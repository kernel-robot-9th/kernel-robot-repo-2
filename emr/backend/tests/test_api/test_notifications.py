"""재고 부족 알림 (2026-10-16). PostgreSQL 필요.
테스트는 트랜잭션을 롤백하므로 NOTIFY가 실제로 전달되지 않는다 — 발행 내용은 NotificationRepository.publish를 바꿔 기록한다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.notification import NotificationRepository
from tests.conftest import requires_db

SUPPLIES = "/api/v1/supplies"
LOW_STOCK = "/api/v1/notifications/low-stock"


@pytest.fixture
def published(monkeypatch) -> list[dict]:
    """발행된 알림 목록. publish가 NOTIFY 대신 여기에 쌓는다."""
    messages: list[dict] = []
    monkeypatch.setattr(NotificationRepository, "publish", lambda self, message: messages.append(message))
    return messages


def _events(published: list[dict]) -> list[tuple[str, str]]:
    return [(message["event"], message["code"]) for message in published]


@requires_db
def test_notifications_require_login(client, seed):
    assert client.get(LOW_STOCK).status_code == 401
    assert client.get("/api/v1/notifications/stream").status_code == 401


@requires_db
def test_low_stock_list_and_threshold_edit(logged_in_client, seed, published):
    supply_id = seed["medication"].id  # 재고 10, 기준 없음
    assert logged_in_client.get(LOW_STOCK).json() == []

    # 기준을 재고 이상으로 올리면 부족 → 알림 + 목록에 나온다
    response = logged_in_client.patch(f"{SUPPLIES}/{supply_id}", json={"low_stock_threshold_qty": 10})
    assert response.status_code == 200 and response.json()["low_stock_threshold_qty"] == 10
    assert [supply["code"] for supply in logged_in_client.get(LOW_STOCK).json()] == ["MED-A"]
    assert _events(published) == [("low_stock", "MED-A")]
    assert published[0]["stock_qty"] == 10 and published[0]["low_stock_threshold_qty"] == 10

    # 부족한 채로 재고가 더 줄면 다시 알리지 않는다
    logged_in_client.patch(f"{SUPPLIES}/{supply_id}", json={"stock_qty": 4})
    assert len(published) == 1

    # 입고로 기준 위로 → 해제 알림
    logged_in_client.patch(f"{SUPPLIES}/{supply_id}", json={"stock_qty": 11})
    assert _events(published)[-1] == ("low_stock_resolved", "MED-A")
    assert logged_in_client.get(LOW_STOCK).json() == []

    # 기준은 null로 지울 수 있고, 음수는 422
    assert logged_in_client.patch(f"{SUPPLIES}/{supply_id}", json={"low_stock_threshold_qty": -1}).status_code == 422
    response = logged_in_client.patch(f"{SUPPLIES}/{supply_id}", json={"low_stock_threshold_qty": None})
    assert response.status_code == 200 and response.json()["low_stock_threshold_qty"] is None


@requires_db
def test_low_stock_on_create_and_delete(logged_in_client, seed, published):
    response = logged_in_client.post(SUPPLIES, json={
        "code": "SUP-LOW", "name": "거즈", "category": "supply", "requestable_by": "nurse",
        "stock_qty": 2, "low_stock_threshold_qty": 5})
    assert response.status_code == 201
    assert _events(published) == [("low_stock", "SUP-LOW")]
    # 삭제하면 목록에서 빠지도록 해제 알림
    assert logged_in_client.delete(f"{SUPPLIES}/{response.json()['id']}").status_code == 204
    assert _events(published)[-1] == ("low_stock_resolved", "SUP-LOW")
    assert logged_in_client.get(LOW_STOCK).json() == []


@requires_db
def test_low_stock_on_delivery_reserve_and_cancel(logged_in_client, seed, published):
    logged_in_client.patch(f"{SUPPLIES}/{seed['medication'].id}", json={"low_stock_threshold_qty": 5})  # 재고 10
    assert published == []
    body = {"destination_location_id": seed["room_301"].id,
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "items": [{"supply_id": seed["medication"].id, "quantity": 5}]}

    delivery = logged_in_client.post("/api/v1/deliveries", json=body).json()  # 10 → 5: 기준 이하
    assert _events(published) == [("low_stock", "MED-A")] and published[0]["stock_qty"] == 5

    # 재고가 모자라 409면 재고도 알림도 바뀌지 않는다
    response = logged_in_client.post("/api/v1/deliveries", json={**body, "items": [{"supply_id": seed["medication"].id, "quantity": 99}]})
    assert response.status_code == 409 and len(published) == 1

    logged_in_client.post(f"/api/v1/deliveries/{delivery['id']}/cancel")  # 5 → 10: 해제
    assert _events(published)[-1] == ("low_stock_resolved", "MED-A")
