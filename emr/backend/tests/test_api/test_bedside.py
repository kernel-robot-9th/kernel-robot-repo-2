"""병상 단말 환자 요청 — 관리자 등록·키, 비품 요청(SR-02), "받았습니다"(SR-06), 로봇 연동, 알림, 기록, 삭제 보호 (2026-10-22). PostgreSQL 필요.
계약: docs/api_contract_delivery_2026-10-20.md 8장. 사용자 결정: 승인 없음, 병상당 진행 중 1건, 품목당 1–5, 실패만 관리자에게 알림.
"""
from __future__ import annotations

import pytest

from tests.conftest import requires_db

DEVICES = "/api/v1/bedside-devices"
BEDSIDE = "/api/v1/bedside"
CLAIM = "/api/v1/robot/deliveries/claim"
ME = "/api/v1/robot/me"


@pytest.fixture
def make_bedside(client, auth_headers):
    """병상 단말 만들기: make_bedside(name, location_id) → {"id", "api_key", "headers"}"""
    def _make(name: str, location_id: int) -> dict:
        created = client.post(DEVICES, headers=auth_headers, json={"name": name, "location_id": location_id})
        assert created.status_code == 201, created.text
        issued = client.post(f"{DEVICES}/{created.json()['id']}/api-key", headers=auth_headers)
        assert issued.status_code == 201, issued.text
        api_key = issued.json()["api_key"]
        return {"id": created.json()["id"], "api_key": api_key, "headers": {"X-Bedside-Api-Key": api_key}}
    return _make


@pytest.fixture
def bed_301(make_bedside, seed) -> dict:
    """301호(좌표 있음) 병상."""
    return make_bedside("301호-1", seed["room_301"].id)


def _request(client, bed: dict, supply_id: int, quantity: int = 1):
    return client.post(f"{BEDSIDE}/requests", headers=bed["headers"],
                       json={"items": [{"supply_id": supply_id, "quantity": quantity}]})


def _progress(client, robot: dict, delivery_id: int, stage: str, failure_reason: str | None = None):
    body = {"stage": stage} | ({"failure_reason": failure_reason} if failure_reason else {})
    return client.post(f"/api/v1/robot/deliveries/{delivery_id}/progress", headers=robot["headers"], json=body)


# ---- 관리자 ----------------------------------------------------------------------

