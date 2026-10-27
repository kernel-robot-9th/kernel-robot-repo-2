"""배송 배정·진행 — 로봇 claim·progress·/robot/me, 삭제 보호 (로드맵 2단계, 2026-10-20). 복귀 장소는 2026-10-27 없앰. PostgreSQL 필요.
계약: docs/api_contract_delivery_2026-10-20.md. 픽스처는 tests/conftest.py.
FOR UPDATE SKIP LOCKED(여러 로봇 동시 claim)는 테스트가 연결 하나를 공유해 여기서 확인할 수 없다 — 실제 스택에서 확인.
"""
from __future__ import annotations

from app.models import Location
from tests.conftest import requires_db

CLAIM = "/api/v1/robot/deliveries/claim"
ME = "/api/v1/robot/me"
DELIVERIES = "/api/v1/deliveries"
ROBOTS = "/api/v1/robots"


def _progress(client, robot: dict, delivery_id: int, stage: str, failure_reason: str | None = None):
    body = {"stage": stage} | ({"failure_reason": failure_reason} if failure_reason else {})
    return client.post(f"/api/v1/robot/deliveries/{delivery_id}/progress", headers=robot["headers"], json=body)


# ---- claim -------------------------------------------------------------------

@requires_db
def test_claim_takes_earliest_overdue_and_is_idempotent(client, auth_headers, robot_with_key, reserve_overdue):
    later = reserve_overdue(minutes_ago=1, quantity=1)
    earlier = reserve_overdue(minutes_ago=10, quantity=1)

    first = client.post(CLAIM, headers=robot_with_key["headers"])
    assert first.status_code == 200 and first.json()["id"] == earlier["id"]
    body = first.json()
    assert body["status"] == "dispatched" and body["dispatched_at"] is not None
    assert body["destination"]["name"] == "301호" and body["destination"]["map_x_m"] == 12.5
    assert body["items"] == [{"name": "A 약품", "quantity": 1}]
    assert "receipt_marker_id" not in body and "nurse_id" not in body  # 로봇용 응답엔 간호사·마커 정보가 없다

    # 멱등: 맡은 배송이 끝날 때까지 같은 것을 돌려준다 (다음 것을 가져가지 않는다)
    again = client.post(CLAIM, headers=robot_with_key["headers"])
    assert again.status_code == 200 and again.json()["id"] == earlier["id"]

    # 간호사 화면: 출발 단계, 맡은 로봇 이름. 출발한 배송은 변경·취소 불가
    seen = client.get(f"{DELIVERIES}/{earlier['id']}", headers=auth_headers).json()
    assert seen["status"] == "dispatched" and seen["assigned_robot_name"] == "배송로봇 1호"
    response = client.post(f"{DELIVERIES}/{earlier['id']}/cancel", headers=auth_headers)
    assert response.status_code == 409 and response.json()["code"] == "delivery_not_reserved"
    assert client.get(f"{DELIVERIES}/{later['id']}", headers=auth_headers).json()["status"] == "reserved"


@requires_db
def test_claim_returns_204_when_nothing_is_due(client, auth_headers, seed, robot_with_key):
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 204
    # 예약 시각이 아직 안 된 것은 가져가지 않는다
    response = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": "2099-01-01T00:00:00+00:00",
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]})
    assert response.status_code == 201
    claim = client.post(CLAIM, headers=robot_with_key["headers"])
    assert claim.status_code == 204 and claim.content == b""


@requires_db
def test_claim_skips_destinations_without_robot_dest(client, db, seed, robot_with_key, reserve_overdue):
    """claim은 로봇 목적지 이름(robot_dest)이 있는 장소의 배송만 내준다 — 좌표만 있고 이름이 없으면 FMS가 /goto로 못 간다 (2026-10-27)."""
    reserve_overdue(destination_id=seed["room_302"].id, minutes_ago=30, quantity=1)  # 302호: 좌표·로봇 목적지 없음
    no_dest_room = Location(name="이름없는방", map_x_m=1.0, map_y_m=1.0, map_yaw_rad=0.0, map_id=seed["ward_map"].id)
    db.add(no_dest_room); db.flush()
    reserve_overdue(destination_id=no_dest_room.id, minutes_ago=20, quantity=1)   # 좌표는 있지만 로봇 목적지 없음
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 204
    reachable = reserve_overdue(minutes_ago=1, quantity=1)
    assert client.post(CLAIM, headers=robot_with_key["headers"]).json()["id"] == reachable["id"]


