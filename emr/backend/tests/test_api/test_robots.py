"""로봇 등록·이름·상태. 변경은 관리자(logged_in_client = N001). PostgreSQL 필요."""
from __future__ import annotations

from tests.conftest import requires_db

URL = "/api/v1/robots"


@requires_db
def test_robot_register_rename_and_status(logged_in_client):
    response = logged_in_client.post(URL, json={"name": "배송로봇 1호", "robot_type": "amr"})
    assert response.status_code == 201, response.text
    robot_id = response.json()["id"]
    assert response.json()["status"] == "idle" and response.json()["robot_type"] == "amr"

    response = logged_in_client.patch(f"{URL}/{robot_id}", json={"status": "charging"})
    assert response.json()["status"] == "charging" and response.json()["name"] == "배송로봇 1호"
    response = logged_in_client.patch(f"{URL}/{robot_id}", json={"name": "배송로봇 A"})
    assert response.json()["name"] == "배송로봇 A" and response.json()["status"] == "charging"
    assert logged_in_client.get(f"{URL}/{robot_id}").json()["name"] == "배송로봇 A"


@requires_db
def test_robot_list_filter_by_status(logged_in_client):
    idle_id = logged_in_client.post(URL, json={"name": "r1", "robot_type": "amr"}).json()["id"]
    charging_id = logged_in_client.post(URL, json={"name": "r2", "robot_type": "manipulator"}).json()["id"]
    logged_in_client.patch(f"{URL}/{charging_id}", json={"status": "charging"})
    assert [robot["id"] for robot in logged_in_client.get(URL).json()] == [idle_id, charging_id]
    assert [robot["id"] for robot in logged_in_client.get(f"{URL}?status=charging").json()] == [charging_id]


@requires_db
def test_robot_rejects_bad_input(logged_in_client):
    robot_id = logged_in_client.post(URL, json={"name": "r1", "robot_type": "amr"}).json()["id"]
    logged_in_client.post(URL, json={"name": "r2", "robot_type": "manipulator"})
    assert logged_in_client.post(URL, json={"name": "r1", "robot_type": "amr"}).status_code == 409
    assert logged_in_client.patch(f"{URL}/{robot_id}", json={"name": "r2", "robot_type": "manipulator"}).status_code == 409
    assert logged_in_client.patch(f"{URL}/{robot_id}", json={"name": "r1", "robot_type": "amr"}).status_code == 200  # 자기 이름 그대로
    assert logged_in_client.patch(f"{URL}/{robot_id}", json={"status": "flying"}).status_code == 422
    assert logged_in_client.post(URL, json={"name": "r3", "robot_type": "amr", "status": "charging"}).json()["status"] == "idle"  # 등록 시 상태 지정 불가
    assert logged_in_client.get(f"{URL}/999999").status_code == 404


@requires_db
def test_robot_type_required_filterable_and_fixed(logged_in_client):
    assert logged_in_client.post(URL, json={"name": "no-type"}).status_code == 422
    assert logged_in_client.post(URL, json={"name": "x", "robot_type": "drone"}).status_code == 422
    amr_id = logged_in_client.post(URL, json={"name": "AMR-1", "robot_type": "amr"}).json()["id"]
    arm_id = logged_in_client.post(URL, json={"name": "ARM-1", "robot_type": "manipulator"}).json()["id"]
    assert [robot["id"] for robot in logged_in_client.get(f"{URL}?robot_type=manipulator").json()] == [arm_id]
    assert [robot["id"] for robot in logged_in_client.get(f"{URL}?robot_type=amr").json()] == [amr_id]
    # 종류는 PATCH로 바꿀 수 없다 (필드가 무시된다)
    assert logged_in_client.patch(f"{URL}/{amr_id}", json={"robot_type": "manipulator"}).json()["robot_type"] == "amr"


@requires_db
def test_robot_delete(logged_in_client):
    robot_id = logged_in_client.post(URL, json={"name": "삭제용", "robot_type": "amr"}).json()["id"]
    assert logged_in_client.delete(f"{URL}/{robot_id}").status_code == 204
    assert logged_in_client.get(f"{URL}/{robot_id}").status_code == 404
    assert logged_in_client.delete(f"{URL}/{robot_id}").status_code == 404
    # 지운 이름은 다시 쓸 수 있다
    assert logged_in_client.post(URL, json={"name": "삭제용", "robot_type": "manipulator"}).status_code == 201