@requires_db
def test_admin_registers_bedside_and_manages_key(client, auth_headers, general_nurse_headers, seed, make_bedside):
    bed = make_bedside("301호-1", seed["room_301"].id)
    assert bed["api_key"].startswith("emr_bk_")
    listed = client.get(DEVICES, headers=auth_headers).json()
    assert [(device["name"], device["has_api_key"]) for device in listed] == [("301호-1", True)]
    duplicate = client.post(DEVICES, headers=auth_headers, json={"name": "301호-1", "location_id": seed["room_301"].id})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "bedside_name_duplicate"
    no_room = client.post(DEVICES, headers=auth_headers, json={"name": "999호-1", "location_id": 999999})
    assert no_room.status_code == 400 and no_room.json()["code"] == "location_not_found"
    renamed = client.patch(f"{DEVICES}/{bed['id']}", headers=auth_headers, json={"name": "301호-A"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "301호-A"
    # 일반 간호사는 관리 못 함
    denied = client.get(DEVICES, headers=general_nurse_headers)
    assert denied.status_code == 403 and denied.json()["code"] == "admin_required"
    # 키 폐기 → 그 키로는 401
    assert client.get(f"{BEDSIDE}/me", headers=bed["headers"]).status_code == 200
    assert client.delete(f"{DEVICES}/{bed['id']}/api-key", headers=auth_headers).status_code == 204
    revoked = client.get(f"{BEDSIDE}/me", headers=bed["headers"])
    assert revoked.status_code == 401 and revoked.json()["code"] == "bedside_key_invalid"


@requires_db
def test_bedside_key_required(client, seed):
    missing = client.get(f"{BEDSIDE}/me")
    assert missing.status_code == 401 and missing.json()["code"] == "bedside_key_missing"
    wrong = client.get(f"{BEDSIDE}/me", headers={"X-Bedside-Api-Key": "emr_bk_nope"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "bedside_key_invalid"


# ---- 환자 요청 -------------------------------------------------------------------

@requires_db
def test_supplies_are_patient_items_only(client, bed_301, seed):
    supplies = client.get(f"{BEDSIDE}/supplies", headers=bed_301["headers"]).json()
    assert supplies == [{"id": seed["blanket"].id, "name": "이불", "in_stock": True}]   # 약품(간호사용)은 없다


@requires_db
def test_request_creates_delivery_right_away(client, db, bed_301, seed):
    created = _request(client, bed_301, seed["blanket"].id, 2)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "reserved" and body["items"] == [{"name": "이불", "quantity": 2}]
    assert "receipt_marker_id" not in body and "nurse_id" not in body
    db.refresh(seed["blanket"])
    assert seed["blanket"].stock_qty == 3                                  # 재고 5 → 3

    me = client.get(f"{BEDSIDE}/me", headers=bed_301["headers"]).json()
    assert me["name"] == "301호-1" and me["room"] == {"id": seed["room_301"].id, "name": "301호", "has_position": True}
    assert me["active_delivery"]["id"] == body["id"]
    # 진행 중 1건 — 두 번째 요청은 409
    again = _request(client, bed_301, seed["blanket"].id, 1)
    assert again.status_code == 409 and again.json()["code"] == "bedside_request_in_progress"


@requires_db
@pytest.mark.parametrize("quantity", [0, 6])
def test_quantity_must_be_1_to_5(client, bed_301, seed, quantity):
    assert _request(client, bed_301, seed["blanket"].id, quantity).status_code == 422


@requires_db
def test_request_rejections(client, db, make_bedside, bed_301, seed):
    nurse_item = _request(client, bed_301, seed["medication"].id)
    assert nurse_item.status_code == 400 and nurse_item.json()["code"] == "supply_not_patient_requestable"
    missing = _request(client, bed_301, 999999)
    assert missing.status_code == 400 and missing.json()["code"] == "supply_not_found"
    seed["blanket"].stock_qty = 1; db.flush()
    short = _request(client, bed_301, seed["blanket"].id, 2)
    assert short.status_code == 409 and short.json()["code"] == "stock_insufficient"
    # 좌표 없는 병실(302호)은 로봇이 갈 수 없다
    bed_302 = make_bedside("302호-1", seed["room_302"].id)
    no_position = _request(client, bed_302, seed["blanket"].id)
    assert no_position.status_code == 409 and no_position.json()["code"] == "bedside_room_has_no_position"


# ---- 로봇 연동·버튼 수령 ---------------------------------------------------------------

@requires_db
def test_robot_delivers_and_patient_confirms_with_button(client, auth_headers, robot_with_key, bed_301, seed, published):
    delivery_id = _request(client, bed_301, seed["blanket"].id).json()["id"]
    claimed = client.post(CLAIM, headers=robot_with_key["headers"])
    assert claimed.status_code == 200 and claimed.json()["id"] == delivery_id
    assert claimed.json()["receipt_method"] == "button"
    assert claimed.json()["destination"]["name"] == "301호"

    # 도착 전 "받았습니다"는 409
    early = client.post(f"{BEDSIDE}/deliveries/{delivery_id}/receipt", headers=bed_301["headers"])
    assert early.status_code == 409 and early.json()["code"] == "delivery_not_arrived"
    assert _progress(client, robot_with_key, delivery_id, "arrived").status_code == 200
    # 병상 화면에도 마커는 없다
    arrived = client.get(f"{BEDSIDE}/deliveries", headers=bed_301["headers"]).json()[0]
    assert arrived["status"] == "arrived" and "receipt_marker_id" not in arrived and arrived["receipt_deadline_at"]
    # 로봇이 마커로 받으려 하면 409 (병상 배송은 버튼으로만)
    by_marker = client.post(f"/api/v1/robot/deliveries/{delivery_id}/receipt", headers=robot_with_key["headers"],
                            json={"aruco_marker_id": 100})
    assert by_marker.status_code == 409 and by_marker.json()["code"] == "delivery_receipt_by_button"

    received = client.post(f"{BEDSIDE}/deliveries/{delivery_id}/receipt", headers=bed_301["headers"])
    assert received.status_code == 200 and received.json()["status"] == "received"
    # 로봇은 /robot/me에서 맡은 배송이 없어진 것으로 수령을 알아차린다
    assert client.get(ME, headers=robot_with_key["headers"]).json()["active_delivery"] is None
    # 병상 배송은 간호사에게 출발·도착·수령 알림을 보내지 않는다
    assert [message["event"] for message in published if message["event"].startswith("delivery_")] == []

    history = client.get(f"/api/v1/deliveries/{delivery_id}/events", headers=auth_headers).json()
    assert [(event["event_type"], event["actor_type"], event["actor_name"]) for event in history] == [
        ("reserved", "bedside", "301호-1"), ("dispatched", "robot", "배송로봇 1호"),
        ("arrived", "robot", "배송로봇 1호"), ("received", "bedside", "301호-1")]
    log = client.get("/api/v1/delivery-events", headers=auth_headers, params={"delivery_id": delivery_id}).json()
    assert {(event["requester_type"], event["requester_name"]) for event in log} == {("bedside", "301호-1")}
    # 다 받았으니 새 요청을 할 수 있다
    assert _request(client, bed_301, seed["blanket"].id).status_code == 201


@requires_db
def test_failed_bedside_delivery_restores_stock_and_tells_admin_only(client, db, robot_with_key, bed_301, seed, published):
    delivery_id = _request(client, bed_301, seed["blanket"].id, 2).json()["id"]
    assert client.post(CLAIM, headers=robot_with_key["headers"]).status_code == 200
    assert _progress(client, robot_with_key, delivery_id, "arrived").status_code == 200
    assert _progress(client, robot_with_key, delivery_id, "failed", "not_received").status_code == 200
    db.refresh(seed["blanket"])
    assert seed["blanket"].stock_qty == 5                                  # 재고 복구
    failures = [message for message in published if message["event"] == "delivery_failed"]
    assert len(failures) == 1 and failures[0]["recipient_role"] == "admin" and failures[0]["recipient_nurse_id"] is None
    assert [message["event"] for message in published if message["event"].startswith("delivery_")] == ["delivery_failed"]


@requires_db
def test_other_bedside_cannot_confirm(client, make_bedside, robot_with_key, bed_301, seed):
    delivery_id = _request(client, bed_301, seed["blanket"].id).json()["id"]
    client.post(CLAIM, headers=robot_with_key["headers"])
    _progress(client, robot_with_key, delivery_id, "arrived")
    other = make_bedside("301호-2", seed["room_301"].id)
    denied = client.post(f"{BEDSIDE}/deliveries/{delivery_id}/receipt", headers=other["headers"])
    assert denied.status_code == 403 and denied.json()["code"] == "delivery_not_for_bedside"


@requires_db
def test_nurse_cannot_see_bedside_delivery_but_admin_can(client, auth_headers, general_nurse_headers, bed_301, seed):
    delivery_id = _request(client, bed_301, seed["blanket"].id).json()["id"]
    assert client.get(f"/api/v1/deliveries/{delivery_id}/events", headers=general_nurse_headers).status_code == 403
    assert client.get(f"/api/v1/deliveries/{delivery_id}/events", headers=auth_headers).status_code == 200


# ---- 삭제 보호 -------------------------------------------------------------------

@requires_db
def test_delete_protection(client, auth_headers, bed_301, seed):
    _request(client, bed_301, seed["blanket"].id)
    busy = client.delete(f"{DEVICES}/{bed_301['id']}", headers=auth_headers)
    assert busy.status_code == 409 and busy.json()["code"] == "bedside_has_active_delivery"
    room = client.delete(f"/api/v1/locations/{seed['room_301'].id}", headers=auth_headers)
    assert room.status_code == 409 and room.json()["code"] == "location_is_bedside_room"