@requires_db
def test_claim_requires_amr_but_not_home(client, auth_headers, make_robot, db, seed, reserve_overdue):
    reserved = reserve_overdue(quantity=1)
    arm = make_robot("적재팔", robot_type="manipulator")
    response = client.post(CLAIM, headers=arm["headers"])
    assert response.status_code == 403 and response.json()["code"] == "robot_not_amr"

    # 복귀 장소 없이도 맡는다 (2026-10-27: 복귀 장소를 쓰지 않음)
    robot = make_robot("배송로봇 9호")
    response = client.post(CLAIM, headers=robot["headers"])
    assert response.status_code == 200 and response.json()["id"] == reserved["id"]
    assert client.post(CLAIM).status_code == 401


@requires_db
def test_two_robots_take_different_deliveries(client, make_robot, reserve_overdue):
    first, second = reserve_overdue(minutes_ago=5, quantity=1), reserve_overdue(minutes_ago=4, quantity=1)
    robot_a = make_robot("배송로봇 A")
    robot_b = make_robot("배송로봇 B")
    assert client.post(CLAIM, headers=robot_a["headers"]).json()["id"] == first["id"]
    assert client.post(CLAIM, headers=robot_b["headers"]).json()["id"] == second["id"]


# ---- progress ----------------------------------------------------------------

@requires_db
def test_arrived_creates_one_time_marker_for_owner_only(client, auth_headers, general_nurse_headers, robot_with_key, reserve_overdue):
    reserved = reserve_overdue()
    client.post(CLAIM, headers=robot_with_key["headers"])
    response = _progress(client, robot_with_key, reserved["id"], "arrived")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "arrived" and body["arrived_at"] is not None and body["receipt_deadline_at"] is not None
    assert "receipt_marker_id" not in body

    seen = client.get(f"{DELIVERIES}/{reserved['id']}", headers=auth_headers).json()
    assert 50 <= seen["receipt_marker_id"] <= 249 and seen["receipt_deadline_at"] is not None
    # 다른 간호사는 이 배송(과 마커)을 볼 수 없다
    assert client.get(f"{DELIVERIES}/{reserved['id']}", headers=general_nurse_headers).status_code == 403
    # 도착 보고는 다시 해도 같은 결과(마커가 바뀌지 않는다)
    assert _progress(client, robot_with_key, reserved["id"], "arrived").status_code == 200
    assert client.get(f"{DELIVERIES}/{reserved['id']}", headers=auth_headers).json()["receipt_marker_id"] == seen["receipt_marker_id"]


@requires_db
def test_markers_differ_between_arrived_deliveries(client, monkeypatch, make_robot, reserve_overdue, auth_headers):
    from app.services import dispatch

    class FirstFree:  # 무작위 대신 비어 있는 첫 번호 — 두 번째 배송이 첫 번호를 피하는지 본다
        @staticmethod
        def choice(free):
            return free[0]
    monkeypatch.setattr(dispatch, "_marker_random", FirstFree())
    markers = []
    for name in ("배송로봇 A", "배송로봇 B"):
        robot = make_robot(name)
        reserved = reserve_overdue(quantity=1)
        assert client.post(CLAIM, headers=robot["headers"]).json()["id"] == reserved["id"]
        _progress(client, robot, reserved["id"], "arrived")
        markers.append(client.get(f"{DELIVERIES}/{reserved['id']}", headers=auth_headers).json()["receipt_marker_id"])
    assert markers == [50, 51]


