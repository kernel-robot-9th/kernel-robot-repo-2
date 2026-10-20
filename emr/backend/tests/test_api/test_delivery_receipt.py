"""배송 수령 확인 — 로봇별 API 키 + 도착 때 생기는 일회용 마커 (2026-10-19, 규칙 변경 2026-10-20). PostgreSQL 필요.
픽스처(robot_with_key·arrived_delivery·reserve_overdue·make_robot·published)는 tests/conftest.py.
"""
from __future__ import annotations

from tests.conftest import requires_db

ROBOTS = "/api/v1/robots"
DELIVERIES = "/api/v1/deliveries"


def _receipt_url(delivery_id: int) -> str:
    return f"/api/v1/robot/deliveries/{delivery_id}/receipt"


@requires_db
def test_robot_api_key_issue_is_admin_only_and_shown_once(client, auth_headers, general_nurse_headers, robot_with_key):
    robot_id = robot_with_key["id"]
    assert robot_with_key["api_key"].startswith("emr_rk_")
    response = client.post(f"{ROBOTS}/{robot_id}/api-key", headers=general_nurse_headers)
    assert response.status_code == 403 and response.json()["code"] == "admin_required"
    assert client.post(f"{ROBOTS}/{robot_id}/api-key").status_code == 401
    assert client.post(f"{ROBOTS}/999999/api-key", headers=auth_headers).status_code == 404

    # 조회(무인증)에는 키가 있는지만 나오고 키·해시는 없다
    robot = client.get(f"{ROBOTS}/{robot_id}").json()
    assert robot["has_api_key"] is True and robot["api_key_issued_at"] is not None
    assert robot_with_key["api_key"] not in str(robot) and "api_key_hash" not in robot


@requires_db
def test_receipt_requires_valid_robot_key(client, auth_headers, robot_with_key, arrived_delivery):
    url = _receipt_url(arrived_delivery["id"])
    body = {"aruco_marker_id": arrived_delivery["receipt_marker_id"]}
    response = client.post(url, json=body)
    assert response.status_code == 401 and response.json()["code"] == "robot_key_missing"
    response = client.post(url, json=body, headers={"X-Robot-Api-Key": "emr_rk_wrong"})
    assert response.status_code == 401 and response.json()["code"] == "robot_key_invalid"
    # 간호사 토큰만으로는 부를 수 없다
    assert client.post(url, json=body, headers=auth_headers).json()["code"] == "robot_key_missing"

    # 재발급하면 이전 키는 무효
    new_key = client.post(f"{ROBOTS}/{robot_with_key['id']}/api-key", headers=auth_headers).json()["api_key"]
    assert client.post(url, json=body, headers=robot_with_key["headers"]).json()["code"] == "robot_key_invalid"
    # 폐기하면 새 키도 무효
    assert client.delete(f"{ROBOTS}/{robot_with_key['id']}/api-key", headers=auth_headers).status_code == 204
    assert client.get(f"{ROBOTS}/{robot_with_key['id']}").json()["has_api_key"] is False
    assert client.post(url, json=body, headers={"X-Robot-Api-Key": new_key}).json()["code"] == "robot_key_invalid"
    assert client.get(f"{DELIVERIES}/{arrived_delivery['id']}", headers=auth_headers).json()["status"] == "arrived"


