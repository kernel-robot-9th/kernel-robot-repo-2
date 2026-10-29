"""팀원 FMS API v1 연동 1단계 — 주문 보내기·이벤트로 배송 단계 바꾸기 (2026-10-27). PostgreSQL 필요.
계약: docs/api_contract_delivery_2026-10-20.md 10장. FMS는 가짜(create_order를 바꿔 끼움) — 네트워크에 나가지 않는다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.clients.fms import FmsRejected, FmsUnavailable
from app.core.config import settings
from app.models import Supply
from app.services.fms_order import FmsOrderSender
from tests.conftest import requires_db

EVENTS = "/api/v1/fms/events"
DELIVERIES = "/api/v1/deliveries"
CLAIM = "/api/v1/robot/deliveries/claim"


@pytest.fixture
def fms(monkeypatch) -> dict:
    """가짜 FMS: 받은 주문을 fms["sent"]에 쌓고 o-1, o-2 …를 준다. fms["reject"]·fms["down"]이면 거절·응답 없음."""
    state: dict = {"sent": [], "reject": None, "down": False}

    def _create_order(base_url: str, request_id: str, room: str, item: str, timeout_seconds: float) -> dict:
        if state["down"]:
            raise FmsUnavailable("connection refused")
        if state["reject"]:
            raise FmsRejected(400, state["reject"], "모르는 병실")
        state["sent"].append({"request_id": request_id, "room": room, "item": item})
        return {"order_id": f"o-{len(state['sent'])}", "request_id": request_id, "room": room, "item": item,
                "status": "queued", "batch_id": None, "robot": None}

    monkeypatch.setattr("app.services.fms_order.create_order", _create_order)
    monkeypatch.setattr(settings, "FMS_BASE_URL", "http://fms.test:8770")
    return state


def _send(db) -> int:
    return FmsOrderSender(db).send_due(datetime.now(UTC))


def _event(client, event_type: str, **fields):
    response = client.post(EVENTS, json={"event_id": f"e-{event_type}", "seq": 1, "time": "2026-10-27T15:00:00+09:00",
                                         "type": event_type, **fields})
    assert response.status_code == 200, response.text
    return response.json()


def _status(client, auth_headers, delivery_id: int) -> dict:
    return client.get(f"{DELIVERIES}/{delivery_id}", headers=auth_headers).json()


# ---- EMR → FMS 주문 ------------------------------------------------------------

@requires_db
def test_sends_one_order_per_item_once_and_blocks_change(client, auth_headers, db, seed, fms, reserve_overdue):
    delivery = reserve_overdue(quantity=2)

    assert _send(db) == 2
    assert fms["sent"] == [
        {"request_id": f"emr-d{delivery['id']}-s{seed['medication'].id}-1", "room": "ROOM_301", "item": "A 약품"},
        {"request_id": f"emr-d{delivery['id']}-s{seed['medication'].id}-2", "room": "ROOM_301", "item": "A 약품"},
    ]
    assert _send(db) == 0 and len(fms["sent"]) == 2   # 다시 보내지 않는다
    assert _status(client, auth_headers, delivery["id"])["status"] == "reserved"   # 출발은 FMS 배차 때

    for call in (lambda: client.post(f"{DELIVERIES}/{delivery['id']}/cancel", headers=auth_headers),
                 lambda: client.patch(f"{DELIVERIES}/{delivery['id']}", headers=auth_headers,
                                      json={"items": [{"supply_id": seed["medication"].id, "quantity": 1}]})):
        response = call()
        assert response.status_code == 409 and response.json()["code"] == "delivery_sent_to_fms"


@requires_db
def test_sends_nothing_when_off_or_not_due(client, auth_headers, db, seed, fms, monkeypatch):
    response = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]})
    assert response.status_code == 201
    assert _send(db) == 0   # 신청 시각 전
    monkeypatch.setattr(settings, "FMS_BASE_URL", "")
    assert _send(db) == 0 and fms["sent"] == []


@requires_db
def test_rejected_or_unreachable_fms_keeps_delivery_for_next_round(client, auth_headers, db, fms, reserve_overdue):
    delivery = reserve_overdue(quantity=1)
    fms["reject"] = "unknown_room"
    assert _send(db) == 0
    fms["reject"], fms["down"] = None, True
    assert _send(db) == 0
    fms["down"] = False
    assert _send(db) == 1   # 다음 회차에 보낸다
    assert _status(client, auth_headers, delivery["id"])["status"] == "reserved"


# ---- FMS → EMR 이벤트 -----------------------------------------------------------

@requires_db
def test_assigned_stays_reserved_called_prepares_parked_dispatches(client, auth_headers, db, fms, reserve_overdue, make_robot,
                                                                     monkeypatch, published):
    """2026-10-29 사용자 "호출부터 준비, 정밀 주차 출발": batch_assigned는 신청 그대로, robot_called → 준비, robot_at_pharmacy → 출발."""
    robot = make_robot("배송로봇 1호")
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {1: robot["id"]})
    first, second = reserve_overdue(quantity=1, minutes_ago=2), reserve_overdue(quantity=1, minutes_ago=1)
    assert _send(db) == 2

    body = _event(client, "batch_assigned", batch_id="b-1", robot=1, name="pinky_6364", count=2, rooms=["ROOM_301"],
                  orders=[{"order_id": "o-1", "room": "ROOM_301", "item": "A 약품"},
                          {"order_id": "o-2", "room": "ROOM_301", "item": "A 약품"}])
    assert body == {"ok": True, "handled": True}
    assert [_status(client, auth_headers, delivery["id"])["status"] for delivery in (first, second)] == ["reserved"] * 2

    assert _event(client, "robot_called", batch_id="b-1", robot=1, eta_s=42)["handled"] is True
    for delivery in (first, second):   # '로봇 한 대 = 진행 중 배송 하나'를 없앤 뒤라 둘 다 같은 로봇 (0015)
        seen = _status(client, auth_headers, delivery["id"])
        assert seen["status"] == "preparing" and seen["assigned_robot_name"] == "배송로봇 1호" and seen["dispatched_at"] is None
    assert "delivery_dispatched" not in [message["event"] for message in published]   # 준비는 알림 없음

    assert _event(client, "robot_at_pharmacy", batch_id="b-1", robot=1)["handled"] is True
    for delivery in (first, second):
        seen = _status(client, auth_headers, delivery["id"])
        assert seen["status"] == "dispatched" and seen["dispatched_at"] is not None
    assert [message["event"] for message in published].count("delivery_dispatched") == 2

    # 같은 이벤트를 다시 보내도 그대로 (알림·기록이 늘지 않음)
    _event(client, "robot_called", batch_id="b-1", robot=1)
    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=1)
    assert [message["event"] for message in published].count("delivery_dispatched") == 2
    events = client.get(f"{DELIVERIES}/{first['id']}/events", headers=auth_headers).json()
    assert [event["event_type"] for event in events] == ["reserved", "preparing", "dispatched"]


@requires_db
def test_arrives_only_when_every_item_is_delivered_then_nurse_receives(client, auth_headers, db, fms, reserve_overdue,
                                                                       make_robot, monkeypatch, published):
    robot = make_robot("배송로봇 1호")
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {2: robot["id"]})
    delivery = reserve_overdue(quantity=2)
    _send(db)
    _event(client, "batch_assigned", batch_id="b-1", robot=2, orders=[{"order_id": "o-1"}, {"order_id": "o-2"}])
    _event(client, "robot_called", batch_id="b-1", robot=2)
    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=2)

    _event(client, "order_delivered", order_id="o-1", room="ROOM_301", robot=2, batch_id="b-1")
    assert _status(client, auth_headers, delivery["id"])["status"] == "dispatched"   # 물품 하나 남음
    _event(client, "order_delivered", order_id="o-2", room="ROOM_301", robot=2, batch_id="b-1")
    seen = _status(client, auth_headers, delivery["id"])
    assert seen["status"] == "arrived" and seen["arrived_at"] is not None
    assert "delivery_arrived" in [message["event"] for message in published]
    _event(client, "order_delivered", order_id="o-2", room="ROOM_301", robot=2, batch_id="b-1")   # 다시 와도 그대로

    received = client.post(f"{DELIVERIES}/{delivery['id']}/receipt", headers=auth_headers)
    assert received.status_code == 200 and received.json()["status"] == "received"


@requires_db
def test_order_failed_fails_delivery_and_restores_stock(client, auth_headers, db, seed, fms, reserve_overdue, make_robot,
                                                        monkeypatch, published):
    robot = make_robot("배송로봇 1호")
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {1: robot["id"]})
    delivery = reserve_overdue(quantity=3)   # 재고 10 → 7
    _send(db)
    _event(client, "batch_assigned", batch_id="b-1", robot=1, orders=[{"order_id": f"o-{n}"} for n in (1, 2, 3)])
    _event(client, "robot_called", batch_id="b-1", robot=1)   # 준비 중에도 실패할 수 있다

    _event(client, "order_failed", order_id="o-2", batch_id="b-1", reason="blocked")
    seen = _status(client, auth_headers, delivery["id"])
    assert seen["status"] == "failed" and seen["failure_reason"] == "robot_error"
    db.refresh(seed["medication"])
    assert db.get(Supply, seed["medication"].id).stock_qty == 10


@requires_db
def test_unknown_orders_and_unmapped_robot_are_ignored(client, auth_headers, db, fms, reserve_overdue, monkeypatch):
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {})
    delivery = reserve_overdue(quantity=1)
    _send(db)
    # 시뮬레이터 화면에서 넣은 주문 등 — 우리 주문이 아니면 무시하고 200
    assert _event(client, "order_delivered", order_id="o-999", room="101호", robot=1, batch_id="b-9")["handled"] is False
    assert _event(client, "robot_departed", robot=1, task="decon", to={"node": "POCKET", "room": None})["handled"] is False
    # 로봇 번호가 EMR 로봇에 이어지지 않으면 준비·출발로 바꾸지 않는다(로그 경고)
    _event(client, "batch_assigned", batch_id="b-1", robot=3, orders=[{"order_id": "o-1"}])
    _event(client, "robot_called", batch_id="b-1", robot=3)
    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=3)
    assert _status(client, auth_headers, delivery["id"])["status"] == "reserved"
    assert _event(client, "robot_called", batch_id="b-9", robot=1)["handled"] is False   # 우리 묶음이 아님


@requires_db
def test_delivered_without_parking_signal_dispatches_then_arrives(client, auth_headers, db, fms, reserve_overdue, make_robot,
                                                                  monkeypatch, published):
    """정밀 주차 신호를 놓쳐도(실물 Pinky 신호를 쓰는데 가상 Pinky가 배송 등) 준비에 멈추지 않고 출발을 남긴 뒤 도착."""
    robot = make_robot("배송로봇 1호")
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {1: robot["id"]})
    delivery = reserve_overdue(quantity=1)
    _send(db)
    _event(client, "batch_assigned", batch_id="b-1", robot=1, orders=[{"order_id": "o-1"}])
    _event(client, "robot_called", batch_id="b-1", robot=1)
    _event(client, "order_delivered", order_id="o-1", room="ROOM_301", robot=1, batch_id="b-1")
    assert _status(client, auth_headers, delivery["id"])["status"] == "arrived"
    events = client.get(f"{DELIVERIES}/{delivery['id']}/events", headers=auth_headers).json()
    assert [event["event_type"] for event in events] == ["reserved", "preparing", "dispatched", "arrived"]


@requires_db
def test_claim_is_closed_while_fms_is_on(client, fms, robot_with_key, reserve_overdue):
    reserve_overdue(quantity=1)
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 204


@requires_db
def test_robot_status_is_accepted(client):
    response = client.post("/api/v1/fms/robot-status", json={"time": "t", "robots": [{"robot": 1, "battery": 90}]})
    assert response.status_code == 200 and response.json() == {"ok": True}