@requires_db
def test_failed_restores_stock_and_is_idempotent(client, auth_headers, seed, robot_with_key, reserve_overdue):
    reserved = reserve_overdue(quantity=4)   # 재고 10 → 6
    assert seed["medication"].stock_qty == 6
    client.post(CLAIM, headers=robot_with_key["headers"])
    response = _progress(client, robot_with_key, reserved["id"], "failed", "navigation_failed")
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert seed["medication"].stock_qty == 10   # 재고 복구
    seen = client.get(f"{DELIVERIES}/{reserved['id']}", headers=auth_headers).json()
    assert seen["failure_reason"] == "navigation_failed" and seen["failed_at"] is not None
    # 다시 보내도 재고를 두 번 되돌리지 않는다
    assert _progress(client, robot_with_key, reserved["id"], "failed", "navigation_failed").status_code == 200
    assert seed["medication"].stock_qty == 10
    # 실패한 배송에 도착 보고는 맞지 않는 전이
    response = _progress(client, robot_with_key, reserved["id"], "arrived")
    assert response.status_code == 409 and response.json()["code"] == "delivery_invalid_transition"
    # 로봇은 이제 다음 배송을 맡을 수 있다
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 204


@requires_db
def test_not_received_after_arrival(client, seed, robot_with_key, arrived_delivery):
    response = _progress(client, robot_with_key, arrived_delivery["id"], "failed", "not_received")
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert seed["medication"].stock_qty == 10


@requires_db
def test_failed_after_received_is_409(client, robot_with_key, arrived_delivery):
    client.post(f"/api/v1/robot/deliveries/{arrived_delivery['id']}/receipt", headers=robot_with_key["headers"],
                json={"aruco_marker_id": arrived_delivery["receipt_marker_id"]})
    response = _progress(client, robot_with_key, arrived_delivery["id"], "failed", "not_received")
    assert response.status_code == 409 and response.json()["code"] == "delivery_already_received"


@requires_db
def test_progress_validation_and_ownership(client, make_robot, robot_with_key, reserve_overdue):
    reserved = reserve_overdue(quantity=1)
    # 맡기 전(reserved)에는 어느 로봇도 보고할 수 없다
    response = _progress(client, robot_with_key, reserved["id"], "arrived")
    assert response.status_code == 403 and response.json()["code"] == "delivery_not_assigned_to_robot"
    client.post(CLAIM, headers=robot_with_key["headers"])
    other = make_robot("배송로봇 2호")
    response = _progress(client, other, reserved["id"], "failed", "robot_error")
    assert response.status_code == 403 and response.json()["code"] == "delivery_not_assigned_to_robot"
    # failed에는 사유가 필요하고, arrived에는 사유를 넣지 않는다, 모르는 단계·사유는 422
    assert _progress(client, robot_with_key, reserved["id"], "failed").status_code == 422
    assert client.post(f"/api/v1/robot/deliveries/{reserved['id']}/progress", headers=robot_with_key["headers"],
                       json={"stage": "arrived", "failure_reason": "robot_error"}).status_code == 422
    assert _progress(client, robot_with_key, reserved["id"], "returned").status_code == 422
    assert _progress(client, robot_with_key, reserved["id"], "failed", "battery_low").status_code == 422
    assert _progress(client, robot_with_key, 999999, "arrived").status_code == 404


# ---- /robot/me · 복귀 장소 · 삭제 보호 -------------------------------------------

@requires_db
def test_robot_me_reports_active_delivery(client, make_robot, robot_with_key, reserve_overdue):
    me = client.get(ME, headers=robot_with_key["headers"]).json()
    assert me["robot"]["name"] == "배송로봇 1호" and me["robot"]["robot_type"] == "amr"
    assert "home_location" not in me   # 2026-10-27 없앰
    assert me["active_delivery"] is None and me["receipt_wait_seconds"] == 300

    reserved = reserve_overdue(quantity=1)
    client.post(CLAIM, headers=robot_with_key["headers"])
    me = client.get(ME, headers=robot_with_key["headers"]).json()
    assert me["active_delivery"]["id"] == reserved["id"] and me["active_delivery"]["status"] == "dispatched"

    assert client.get(ME).status_code == 401


