"""FMS 묶음을 실제 OMX로 싣기 — 2단계 (2026-10-27). PostgreSQL 필요. OMX·FMS는 가짜 — 로봇팔이 움직이지 않는다.
계약: docs/api_contract_delivery_2026-10-20.md 10.4. 순서: /command {"blue": N, "green": N} → ready → (정밀 주차) → /pinky → loaded
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import FmsBatch
from app.services.fms_omx import FmsOmxRunner
from app.services.fms_order import FmsOrderSender
from tests.conftest import requires_db

EVENTS = "/api/v1/fms/events"
IDLE = {"request_id": "earlier", "state": "completed", "pinky": "completed"}


@pytest.fixture
def arm(monkeypatch, make_robot) -> dict:
    """가짜 FMS(주문·ready·loaded)와 가짜 OMX(/command·/pinky·/status). calls에 부른 순서대로 쌓인다.
    arm["status"]를 바꾸면 OMX /status 응답이 바뀐다."""
    robot = make_robot("배송로봇 1호")
    state: dict = {"calls": [], "status": dict(IDLE), "orders": 0, "fms_batch_status": "at_pharmacy", "robot": robot}

    def _create_order(base_url, request_id, room, item, timeout_seconds):
        state["orders"] += 1
        return {"order_id": f"o-{state['orders']}", "status": "queued"}

    def _batch_step(base_url, batch_id, step, timeout_seconds):
        state["calls"].append(("fms", step, batch_id))
        return {"batch_id": batch_id, "status": "called" if step == "ready" else "delivering"}

    def _send_command(base_url, counts, request_id, timeout_seconds):
        state["calls"].append(("omx", "command", counts, request_id))
        state["status"] = {"request_id": request_id, "state": "running", "pinky": None}
        return {"accepted": True}

    def _send_pinky(base_url, request_id, timeout_seconds):
        state["calls"].append(("omx", "pinky", request_id))
        return {"accepted": True}

    monkeypatch.setattr("app.services.fms_order.create_order", _create_order)
    monkeypatch.setattr("app.services.fms_omx.batch_step", _batch_step)
    monkeypatch.setattr("app.services.fms_omx.get_batch",
                        lambda base_url, batch_id, timeout_seconds: {"batch_id": batch_id, "status": state["fms_batch_status"]})
    monkeypatch.setattr("app.services.fms_omx.send_command", _send_command)
    monkeypatch.setattr("app.services.fms_omx.send_pinky", _send_pinky)
    monkeypatch.setattr("app.services.fms_omx.get_status", lambda base_url, timeout_seconds: dict(state["status"]))
    monkeypatch.setattr(settings, "FMS_BASE_URL", "http://fms.test:8770")
    monkeypatch.setattr(settings, "FMS_OMX_ENABLED", True)
    monkeypatch.setattr(settings, "FMS_ROBOT_MAP", {1: robot["id"]})
    return state


def _round(db) -> None:
    FmsOmxRunner(db).run_round(datetime.now(UTC))


def _event(client, event_type: str, **fields) -> None:
    response = client.post(EVENTS, json={"event_id": f"e-{event_type}", "seq": 1, "type": event_type, **fields})
    assert response.status_code == 200, response.text


def _assign(client, db, batch_id: str, order_ids: list[str]) -> FmsBatch:
    FmsOrderSender(db).send_due(datetime.now(UTC))
    _event(client, "batch_assigned", batch_id=batch_id, robot=1, orders=[{"order_id": order_id} for order_id in order_ids])
    return db.scalar(select(FmsBatch).where(FmsBatch.batch_id == batch_id))


@requires_db
def test_two_medicines_go_command_ready_pinky_loaded(client, db, arm, reserve_overdue):
    reserve_overdue(quantity=2)   # A 약품 ×2 → blue 2
    batch = _assign(client, db, "b-1", ["o-1", "o-2"])
    assert (batch.blue_count, batch.green_count, batch.step) == (2, 0, "pick")

    _round(db)   # 집기 명령 — 묶음 하나에 한 번
    assert arm["calls"] == [("omx", "command", {"blue": 2}, f"emr-b{batch.id}")]   # 0인 green은 뺀다(10-28)
    assert batch.step == "picking"
    _round(db)   # 아직 running
    assert batch.step == "picking"

    arm["status"] = {"request_id": f"emr-b{batch.id}", "state": "completed", "pinky": "holding"}
    _round(db)
    assert batch.step == "ready"
    _round(db)   # FMS ready → Pinky가 약제실로
    assert arm["calls"][-1] == ("fms", "ready", "b-1") and batch.step == "called"
    _round(db)   # 정밀 주차 전에는 내려놓지 않는다
    assert batch.step == "called" and len(arm["calls"]) == 2

    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=1)
    _round(db)
    assert batch.step == "pinky"
    _round(db)   # 내려놓기
    assert arm["calls"][-1] == ("omx", "pinky", f"emr-b{batch.id}") and batch.step == "loading"
    arm["status"] = {"request_id": f"emr-b{batch.id}", "state": "completed", "pinky": "returning"}
    _round(db)
    assert batch.step == "loading"
    arm["status"]["pinky"] = "completed"
    _round(db)
    assert batch.step == "loaded"
    _round(db)   # FMS loaded → Pinky가 병실로
    assert arm["calls"][-1] == ("fms", "loaded", "b-1") and batch.step == "delivering"
    assert [call[1] for call in arm["calls"]] == ["command", "ready", "pinky", "loaded"]


@requires_db
def test_no_command_while_arm_holds_another_batch(client, db, arm, reserve_overdue):
    reserve_overdue(quantity=1, minutes_ago=2)
    first = _assign(client, db, "b-1", ["o-1"])
    _round(db)
    arm["status"] = {"request_id": f"emr-b{first.id}", "state": "completed", "pinky": "holding"}
    _round(db)
    _round(db)   # first: ready → called (들고 대기)

    reserve_overdue(quantity=1, minutes_ago=1)
    second = _assign(client, db, "b-2", ["o-2"])
    for _ in range(3):
        _round(db)
    assert second.step == "pick"   # OMX가 첫 묶음을 들고 있는 동안 두 번째 /command를 보내지 않는다
    assert [call[1] for call in arm["calls"]].count("command") == 1


@requires_db
def test_omx_failure_stops_batch(client, db, arm, reserve_overdue):
    reserve_overdue(quantity=1)
    batch = _assign(client, db, "b-1", ["o-1"])
    _round(db)
    arm["status"] = {"request_id": f"emr-b{batch.id}", "state": "failed", "pinky": None, "error": "no blue_gauze in area"}
    _round(db)
    assert batch.step == "failed" and "no blue_gauze" in batch.error
    _round(db)
    assert [call[1] for call in arm["calls"]] == ["command"]   # 멈춘 뒤에는 아무것도 보내지 않는다


@requires_db
def test_off_by_default_keeps_virtual_omx(client, db, arm, reserve_overdue, monkeypatch):
    monkeypatch.setattr(settings, "FMS_OMX_ENABLED", False)
    reserve_overdue(quantity=1)
    assert _assign(client, db, "b-1", ["o-1"]) is None   # 묶음을 만들지 않는다 — ready·loaded는 FMS 가상 OMX
    _round(db)
    assert arm["calls"] == []


@requires_db
def test_sentence_mode_sends_gauze_sentence_once(client, db, arm, reserve_overdue, monkeypatch):
    """임시(10-27): 실제 OMX가 문장만 받는 동안 — 묶음의 수량은 무시하고 거즈 문장 한 번."""
    monkeypatch.setattr(settings, "OMX_COMMAND_FORMAT", "sentence")
    reserve_overdue(quantity=2)
    batch = _assign(client, db, "b-1", ["o-1", "o-2"])
    _round(db)
    assert arm["calls"] == [("omx", "command", "pick and place blue gauze", f"emr-b{batch.id}")]


@requires_db
def test_fixed_mode_sends_one_blue_one_green(client, db, arm, reserve_overdue, monkeypatch):
    """시연(10-30): OMX_COMMAND_FORMAT=fixed면 묶음 개수와 상관없이 {"blue": 1, "green": 1}, 묶음 개수는 그대로."""
    monkeypatch.setattr(settings, "OMX_COMMAND_FORMAT", "fixed")
    reserve_overdue(quantity=3)
    batch = _assign(client, db, "b-1", ["o-1", "o-2", "o-3"])
    _round(db)
    assert arm["calls"] == [("omx", "command", {"blue": 1, "green": 1}, f"emr-b{batch.id}")]
    assert (batch.blue_count, batch.green_count) == (3, 0)


@requires_db
def test_omx_format_not_supported_skips_loading(client, db, arm, reserve_overdue, monkeypatch):
    """10-28 사용자 "OMX 양식이 없으면 생략": /command가 422면 OMX 적재 없이 ready → 정밀 주차 → loaded (/pinky 없음)."""
    from app.clients.omx import OmxRejected

    def _reject(base_url, command, request_id, timeout_seconds):
        arm["calls"].append(("omx", "command", command, request_id))
        raise OmxRejected(422, [{"msg": "Input should be a valid string"}])

    monkeypatch.setattr("app.services.fms_omx.send_command", _reject)
    reserve_overdue(quantity=1)
    batch = _assign(client, db, "b-1", ["o-1"])
    _round(db)
    assert batch.step == "ready" and batch.omx_request_id is None and "422" in batch.error
    _round(db)
    assert arm["calls"][-1] == ("fms", "ready", "b-1") and batch.step == "called"
    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=1)
    _round(db)
    assert batch.step == "loaded"
    _round(db)
    assert [call[1] for call in arm["calls"]] == ["command", "ready", "loaded"] and batch.step == "delivering"


@requires_db
def test_skipped_batch_does_not_block_next_batch_on_omx(client, db, arm, reserve_overdue, monkeypatch):
    """생략한 묶음이 Pinky를 기다리는 동안에도 다른 묶음은 OMX를 쓸 수 있다."""
    from app.clients.omx import OmxRejected

    calls = {"n": 0}
    real_send = __import__("app.services.fms_omx", fromlist=["send_command"]).send_command

    def _first_rejected(base_url, command, request_id, timeout_seconds):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OmxRejected(422, "format")
        return real_send(base_url, command, request_id, timeout_seconds)

    monkeypatch.setattr("app.services.fms_omx.send_command", _first_rejected)
    reserve_overdue(quantity=1, minutes_ago=2)
    first = _assign(client, db, "b-1", ["o-1"])
    _round(db)
    _round(db)   # first: ready → called (Pinky 기다림, OMX는 안 씀)
    assert first.step == "called"
    reserve_overdue(quantity=1, minutes_ago=1)
    second = _assign(client, db, "b-2", ["o-2"])
    _round(db)
    assert second.step == "picking"


def _hold(arm, batch) -> None:
    arm["status"] = {"request_id": f"emr-b{batch.id}", "state": "completed", "pinky": "holding"}


@requires_db
def test_pinky_signal_mode_puts_down_after_real_pinky_docks(client, auth_headers, db, arm, reserve_overdue, monkeypatch):
    """10-28 사용자 "정밀 주차 완료 후": FMS_PHARMACY_SIGNAL=pinky면 FMS robot_at_pharmacy가 아니라
    실물 Pinky의 POST /robot/arrived(정밀 주차 끝)를 받은 뒤에 /pinky. 배송 출발도 그 신호로 (10-29 "정밀 주차 출발")."""
    monkeypatch.setattr(settings, "FMS_PHARMACY_SIGNAL", "pinky")
    delivery = reserve_overdue(quantity=1)
    batch = _assign(client, db, "b-1", ["o-1"])
    _round(db); _hold(arm, batch); _round(db); _round(db)
    assert batch.step == "called"

    _event(client, "robot_called", batch_id="b-1", robot=1)
    _event(client, "robot_at_pharmacy", batch_id="b-1", robot=1)   # 가상 FMS의 정밀 주차 — 무시
    _round(db)
    assert batch.step == "called" and batch.at_pharmacy_at is None
    status = lambda: client.get(f"/api/v1/deliveries/{delivery['id']}", headers=auth_headers).json()["status"]  # noqa: E731
    assert status() == "preparing"

    response = client.post("/api/v1/robot/arrived", headers=arm["robot"]["headers"],
                           json={"event": "arrived", "dest": "PHARMACY", "job_id": "b86a97fa",
                                 "dock_error": {"fwd_mm": -7.3, "left_mm": -3.4, "heading_deg": -0.94}})
    assert response.status_code == 200 and response.json()["id"] == delivery["id"]
    assert status() == "dispatched"
    _round(db)
    assert batch.step == "pinky"
    _round(db)
    assert arm["calls"][-1] == ("omx", "pinky", f"emr-b{batch.id}")


@requires_db
def test_loaded_waits_until_fms_batch_is_at_pharmacy(client, db, arm, reserve_overdue, monkeypatch):
    """실물 Pinky로 먼저 실었어도 FMS 묶음이 아직 called면 loaded를 보내지 않고 기다린다(409를 '넘어감'으로 잘못 보지 않게)."""
    monkeypatch.setattr(settings, "FMS_PHARMACY_SIGNAL", "pinky")
    reserve_overdue(quantity=1)
    batch = _assign(client, db, "b-1", ["o-1"])
    _round(db); _hold(arm, batch); _round(db); _round(db)
    client.post("/api/v1/robot/arrived", headers=arm["robot"]["headers"], json={"dest": "PHARMACY"})
    _round(db); _round(db)
    arm["status"]["pinky"] = "completed"
    _round(db)
    assert batch.step == "loaded"
    arm["fms_batch_status"] = "called"
    _round(db); _round(db)
    assert batch.step == "loaded" and "loaded" not in [call[1] for call in arm["calls"]]
    arm["fms_batch_status"] = "at_pharmacy"
    _round(db)
    assert batch.step == "delivering" and arm["calls"][-1] == ("fms", "loaded", "b-1")

