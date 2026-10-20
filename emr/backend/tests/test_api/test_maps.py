"""맵(파일 이름·맵 정보). 변경은 관리자(logged_in_client = N001). PostgreSQL 필요."""
from __future__ import annotations

from unittest.mock import ANY

from tests.conftest import requires_db

URL = "/api/v1/maps"
BODY = {"name": "4병동", "file_name": "ward4.yaml", "resolution_m_per_pixel": 0.05,
        "origin_x_m": -5.0, "origin_y_m": -6.0, "origin_yaw_rad": 0.0}


@requires_db
def test_map_crud(logged_in_client):
    response = logged_in_client.post(URL, json=BODY)
    assert response.status_code == 201, response.text
    map_id = response.json()["id"]
    assert response.json() == {"id": map_id, **BODY, "has_image": False, "image_width_px": None, "image_height_px": None, "image_file_name": None, "updated_at": ANY}  # 숫자만 등록한 맵은 이미지 없음

    response = logged_in_client.patch(f"{URL}/{map_id}", json={"file_name": "ward4_v2.yaml", "resolution_m_per_pixel": 0.025})
    assert response.json()["file_name"] == "ward4_v2.yaml" and response.json()["name"] == "4병동"
    assert [map_["name"] for map_ in logged_in_client.get(URL).json()] == ["3병동", "4병동"]  # 3병동은 seed
    assert logged_in_client.delete(f"{URL}/{map_id}").status_code == 204
    assert logged_in_client.get(f"{URL}/{map_id}").status_code == 404


@requires_db
def test_map_rejects_bad_input(logged_in_client, seed):
    assert logged_in_client.post(URL, json={**BODY, "name": "3병동"}).json()["code"] == "map_name_duplicate"
    assert logged_in_client.post(URL, json={**BODY, "file_name": "ward3.yaml"}).json()["code"] == "map_file_name_duplicate"
    assert logged_in_client.post(URL, json={**BODY, "resolution_m_per_pixel": 0}).status_code == 422
    map_id = logged_in_client.post(URL, json=BODY).json()["id"]
    assert logged_in_client.patch(f"{URL}/{map_id}", json={"file_name": "ward3.yaml"}).status_code == 409
    assert logged_in_client.patch(f"{URL}/{map_id}", json={"file_name": "ward4.yaml"}).status_code == 200  # 자기 값 그대로


@requires_db
def test_map_used_by_location_cannot_be_deleted(logged_in_client, seed):
    assert logged_in_client.delete(f"{URL}/{seed['ward_map'].id}").json()["code"] == "map_in_use"