@requires_db
def test_home_location_is_gone_and_old_home_does_not_block_delete(client, auth_headers, db, seed, robot_with_key, reserve_overdue):
    """2026-10-27: 복귀 장소를 API에서 없앰. DB에 예전 값이 남아 있어도 그 장소를 지울 수 있다(값을 비우고 지움)."""
    from app.models import Robot

    robot_id = robot_with_key["id"]
    assert "home_location_id" not in client.get(f"{ROBOTS}/{robot_id}").json()
    ignored = client.patch(f"{ROBOTS}/{robot_id}", headers=auth_headers, json={"home_location_id": seed["room_302"].id})
    assert ignored.status_code == 200 and db.get(Robot, robot_id).home_location_id is None   # 보내도 무시

    old_home = Location(name="예전복귀", map_x_m=1.0, map_y_m=1.0, map_yaw_rad=0.0, map_id=seed["ward_map"].id)
    db.add(old_home); db.flush()
    db.get(Robot, robot_id).home_location_id = old_home.id; db.flush()
    assert client.delete(f"/api/v1/locations/{old_home.id}", headers=auth_headers).status_code == 204
    db.expire_all()
    assert db.get(Robot, robot_id).home_location_id is None

    # 진행 중 배송을 맡은 로봇은 지울 수 없다
    reserve_overdue(quantity=1)
    client.post(CLAIM, headers=robot_with_key["headers"])
    response = client.delete(f"{ROBOTS}/{robot_id}", headers=auth_headers)
    assert response.status_code == 409 and response.json()["code"] == "robot_has_active_delivery"


# ---- 알림 (2026-10-20) --------------------------------------------------------

def _events(published: list[dict]) -> list[str]:
    return [message["event"] for message in published if message["event"].startswith("delivery_")]


@requires_db
def test_stage_notifications_go_to_owner_and_failure_to_admins(client, seed, robot_with_key, reserve_overdue, published):
    reserved = reserve_overdue(quantity=1)
    published.clear()
    client.post(CLAIM, headers=robot_with_key["headers"])
    client.post(CLAIM, headers=robot_with_key["headers"])   # 멱등 claim은 알림을 다시 내지 않는다
    _progress(client, robot_with_key, reserved["id"], "arrived")
    _progress(client, robot_with_key, reserved["id"], "arrived")   # 멱등
    _progress(client, robot_with_key, reserved["id"], "failed", "not_received")
    _progress(client, robot_with_key, reserved["id"], "failed", "not_received")   # 멱등
    assert _events(published) == ["delivery_dispatched", "delivery_arrived", "delivery_failed"]

    dispatched, arrived, failed = [message for message in published if message["event"].startswith("delivery_")]
    for message in (dispatched, arrived, failed):
        assert message["recipient_nurse_id"] == seed["nurse"].id and message["delivery_id"] == reserved["id"]
        assert message["destination_location_name"] == "301호" and message["robot_name"] == "배송로봇 1호"
    assert 50 <= arrived["receipt_marker_id"] <= 249 and arrived["receipt_deadline_at"] is not None
    assert "recipient_role" not in arrived   # 마커는 예약자에게만 — 관리자에게 가지 않는다
    assert failed["recipient_role"] == "admin" and failed["failure_reason"] == "not_received"


@requires_db
def test_rejected_progress_sends_no_notification(client, make_robot, robot_with_key, reserve_overdue, published):
    reserved = reserve_overdue(quantity=1)
    client.post(CLAIM, headers=robot_with_key["headers"])
    published.clear()
    other = make_robot("배송로봇 2호")
    assert _progress(client, other, reserved["id"], "arrived").status_code == 403
    assert _events(published) == []


