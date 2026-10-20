"""비품 CRUD. PostgreSQL 필요."""
from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import requires_db


@requires_db
def test_supply_crud(logged_in_client):
    response = logged_in_client.post("/api/v1/supplies", json={
        "code": "MED-X", "name": "X 약품", "category": "medication", "requestable_by": "nurse",
        "stock_qty": 7})
    assert response.status_code == 201, response.text
    supply_id = response.json()["id"]
    response = logged_in_client.patch(f"/api/v1/supplies/{supply_id}", json={"stock_qty": 9})
    assert response.json()["stock_qty"] == 9
    assert logged_in_client.get("/api/v1/supplies?q=X 약").json()[0]["code"] == "MED-X"
    assert logged_in_client.delete(f"/api/v1/supplies/{supply_id}").status_code == 204
    assert logged_in_client.get(f"/api/v1/supplies/{supply_id}").status_code == 404


@requires_db
def test_supply_duplicate_code_conflict(logged_in_client, seed):
    response = logged_in_client.post("/api/v1/supplies", json={
        "code": "MED-A", "name": "dup", "category": "medication", "requestable_by": "nurse"})
    assert response.status_code == 409 and response.json()["code"] == "supply_code_duplicate"


@requires_db
def test_supply_update_null_only_for_expiry_date(logged_in_client, seed):
    supply_id = seed["medication"].id
    for field in ("name", "stock_qty", "requestable_by"):
        response = logged_in_client.patch(f"/api/v1/supplies/{supply_id}", json={field: None})
        assert response.status_code == 400 and response.json()["code"] == "supply_field_required", (field, response.text)
    response = logged_in_client.patch(f"/api/v1/supplies/{supply_id}", json={"expiry_date": None})
    assert response.status_code == 200 and response.json()["expiry_date"] is None


@requires_db
def test_supplies_require_login(client, seed):
    assert client.get("/api/v1/supplies").status_code == 401
    assert client.post("/api/v1/supplies", json={
        "code": "MED-Y", "name": "y", "category": "medication", "requestable_by": "nurse"}).status_code == 401
    assert client.delete(f"/api/v1/supplies/{seed['medication'].id}").status_code == 401


@requires_db
def test_supply_expiry_is_filled_automatically(logged_in_client):
    """유효기간을 보내지 않으면 오늘부터 6개월~1년 사이로 채운다. 보내면 그 값을 쓴다 (2026-10-19)."""
    response = logged_in_client.post("/api/v1/supplies", json={
        "code": "SUP-AUTO", "name": "자동 유효기간", "category": "supply", "requestable_by": "nurse"})
    assert response.status_code == 201, response.text
    expiry = date.fromisoformat(response.json()["expiry_date"])
    assert date.today() + timedelta(days=183) <= expiry <= date.today() + timedelta(days=365)

    response = logged_in_client.post("/api/v1/supplies", json={
        "code": "SUP-GIVEN", "name": "지정 유효기간", "category": "supply", "requestable_by": "nurse",
        "expiry_date": "2027-01-31"})
    assert response.json()["expiry_date"] == "2027-01-31"
