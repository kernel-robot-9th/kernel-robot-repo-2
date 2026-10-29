"""배송 기록 — 간호사 예약·변경·취소, 로봇 출발·도착·수령·실패, 본인·관리자 조회 (로드맵 4단계, 2026-10-21). PostgreSQL 필요.
기록은 상태를 바꾼 요청과 같은 트랜잭션 — 거부(409·403)·멱등 재보고는 남지 않는다. 일회용 마커 번호는 기록하지 않는다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.conftest import requires_db

DELIVERIES = "/api/v1/deliveries"
EVENTS = "/api/v1/delivery-events"
CLAIM = "/api/v1/robot/deliveries/claim"
ROBOTS = "/api/v1/robots"


def _history(client, headers, delivery_id: int):
    response = client.get(f"{DELIVERIES}/{delivery_id}/events", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _types(events: list[dict]) -> list[str]:
    return [event["event_type"] for event in events]


def _progress(client, robot: dict, delivery_id: int, stage: str, failure_reason: str | None = None):
    body = {"stage": stage} | ({"failure_reason": failure_reason} if failure_reason else {})
    return client.post(f"/api/v1/robot/deliveries/{delivery_id}/progress", headers=robot["headers"], json=body)


def _nurse_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _future(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


# ---- 간호사 사건 ---------------------------------------------------------------

@requires_db
def test_reserve_update_cancel_are_recorded_with_snapshots(client, auth_headers, seed):
    created = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": _future(2),
        "items": [{"supply_id": seed["medication"].id, "quantity": 2}]})
    assert created.status_code == 201
    delivery_id = created.json()["id"]

    reserved = _history(client, auth_headers, delivery_id)
    assert _types(reserved) == ["reserved"]
    assert reserved[0]["actor_type"] == "nurse" and reserved[0]["actor_name"] == "김간호"
    assert reserved[0]["details"]["destination"] == {"id": seed["room_301"].id, "name": "301호"}
    assert reserved[0]["details"]["items"] == [{"supply_id": seed["medication"].id, "name": "A 약품", "quantity": 2}]

    # 바뀐 것만 남는다 — 목적지·품목만 바꾸면 scheduled_at은 없다
    changed = client.patch(f"{DELIVERIES}/{delivery_id}", headers=auth_headers, json={
        "destination_location_id": seed["room_302"].id,
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}, {"supply_id": seed["blanket"].id, "quantity": 1}]})
    assert changed.status_code == 200
    updated = _history(client, auth_headers, delivery_id)[-1]
    assert updated["event_type"] == "updated"
    assert set(updated["details"]) == {"destination", "items"}
    assert updated["details"]["destination"] == {"from": {"id": seed["room_301"].id, "name": "301호"},
                                                 "to": {"id": seed["room_302"].id, "name": "302호"}}
    assert [item["quantity"] for item in updated["details"]["items"]["from"]] == [2]
    assert {item["name"] for item in updated["details"]["items"]["to"]} == {"A 약품", "이불"}

    # 같은 값으로 다시 보내면 기록하지 않는다
    same = client.patch(f"{DELIVERIES}/{delivery_id}", headers=auth_headers,
                        json={"destination_location_id": seed["room_302"].id})
    assert same.status_code == 200
    assert _types(_history(client, auth_headers, delivery_id)) == ["reserved", "updated"]

    assert client.post(f"{DELIVERIES}/{delivery_id}/cancel", headers=auth_headers).status_code == 200
    cancelled = _history(client, auth_headers, delivery_id)
    assert _types(cancelled) == ["reserved", "updated", "cancelled"]
    assert cancelled[-1]["details"] is None


@requires_db
def test_rejected_nurse_requests_leave_no_record(client, auth_headers, seed):
    # 재고 부족 예약(409)은 롤백 — 배송도 기록도 없다
    too_many = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": _future(2),
        "items": [{"supply_id": seed["medication"].id, "quantity": 99}]})
    assert too_many.status_code == 409
    assert client.get(EVENTS, headers=auth_headers).json() == []

    created = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": _future(2),
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]}).json()
    assert client.post(f"{DELIVERIES}/{created['id']}/cancel", headers=auth_headers).status_code == 200
    # 이미 취소된 예약을 또 취소(409) — 기록이 늘지 않는다
    assert client.post(f"{DELIVERIES}/{created['id']}/cancel", headers=auth_headers).status_code == 409
    assert _types(_history(client, auth_headers, created["id"])) == ["reserved", "cancelled"]


# ---- 로봇 사건 -----------------------------------------------------------------

@requires_db
def test_robot_flow_is_recorded_without_receipt_marker(client, auth_headers, robot_with_key, arrived_delivery):
    delivery_id = arrived_delivery["id"]
    # 멱등 재보고(arrived 두 번)는 기록하지 않는다
    assert _progress(client, robot_with_key, delivery_id, "arrived").status_code == 200
    # 틀린 마커(403)도 기록하지 않는다
    wrong_marker = 50 if arrived_delivery["receipt_marker_id"] != 50 else 51
    rejected = client.post(f"/api/v1/robot/deliveries/{delivery_id}/receipt", headers=robot_with_key["headers"],
                           json={"aruco_marker_id": wrong_marker})
    assert rejected.status_code == 403
    received = client.post(f"/api/v1/robot/deliveries/{delivery_id}/receipt", headers=robot_with_key["headers"],
                           json={"aruco_marker_id": arrived_delivery["receipt_marker_id"]})
    assert received.status_code == 200

    events = _history(client, auth_headers, delivery_id)
    assert _types(events) == ["reserved", "dispatched", "arrived", "received"]
    robot_events = events[1:]
    assert all(event["actor_type"] == "robot" and event["actor_name"] == "배송로봇 1호"
               and event["actor_robot_id"] == robot_with_key["id"] for event in robot_events)
    # 일회용 마커 번호는 어디에도 남기지 않는다
    assert all(event["details"] is None for event in robot_events)
    assert str(arrived_delivery["receipt_marker_id"]) not in str(events)
    times = [event["occurred_at"] for event in events]
    assert times == sorted(times)


@requires_db
def test_robot_failure_records_reason_once(client, auth_headers, robot_with_key, reserve_overdue):
    reserved = reserve_overdue()
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200  # 멱등 claim — 출발은 한 번만
    assert _progress(client, robot_with_key, reserved["id"], "failed", "navigation_failed").status_code == 200
    assert _progress(client, robot_with_key, reserved["id"], "failed", "navigation_failed").status_code == 200
    # 실패 뒤 도착 보고는 409 — 기록 없음
    assert _progress(client, robot_with_key, reserved["id"], "arrived").status_code == 409

    events = _history(client, auth_headers, reserved["id"])
    assert _types(events) == ["reserved", "dispatched", "failed"]
    assert events[-1]["details"] == {"failure_reason": "navigation_failed"}


@requires_db
def test_robot_name_survives_robot_deletion(client, auth_headers, robot_with_key, reserve_overdue):
    reserved = reserve_overdue()
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    assert _progress(client, robot_with_key, reserved["id"], "failed", "robot_error").status_code == 200
    assert client.delete(f"{ROBOTS}/{robot_with_key['id']}", headers=auth_headers).status_code == 204

    robot_events = _history(client, auth_headers, reserved["id"])[1:]
    assert [(event["actor_name"], event["actor_robot_id"]) for event in robot_events] == [
        ("배송로봇 1호", None), ("배송로봇 1호", None)]


# ---- 권한 ----------------------------------------------------------------------

@requires_db
def test_history_is_for_owner_and_admin_only(client, auth_headers, general_nurse_headers, reserve_overdue):
    mine = reserve_overdue(headers=general_nurse_headers)
    others = reserve_overdue()   # N001(관리자)의 예약

    assert _types(_history(client, general_nurse_headers, mine["id"])) == ["reserved"]
    denied = client.get(f"{DELIVERIES}/{others['id']}/events", headers=general_nurse_headers)
    assert denied.status_code == 403 and denied.json()["code"] == "delivery_not_owned"
    # 관리자는 남의 배송 기록도 본다
    assert _types(_history(client, auth_headers, mine["id"])) == ["reserved"]
    missing = client.get(f"{DELIVERIES}/999999/events", headers=auth_headers)
    assert missing.status_code == 404 and missing.json()["code"] == "delivery_not_found"


@requires_db
def test_admin_list_filters_and_requires_admin(
    client, auth_headers, general_nurse_headers, make_robot, robot_with_key, reserve_overdue, seed,
):
    other_robot = make_robot("배송로봇 2호")
    first = reserve_overdue(minutes_ago=10)                              # N001 예약 → robot_with_key
    second = reserve_overdue(minutes_ago=5, headers=general_nurse_headers)  # N090 예약 → other_robot
    assert client.post(CLAIM, headers=robot_with_key["headers"]).json()["id"] == first["id"]
    assert client.post(CLAIM, headers=other_robot["headers"]).json()["id"] == second["id"]

    denied = client.get(EVENTS, headers=general_nurse_headers)
    assert denied.status_code == 403 and denied.json()["code"] == "admin_required"

    everything = client.get(EVENTS, headers=auth_headers).json()
    assert len(everything) == 4
    # 최근 것부터
    assert [event["occurred_at"] for event in everything] == sorted((event["occurred_at"] for event in everything),
                                                                    reverse=True)
    assert {event["destination_location_name"] for event in everything} == {"301호"}
    assert {event["requester_name"] for event in everything} == {"김간호", "일반간호"}
    assert {event["requester_type"] for event in everything} == {"nurse"}

    def ids(**params):
        response = client.get(EVENTS, headers=auth_headers, params=params)
        assert response.status_code == 200, response.text
        return sorted((event["delivery_id"], event["event_type"]) for event in response.json())

    assert ids(event_type="dispatched") == [(first["id"], "dispatched"), (second["id"], "dispatched")]
    assert ids(robot_id=other_robot["id"]) == [(second["id"], "dispatched")]
    nurse_090 = _nurse_id(client, general_nurse_headers)
    assert ids(nurse_id=nurse_090) == [(second["id"], "dispatched"), (second["id"], "reserved")]
    assert ids(delivery_id=first["id"]) == [(first["id"], "dispatched"), (first["id"], "reserved")]
    assert ids(since=_future(1)) == []
    assert len(ids(until=_future(1))) == 4
    assert len(ids(limit=1)) == 1
    # 시간대 없는 시각은 422
    assert client.get(EVENTS, headers=auth_headers, params={"since": "2026-10-21T00:00:00"}).status_code == 422