@requires_db
def test_location_robot_dest_reaches_robot(client, auth_headers, robot_with_key, reserve_overdue, seed):
    """장소의 로봇 목적지 이름(Pinky /dests, 2026-10-22)이 로봇용 응답 destination에 실린다. 이름은 장소 하나에만."""
    set_dest = client.patch(f"/api/v1/locations/{seed['room_301'].id}", headers=auth_headers, json={"robot_dest": "ROOM1_CUL"})
    assert set_dest.status_code == 200 and set_dest.json()["robot_dest"] == "ROOM1_CUL"
    duplicate = client.patch(f"/api/v1/locations/{seed['room_302'].id}", headers=auth_headers, json={"robot_dest": "ROOM1_CUL"})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "location_robot_dest_duplicate"
    reserve_overdue()
    claimed = client.post("/api/v1/robot/deliveries/claim", headers=robot_with_key["headers"]).json()
    assert claimed["destination"]["robot_dest"] == "ROOM1_CUL"


@requires_db
def test_robot_arrived_is_pharmacy_only(client, auth_headers, robot_with_key, reserve_overdue, published):
    """POST /robot/arrived (2026-10-27 약제실 전용): 배송 id 없이 약제실 도착을 알린다 — 로그만, 상태·알림·기록은 그대로.
    병실 도착은 progress arrived. 맡은 것이 없으면 409, 병실 도착 뒤에 부르면 409."""
    nothing = client.post("/api/v1/robot/arrived", headers=robot_with_key["headers"])
    assert nothing.status_code == 409 and nothing.json()["code"] == "robot_no_active_delivery"
    assert client.post("/api/v1/robot/arrived").status_code == 401   # 로봇 키 필요
    reserved = reserve_overdue()
    assert client.post("/api/v1/robot/deliveries/claim", headers=robot_with_key["headers"]).json()["id"] == reserved["id"]
    at_pharmacy = client.post("/api/v1/robot/arrived", headers=robot_with_key["headers"])
    assert at_pharmacy.status_code == 200 and at_pharmacy.json()["id"] == reserved["id"]
    assert at_pharmacy.json()["status"] == "dispatched" and at_pharmacy.json()["arrived_at"] is None
    assert client.post("/api/v1/robot/arrived", headers=robot_with_key["headers"]).json()["status"] == "dispatched"   # 여러 번 불러도 같다
    assert not [m for m in published if m["event"] == "delivery_arrived"]   # 간호사에게 도착 알림이 가지 않는다
    events = client.get(f"/api/v1/deliveries/{reserved['id']}/events", headers=auth_headers).json()
    assert [event["event_type"] for event in events] == ["reserved", "dispatched"]   # 배송 기록에도 남지 않는다
    room = client.post(f"/api/v1/robot/deliveries/{reserved['id']}/progress", headers=robot_with_key["headers"], json={"stage": "arrived"})
    assert room.status_code == 200 and room.json()["status"] == "arrived"   # 병실 도착은 progress
    after_room = client.post("/api/v1/robot/arrived", headers=robot_with_key["headers"])
    assert after_room.status_code == 409 and after_room.json()["code"] == "delivery_invalid_transition"


@requires_db
def test_robot_lists_waiting_deliveries_without_claiming(client, robot_with_key, reserve_overdue):
    """GET /robot/deliveries (2026-10-22): 맡지 않은 예약을 보기만 — 로봇 배정·상태 변경 없음."""
    overdue = reserve_overdue()
    listed = client.get("/api/v1/robot/deliveries", headers=robot_with_key["headers"])
    assert listed.status_code == 200 and [d["id"] for d in listed.json()] == [overdue["id"]]
    assert listed.json()[0]["status"] == "reserved" and "receipt_marker_id" not in listed.json()[0]
    assert client.get("/api/v1/robot/me", headers=robot_with_key["headers"]).json()["active_delivery"] is None   # 맡지 않았다
    assert client.get("/api/v1/robot/deliveries").status_code == 401   # 로봇 키 필요(켜져 있을 때)
