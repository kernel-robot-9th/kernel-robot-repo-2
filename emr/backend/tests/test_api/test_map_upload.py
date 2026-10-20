"""맵 파일 업로드·이미지 조회·파일 교체 (2026-10-19). PostgreSQL 필요."""
from __future__ import annotations

from tests.conftest import requires_db
from tests.test_services.test_map_files import PINKY_MY_MAP_YAML, make_pgm

MAPS = "/api/v1/maps"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _files(yaml_text: str = PINKY_MY_MAP_YAML, image: bytes | None = None, yaml_name: str = "my_map.yaml") -> dict:
    return {"map_yaml": (yaml_name, yaml_text.encode(), "application/x-yaml"),
            "map_image": ("my_map.pgm", image if image is not None else make_pgm(), "image/x-portable-graymap")}


@requires_db
def test_upload_pinky_map_reads_yaml_and_serves_png(client, auth_headers):
    response = client.post(f"{MAPS}/upload", headers=auth_headers, data={"name": "핑키 실습실"}, files=_files())
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["file_name"] == "my_map.yaml" and created["image_file_name"] == "my_map.pgm"
    assert (created["resolution_m_per_pixel"], created["origin_x_m"], created["origin_y_m"], created["origin_yaw_rad"]) == (0.05, -2.05, -1.62, 0.0)
    assert created["has_image"] is True and (created["image_width_px"], created["image_height_px"]) == (82, 63)

    # 이미지는 누구나 (맵 조회와 같은 정책), PNG
    image = client.get(f"{MAPS}/{created['id']}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png" and image.content.startswith(PNG_SIGNATURE)
    # 목록에는 이미지 바이트가 실리지 않는다
    listed = next(item for item in client.get(MAPS).json() if item["id"] == created["id"])
    assert "image_png" not in listed and listed["has_image"] is True


@requires_db
def test_upload_requires_admin(client, general_nurse_headers):
    assert client.post(f"{MAPS}/upload", data={"name": "x"}, files=_files()).status_code == 401
    response = client.post(f"{MAPS}/upload", headers=general_nurse_headers, data={"name": "x"}, files=_files())
    assert response.status_code == 403 and response.json()["code"] == "admin_required"


@requires_db
def test_upload_rejects_bad_files_and_duplicates(client, auth_headers, seed):
    cases = [
        (_files(yaml_text="resolution: 0.05\n"), "map_yaml_invalid"),
        (_files(image=b"not an image"), "map_image_invalid"),
        ({**_files(), "map_yaml": ("my_map.yaml", b"\xff\xfe", "application/x-yaml")}, "map_yaml_invalid"),
    ]
    for files, code in cases:
        response = client.post(f"{MAPS}/upload", headers=auth_headers, data={"name": "새 맵"}, files=files)
        assert response.status_code == 400 and response.json()["code"] == code, (code, response.text)
    response = client.post(f"{MAPS}/upload", headers=auth_headers, data={"name": "   "}, files=_files())
    assert response.status_code == 400 and response.json()["code"] == "map_name_invalid"
    # seed의 '3병동'(ward3.yaml)과 이름·파일 이름 중복
    response = client.post(f"{MAPS}/upload", headers=auth_headers, data={"name": "3병동"}, files=_files())
    assert response.status_code == 409 and response.json()["code"] == "map_name_duplicate"
    response = client.post(f"{MAPS}/upload", headers=auth_headers, data={"name": "다른 이름"}, files=_files(yaml_name="ward3.yaml"))
    assert response.status_code == 409 and response.json()["code"] == "map_file_name_duplicate"


@requires_db
def test_map_without_image_and_replace_files_keeps_locations(client, auth_headers, seed):
    ward_map_id = seed["ward_map"].id   # 숫자만 등록된 맵 (이미지 없음)
    assert client.get(f"{MAPS}/{ward_map_id}").json()["has_image"] is False
    response = client.get(f"{MAPS}/{ward_map_id}/image")
    assert response.status_code == 404 and response.json()["code"] == "map_image_not_found"
    assert client.get(f"{MAPS}/999999/image").json()["code"] == "map_not_found"

    before = client.get(f"{MAPS}/{ward_map_id}").json()
    response = client.put(f"{MAPS}/{ward_map_id}/files", headers=auth_headers, files=_files(yaml_name="ward3_v2.yaml"))
    assert response.status_code == 200, response.text
    replaced = response.json()
    assert replaced["name"] == "3병동" and replaced["file_name"] == "ward3_v2.yaml" and replaced["has_image"] is True
    assert replaced["origin_x_m"] == -2.05 and replaced["updated_at"] >= before["updated_at"]
    # 장소 좌표는 그대로
    room = client.get(f"/api/v1/locations/{seed['room_301'].id}").json()
    assert (room["map_id"], room["map_x_m"], room["map_y_m"]) == (ward_map_id, 12.5, 3.2)
    assert client.get(f"{MAPS}/{ward_map_id}/image").status_code == 200
    assert client.put(f"{MAPS}/999999/files", headers=auth_headers, files=_files()).status_code == 404
