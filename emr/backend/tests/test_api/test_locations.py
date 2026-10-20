"""장소(배송 위치·맵 좌표). 변경은 관리자(logged_in_client = N001). PostgreSQL 필요."""
from __future__ import annotations

from unittest.mock import ANY

from datetime import UTC, datetime, timedelta

from tests.conftest import requires_db

URL = "/api/v1/locations"


@requires_db
def test_location_crud(logged_in_client, seed):
    map_id = seed["ward_map"].id
    response = logged_in_client.post(URL, json={"name": "401호", "map_x_m": 1.0, "map_y_m": 2.0, "map_yaw_rad": 0.5, "map_id": map_id})
    assert response.status_code == 201, response.text
    location_id = response.json()["id"]
    assert response.json() == {"id": location_id, "name": "401호", "map_x_m": 1.0, "map_y_m": 2.0, "map_yaw_rad": 0.5,
                               "map_id": map_id, "map": {"id": seed["ward_map"].id, "name": "3병동", "file_name": "ward3.yaml", "resolution_m_per_pixel": 0.05, "origin_x_m": -10.0, "origin_y_m": -10.0, "origin_yaw_rad": 0.0, "has_image": False, "image_width_px": None, "image_height_px": None, "image_file_name": None, "updated_at": ANY}}

    response = logged_in_client.patch(f"{URL}/{location_id}", json={"name": "401호(격리)"})
    assert response.json()["name"] == "401호(격리)" and response.json()["map_x_m"] == 1.0  # 좌표 유지
    assert "401호(격리)" in [location["name"] for location in logged_in_client.get(URL).json()]
    assert logged_in_client.delete(f"{URL}/{location_id}").status_code == 204
    assert logged_in_client.get(f"{URL}/{location_id}").status_code == 404


@requires_db
def test_location_without_map_pose_then_fill(logged_in_client, seed):
    response = logged_in_client.post(URL, json={"name": "휴게실"})
    assert response.status_code == 201 and response.json()["map_x_m"] is None
    location_id = response.json()["id"]
    # 좌표는 세 값을 함께
    assert logged_in_client.patch(f"{URL}/{location_id}", json={"map_x_m": 1.0}).status_code == 422
    assert logged_in_client.post(URL, json={"name": "x", "map_x_m": 1.0, "map_y_m": 2.0}).status_code == 422
    # 좌표만 있고 맵이 없으면 400, 맵과 함께 보내면 200
    assert logged_in_client.patch(f"{URL}/{location_id}", json={"map_x_m": 1.0, "map_y_m": 2.0, "map_yaw_rad": 0.0}).status_code == 400
    response = logged_in_client.patch(f"{URL}/{location_id}", json={"map_x_m": 1.0, "map_y_m": 2.0, "map_yaw_rad": 0.0, "map_id": seed["ward_map"].id})
    assert response.status_code == 200 and response.json()["map"]["file_name"] == "ward3.yaml"
    assert logged_in_client.patch(f"{URL}/{location_id}", json={"map_id": 999999}).status_code == 400


@requires_db
def test_location_name_conflict(logged_in_client, seed):
    assert logged_in_client.post(URL, json={"name": "301호"}).status_code == 409
    assert logged_in_client.patch(f"{URL}/{seed['room_302'].id}", json={"name": "301호"}).status_code == 409
    assert logged_in_client.patch(f"{URL}/{seed['room_302'].id}", json={"name": "302호"}).status_code == 200  # 자기 이름 그대로


@requires_db
def test_location_used_by_delivery_cannot_be_deleted(logged_in_client, seed, auth_headers):
    scheduled_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = logged_in_client.post("/api/v1/deliveries", headers=auth_headers, json={
        "destination_location_id": seed["room_301"].id, "scheduled_at": scheduled_at,
        "items": [{"supply_id": seed["medication"].id, "quantity": 1}]})
    assert response.status_code == 201, response.text
    assert logged_in_client.delete(f"{URL}/{seed['room_301'].id}").json()["code"] == "location_in_use"
    assert logged_in_client.delete(f"{URL}/{seed['room_302'].id}").status_code == 204
