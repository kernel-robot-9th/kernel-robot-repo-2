"""권한 (2026-10-15 결정). 맵·장소·로봇 조회는 로그인 없이, 변경은 관리자만. 간호사 관리는 관리자만. PostgreSQL 필요."""
from __future__ import annotations

from tests.conftest import requires_db

MAP_BODY = {"name": "5병동", "file_name": "ward5.yaml", "resolution_m_per_pixel": 0.05}


@requires_db
def test_map_location_robot_reads_need_no_login(client, seed):
    for url in ("/api/v1/maps", "/api/v1/locations", "/api/v1/robots", f"/api/v1/locations/{seed['room_301'].id}"):
        assert client.get(url).status_code == 200, url


@requires_db
def test_map_location_robot_writes_need_login(client, seed):
    response = client.post("/api/v1/robots", json={"name": "r1", "robot_type": "amr"})
    assert response.status_code == 401 and response.json()["code"] == "token_missing"
    assert client.post("/api/v1/maps", json=MAP_BODY).status_code == 401
    assert client.delete(f"/api/v1/locations/{seed['room_302'].id}").status_code == 401


@requires_db
def test_map_location_robot_writes_need_admin(client, seed, general_nurse_headers):
    headers = general_nurse_headers
    requests = [
        ("POST", "/api/v1/maps", MAP_BODY),
        ("PATCH", f"/api/v1/maps/{seed['ward_map'].id}", {"name": "x"}),
        ("POST", "/api/v1/locations", {"name": "401호"}),
        ("PATCH", f"/api/v1/locations/{seed['room_302'].id}", {"name": "x"}),
        ("DELETE", f"/api/v1/locations/{seed['room_302'].id}", None),
        ("POST", "/api/v1/robots", {"name": "r1", "robot_type": "amr"}),
    ]
    for method, url, body in requests:
        response = client.request(method, url, headers=headers, json=body)
        assert response.status_code == 403 and response.json()["code"] == "admin_required", (method, url, response.text)
    assert client.get(f"/api/v1/locations/{seed['room_302'].id}").json()["name"] == "302호"  # 아무것도 안 바뀜


@requires_db
def test_nurse_management_needs_admin(client, seed, general_nurse_headers):
    headers = general_nurse_headers
    admin_id = seed["nurse"].id
    assert client.get("/api/v1/nurses", headers=headers).status_code == 200  # 목록은 누구나
    requests = [
        ("POST", "/api/v1/nurses", {"employee_no": "N091", "name": "x", "password": "pass-1234"}),
        ("PATCH", f"/api/v1/nurses/{admin_id}", {"name": "x"}),
        ("DELETE", f"/api/v1/nurses/{admin_id}", None),
        ("POST", f"/api/v1/nurses/{admin_id}/password-reset", {"new_password": "temp-1234"}),
    ]
    for method, url, body in requests:
        response = client.request(method, url, headers=headers, json=body)
        assert response.status_code == 403 and response.json()["code"] == "admin_required", (method, url, response.text)


@requires_db
def test_general_nurse_can_manage_supplies_and_deliveries(client, seed, general_nurse_headers):
    headers = general_nurse_headers
    assert client.patch(f"/api/v1/supplies/{seed['medication'].id}", headers=headers, json={"stock_qty": 12}).status_code == 200
    response = client.post("/api/v1/deliveries", headers=headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": "2099-01-01T09:00:00+09:00",
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]})
    assert response.status_code == 201, response.text
