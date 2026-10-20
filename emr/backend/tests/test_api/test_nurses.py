"""간호사 CRUD. PostgreSQL 필요."""
from __future__ import annotations

from tests.conftest import requires_db


@requires_db
def test_nurse_list_and_get(logged_in_client, seed):
    response = logged_in_client.get("/api/v1/nurses")
    assert [nurse["employee_no"] for nurse in response.json()] == ["N001"]
    assert logged_in_client.get(f"/api/v1/nurses/{seed['nurse'].id}").json()["name"] == "김간호"
    assert logged_in_client.get("/api/v1/nurses/999999").status_code == 404


@requires_db
def test_nurse_crud(logged_in_client):
    response = logged_in_client.post("/api/v1/nurses", json={"employee_no": "N100", "name": "박간호", "password": "pass-1234"})
    assert response.status_code == 201, response.text
    assert response.json()["is_active"] is True and "password" not in response.text
    nurse_id = response.json()["id"]

    response = logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"name": "박수간호"})
    assert response.json()["name"] == "박수간호" and response.json()["employee_no"] == "N100"

    # 삭제 = 비활성화. 행은 남고 조회된다
    assert logged_in_client.delete(f"/api/v1/nurses/{nurse_id}").status_code == 204
    assert logged_in_client.get(f"/api/v1/nurses/{nurse_id}").json()["is_active"] is False
    # 복귀
    assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"is_active": True}).json()["is_active"] is True


@requires_db
def test_nurse_duplicate_employee_no_conflict(logged_in_client, seed):
    response = logged_in_client.post("/api/v1/nurses", json={"employee_no": "N001", "name": "dup", "password": "pass-1234"})
    assert response.status_code == 409 and response.json()["code"] == "employee_no_duplicate"


@requires_db
def test_nurse_update_ignores_null_and_missing(logged_in_client, seed):
    nurse_id = seed["nurse"].id
    response = logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"name": None})
    assert response.status_code == 200 and response.json()["name"] == "김간호"
    assert logged_in_client.patch("/api/v1/nurses/999999", json={"name": "x"}).status_code == 404
    assert logged_in_client.delete("/api/v1/nurses/999999").status_code == 404


@requires_db
def test_nurses_require_login(client, seed):
    assert client.get("/api/v1/nurses").status_code == 401
    assert client.post("/api/v1/nurses", json={"employee_no": "N9", "name": "x", "password": "pass-1234"}).status_code == 401


@requires_db
def test_nurse_cannot_deactivate_self(logged_in_client, seed):
    own_id = seed["nurse"].id
    assert logged_in_client.delete(f"/api/v1/nurses/{own_id}").json()["code"] == "self_deactivation"
    assert logged_in_client.patch(f"/api/v1/nurses/{own_id}", json={"is_active": False}).status_code == 409
    assert logged_in_client.patch(f"/api/v1/nurses/{own_id}", json={"name": "김수간호"}).status_code == 200  # 이름은 바꿀 수 있다


@requires_db
def test_nurse_role_register_promote_and_self_protection(logged_in_client, seed):
    response = logged_in_client.post("/api/v1/nurses", json={"employee_no": "N101", "name": "기본역할", "password": "pass-1234"})
    assert response.json()["role"] == "nurse"  # 생략하면 일반
    nurse_id = response.json()["id"]
    assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"role": "admin"}).json()["role"] == "admin"
    assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"role": "nurse"}).json()["role"] == "nurse"
    assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"role": "boss"}).status_code == 422
    # 자기 자신의 관리자 권한은 내릴 수 없다 (관리자가 아무도 없게 되는 것 방지)
    response = logged_in_client.patch(f"/api/v1/nurses/{seed['nurse'].id}", json={"role": "nurse"})
    assert response.status_code == 409 and response.json()["code"] == "self_role_change"
    assert logged_in_client.patch(f"/api/v1/nurses/{seed['nurse'].id}", json={"role": "admin"}).status_code == 200


@requires_db
def test_nurse_aruco_marker_assign_duplicate_and_clear(logged_in_client, seed):
    response = logged_in_client.post("/api/v1/nurses", json={
        "employee_no": "N200", "name": "마커간호", "password": "pass-1234", "aruco_marker_id": 7})
    assert response.status_code == 201 and response.json()["aruco_marker_id"] == 7
    nurse_id = response.json()["id"]
    assert logged_in_client.get(f"/api/v1/nurses/{seed['nurse'].id}").json()["aruco_marker_id"] is None  # 미배정

    # 다른 간호사가 쓰는 번호는 등록·수정 모두 409
    response = logged_in_client.post("/api/v1/nurses", json={
        "employee_no": "N201", "name": "겹침", "password": "pass-1234", "aruco_marker_id": 7})
    assert response.status_code == 409 and response.json()["code"] == "aruco_marker_duplicate"
    response = logged_in_client.patch(f"/api/v1/nurses/{seed['nurse'].id}", json={"aruco_marker_id": 7})
    assert response.status_code == 409 and response.json()["code"] == "aruco_marker_duplicate"
    # 자기 번호를 다시 보내는 것은 괜찮다
    assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"aruco_marker_id": 7}).status_code == 200

    # DICT_4X4_50 범위 밖은 422
    for out_of_range in (-1, 50):
        assert logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"aruco_marker_id": out_of_range}).status_code == 422

    # 다른 필드의 null은 무시하고, 마커 번호의 null은 배정 해제
    response = logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"name": None})
    assert response.json()["name"] == "마커간호" and response.json()["aruco_marker_id"] == 7
    response = logged_in_client.patch(f"/api/v1/nurses/{nurse_id}", json={"aruco_marker_id": None})
    assert response.status_code == 200 and response.json()["aruco_marker_id"] is None
    # 해제된 번호는 다른 간호사에게 줄 수 있다
    assert logged_in_client.patch(f"/api/v1/nurses/{seed['nurse'].id}", json={"aruco_marker_id": 7}).json()["aruco_marker_id"] == 7


@requires_db
def test_nurse_aruco_marker_admin_only(client, seed, general_nurse_headers):
    response = client.patch(f"/api/v1/nurses/{seed['nurse'].id}", headers=general_nurse_headers, json={"aruco_marker_id": 3})
    assert response.status_code == 403 and response.json()["code"] == "admin_required"