@requires_db
def test_receipt_with_one_time_marker(client, auth_headers, db, seed, robot_with_key, arrived_delivery):
    marker = arrived_delivery["receipt_marker_id"]
    assert 50 <= marker <= 249
    response = client.post(_receipt_url(arrived_delivery["id"]), json={"aruco_marker_id": marker}, headers=robot_with_key["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"
    assert "receipt_marker_id" not in response.json()  # 로봇용 응답엔 마커가 없다
    assert seed["medication"].stock_qty == 7  # 재고는 예약 때 뺀 그대로

    # 간호사 화면에서 수령으로 보이고, 받은 간호사 = 예약한 간호사, 받은 로봇 = 맡은 로봇
    seen = client.get(f"{DELIVERIES}/{arrived_delivery['id']}", headers=auth_headers).json()
    assert seen["status"] == "received" and seen["received_at"] is not None
    assert seen["received_by_nurse_id"] == seed["nurse"].id and seen["received_by_robot_id"] == robot_with_key["id"]
    # 더는 변경·취소·재수령할 수 없다
    assert client.post(f"{DELIVERIES}/{arrived_delivery['id']}/cancel", headers=auth_headers).json()["code"] == "delivery_not_reserved"
    response = client.post(_receipt_url(arrived_delivery["id"]), json={"aruco_marker_id": marker}, headers=robot_with_key["headers"])
    assert response.status_code == 409 and response.json()["code"] == "delivery_not_arrived"

    # 배송이 끝났으니 로봇을 지울 수 있고, 수령 기록은 남고 로봇만 비워진다
    assert client.delete(f"{ROBOTS}/{robot_with_key['id']}", headers=auth_headers).status_code == 204
    db.expire_all()  # 테스트는 요청끼리 세션을 공유한다 — DB의 ON DELETE SET NULL 결과를 다시 읽게
    after = client.get(f"{DELIVERIES}/{arrived_delivery['id']}", headers=auth_headers).json()
    assert after["status"] == "received" and after["received_by_robot_id"] is None and after["assigned_robot_id"] is None


@requires_db
def test_receipt_rejects_wrong_markers(client, auth_headers, db, seed, robot_with_key, arrived_delivery):
    url = _receipt_url(arrived_delivery["id"])
    headers = robot_with_key["headers"]
    marker = arrived_delivery["receipt_marker_id"]
    # 예약한 간호사의 고정 마커(0~49)로도 받을 수 없다 (2026-10-20 결정)
    client.patch(f"/api/v1/nurses/{seed['nurse'].id}", headers=auth_headers, json={"aruco_marker_id": 7})
    for wrong in (7, 0, 49, 50 if marker != 50 else 51):
        response = client.post(url, json={"aruco_marker_id": wrong}, headers=headers)
        assert response.status_code == 403 and response.json()["code"] == "receipt_marker_not_for_delivery", wrong
    for out_of_range in (-1, 250):
        assert client.post(url, json={"aruco_marker_id": out_of_range}, headers=headers).status_code == 422
    assert client.post(_receipt_url(999999), json={"aruco_marker_id": marker}, headers=headers).status_code == 404
    # 거부된 시도는 아무것도 바꾸지 않는다
    assert client.get(f"{DELIVERIES}/{arrived_delivery['id']}", headers=auth_headers).json()["status"] == "arrived"


@requires_db
def test_receipt_only_by_assigned_robot(client, auth_headers, make_robot, home_location, arrived_delivery):
    other = make_robot("배송로봇 2호", home_location_id=home_location.id)
    response = client.post(_receipt_url(arrived_delivery["id"]), json={"aruco_marker_id": arrived_delivery["receipt_marker_id"]},
                           headers=other["headers"])
    assert response.status_code == 403 and response.json()["code"] == "delivery_not_assigned_to_robot"


@requires_db
def test_receipt_rejected_before_arrival(client, auth_headers, seed, robot_with_key, reserve_overdue):
    # reserved(로봇 배정 전)·dispatched(가는 중)·cancelled에서는 받을 수 없다
    reserved = reserve_overdue(quantity=1)
    response = client.post(_receipt_url(reserved["id"]), json={"aruco_marker_id": 60}, headers=robot_with_key["headers"])
    assert response.status_code == 409 and response.json()["code"] == "delivery_not_arrived"
    client.post("/api/v1/robot/deliveries/claim", headers=robot_with_key["headers"])
    response = client.post(_receipt_url(reserved["id"]), json={"aruco_marker_id": 60}, headers=robot_with_key["headers"])
    assert response.status_code == 409 and response.json()["code"] == "delivery_not_arrived"

    cancelled = client.post(DELIVERIES, headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": "2099-01-01T00:00:00+00:00",
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]}).json()
    assert client.post(f"{DELIVERIES}/{cancelled['id']}/cancel", headers=auth_headers).status_code == 200
    response = client.post(_receipt_url(cancelled["id"]), json={"aruco_marker_id": 60}, headers=robot_with_key["headers"])
    assert response.status_code == 409 and response.json()["code"] == "delivery_not_arrived"


@requires_db
def test_receipt_notifies_reserving_nurse_only(client, seed, robot_with_key, arrived_delivery, published):
    """수령 확인되면 예약한 간호사에게만 가는 delivery_received 알림 (2026-10-19)."""
    published.clear()  # 예약·도착 때의 알림은 비운다
    response = client.post(_receipt_url(arrived_delivery["id"]), json={"aruco_marker_id": arrived_delivery["receipt_marker_id"]},
                           headers=robot_with_key["headers"])
    assert response.status_code == 200, response.text

    received_events = [message for message in published if message["event"] == "delivery_received"]
    assert len(received_events) == 1
    message = received_events[0]
    assert message["recipient_nurse_id"] == seed["nurse"].id
    assert message["delivery_id"] == arrived_delivery["id"]
    assert message["destination_location_name"] == seed["room_301"].name
    assert message["robot_name"] == "배송로봇 1호"
    assert message["received_at"] is not None
    assert message["items"] == [{"name": seed["medication"].name, "quantity": 3}] and message["item_count"] == 1


@requires_db
def test_rejected_receipt_sends_no_notification(client, robot_with_key, arrived_delivery, published):
    published.clear()
    response = client.post(_receipt_url(arrived_delivery["id"]), json={"aruco_marker_id": 30}, headers=robot_with_key["headers"])
    assert response.status_code == 403
    assert [message for message in published if message["event"] == "delivery_received"] == []
