"""배송 일정 예약. PostgreSQL 필요."""
from __future__ import annotations

from unittest.mock import ANY

from datetime import UTC, datetime, timedelta

from tests.conftest import requires_db

URL = "/api/v1/deliveries"


def _future(hours: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _body(seed: dict, **overrides) -> dict:
    return {"destination_location_id": seed["room_301"].id, "scheduled_at": _future(),
            "items": [{"supply_id": seed["medication"].id, "quantity": 3}], **overrides}


@requires_db
def test_delivery_requires_login(client, seed):
    assert client.post(URL, json=_body(seed)).status_code == 401
    assert client.get(URL).status_code == 401


@requires_db
def test_delivery_create_list_get(client, seed, auth_headers):
    response = client.post(URL, headers=auth_headers, json=_body(seed))
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "reserved" and created["nurse_id"] == seed["nurse"].id
    assert created["items"] == [{"supply_id": seed["medication"].id, "quantity": 3}]
    assert seed["medication"].stock_qty == 7  # 예약하면 재고에서 뺀다 (10 - 3)

    later = client.post(URL, headers=auth_headers, json=_body(seed, scheduled_at=_future(1))).json()
    assert [r["id"] for r in client.get(URL, headers=auth_headers).json()] == [later["id"], created["id"]]  # 빠른 순
    assert client.get(f"{URL}/{created['id']}", headers=auth_headers).json()["destination_location"] == {
        "id": seed["room_301"].id, "name": "301호", "map_x_m": 12.5, "map_y_m": 3.2, "map_yaw_rad": 1.57,
        "map_id": seed["ward_map"].id, "robot_dest": None, "robot_only": False, "map": {"id": seed["ward_map"].id, "name": "3병동", "file_name": "ward3.yaml", "resolution_m_per_pixel": 0.05, "origin_x_m": -10.0, "origin_y_m": -10.0, "origin_yaw_rad": 0.0, "has_image": False, "image_width_px": None, "image_height_px": None, "image_file_name": None, "updated_at": ANY}}
    assert client.get(f"{URL}/999999", headers=auth_headers).status_code == 404


@requires_db
def test_delivery_rejects_bad_input(client, seed, auth_headers):
    past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()   # 5분 안의 과거("지금")는 받는다 (2026-10-22)
    assert client.post(URL, headers=auth_headers, json=_body(seed, scheduled_at=past)).status_code == 400
    assert client.post(URL, headers=auth_headers, json=_body(seed, scheduled_at="2030-01-01T09:00:00")).status_code == 422  # 시간대 없음
    empty = client.post(URL, headers=auth_headers, json=_body(seed, items=[]))   # 품목 없음은 로봇 전용 장소 이동만 (2026-10-22)
    assert empty.status_code == 400 and empty.json()["code"] == "delivery_items_required"
    assert client.post(URL, headers=auth_headers, json=_body(seed, items=[{"supply_id": 999999, "quantity": 1}])).status_code == 400
    assert client.post(URL, headers=auth_headers, json=_body(seed, destination_location_id=999999)).status_code == 400
    duplicate = [{"supply_id": seed["medication"].id, "quantity": 1}, {"supply_id": seed["medication"].id, "quantity": 2}]
    assert client.post(URL, headers=auth_headers, json=_body(seed, items=duplicate)).status_code == 400
    assert client.post(URL, headers=auth_headers, json=_body(seed, items=[{"supply_id": seed["medication"].id, "quantity": 0}])).status_code == 422


@requires_db
def test_delivery_update_and_cancel(client, seed, auth_headers):
    delivery_id = client.post(URL, headers=auth_headers, json=_body(seed)).json()["id"]
    new_items = [{"supply_id": seed["medication"].id, "quantity": 5}, {"supply_id": seed["blanket"].id, "quantity": 1}]
    response = client.patch(f"{URL}/{delivery_id}", headers=auth_headers, json={"destination_location_id": seed["room_302"].id, "items": new_items})
    assert response.status_code == 200, response.text
    assert response.json()["destination_location"]["name"] == "302호" and response.json()["items"] == new_items

    response = client.post(f"{URL}/{delivery_id}/cancel", headers=auth_headers)
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    # 취소된 예약은 변경·재취소 불가
    assert client.patch(f"{URL}/{delivery_id}", headers=auth_headers, json={"destination_location_id": seed["room_301"].id}).status_code == 409
    assert client.post(f"{URL}/{delivery_id}/cancel", headers=auth_headers).json()["code"] == "delivery_not_reserved"
    assert [r["id"] for r in client.get(f"{URL}?status=reserved", headers=auth_headers).json()] == []
    assert [r["id"] for r in client.get(f"{URL}?status=cancelled", headers=auth_headers).json()] == [delivery_id]


@requires_db
def test_delivery_is_private_to_owner(client, seed, auth_headers):
    delivery_id = client.post(URL, headers=auth_headers, json=_body(seed)).json()["id"]
    client.post("/api/v1/nurses", headers=auth_headers, json={"employee_no": "N002", "name": "이간호", "password": "pass-1234"})
    token = client.post("/api/v1/auth/login", json={"employee_no": "N002", "password": "pass-1234"}).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {token}"}
    assert client.get(URL, headers=other_headers).json() == []
    assert client.get(f"{URL}/{delivery_id}", headers=other_headers).status_code == 403
    assert client.patch(f"{URL}/{delivery_id}", headers=other_headers, json={"destination_location_id": seed["room_302"].id}).status_code == 403
    assert client.post(f"{URL}/{delivery_id}/cancel", headers=other_headers).status_code == 403


def _stock(client, supply_id: int, headers: dict) -> int:
    return client.get(f"/api/v1/supplies/{supply_id}", headers=headers).json()["stock_qty"]


@requires_db
def test_reservation_deducts_stock_and_cancel_restores(client, seed, auth_headers):
    medication_id, blanket_id = seed["medication"].id, seed["blanket"].id  # 재고 10, 5
    delivery_id = client.post(URL, headers=auth_headers, json=_body(seed)).json()["id"]  # 약품 3
    assert _stock(client, medication_id, auth_headers) == 7
    # 변경: 약품 3 → 1, 이불 0 → 4 — 차이만큼 조정
    new_items = [{"supply_id": medication_id, "quantity": 1}, {"supply_id": blanket_id, "quantity": 4}]
    assert client.patch(f"{URL}/{delivery_id}", headers=auth_headers, json={"items": new_items}).status_code == 200
    assert (_stock(client, medication_id, auth_headers), _stock(client, blanket_id, auth_headers)) == (9, 1)
    # 품목을 안 보내는 변경은 재고를 건드리지 않는다
    client.patch(f"{URL}/{delivery_id}", headers=auth_headers, json={"destination_location_id": seed["room_302"].id})
    assert (_stock(client, medication_id, auth_headers), _stock(client, blanket_id, auth_headers)) == (9, 1)
    # 취소하면 전부 되돌린다
    assert client.post(f"{URL}/{delivery_id}/cancel", headers=auth_headers).status_code == 200
    assert (_stock(client, medication_id, auth_headers), _stock(client, blanket_id, auth_headers)) == (10, 5)


@requires_db
def test_reservation_rejected_when_stock_insufficient(client, seed, auth_headers):
    medication_id, blanket_id = seed["medication"].id, seed["blanket"].id  # 재고 10, 5
    # 한 품목이라도 모자라면 거절하고 아무것도 바꾸지 않는다
    items = [{"supply_id": medication_id, "quantity": 2}, {"supply_id": blanket_id, "quantity": 6}]
    response = client.post(URL, headers=auth_headers, json=_body(seed, items=items))
    assert response.status_code == 409 and response.json()["code"] == "stock_insufficient"
    assert (_stock(client, medication_id, auth_headers), _stock(client, blanket_id, auth_headers)) == (10, 5)
    assert client.get(URL, headers=auth_headers).json() == []
    # 재고를 정확히 다 쓰는 예약은 된다
    delivery_id = client.post(URL, headers=auth_headers, json=_body(seed, items=[{"supply_id": blanket_id, "quantity": 5}])).json()["id"]
    assert _stock(client, blanket_id, auth_headers) == 0
    # 변경으로 늘릴 때도 모자라면 거절, 예약은 그대로
    response = client.patch(f"{URL}/{delivery_id}", headers=auth_headers, json={"items": [{"supply_id": blanket_id, "quantity": 6}]})
    assert response.status_code == 409 and response.json()["code"] == "stock_insufficient"
    assert client.get(f"{URL}/{delivery_id}", headers=auth_headers).json()["items"] == [{"supply_id": blanket_id, "quantity": 5}]
