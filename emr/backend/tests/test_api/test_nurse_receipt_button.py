"""간호사 "받았습니다" 버튼 수령 (2026-10-22, 사용자 결정: 마커는 일단 끄고 간호사도 버튼). PostgreSQL 필요.
설정 NURSE_RECEIPT_METHOD: button(기본) | marker(마커를 되살릴 때). 계약: docs/api_contract_delivery_2026-10-20.md 3.4·5장.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from tests.conftest import requires_db

DELIVERIES = "/api/v1/deliveries"
ME = "/api/v1/robot/me"


def _receipt(client, headers, delivery_id: int):
    return client.post(f"{DELIVERIES}/{delivery_id}/receipt", headers=headers)


@pytest.fixture
def marker_mode(monkeypatch):
    """마커를 되살린 설정 (NURSE_RECEIPT_METHOD=marker)."""
    monkeypatch.setattr(settings, "NURSE_RECEIPT_METHOD", "marker")


@requires_db
def test_nurse_presses_received_and_robot_notices(client, auth_headers, robot_with_key, arrived_delivery, published):
    delivery_id = arrived_delivery["id"]
    mine = client.get(f"{DELIVERIES}/{delivery_id}", headers=auth_headers).json()
    assert mine["status"] == "arrived" and mine["receipt_method"] == "button"
    robot_view = client.get(ME, headers=robot_with_key["headers"]).json()["active_delivery"]
    assert robot_view["id"] == delivery_id and robot_view["receipt_method"] == "button"   # 실행기는 마커를 기다리지 않는다

    received = _receipt(client, auth_headers, delivery_id)
    assert received.status_code == 200, received.text
    body = received.json()
    assert body["status"] == "received" and body["received_at"] is not None
    assert body["received_by_nurse_id"] == mine["nurse_id"] and body["received_by_robot_id"] == robot_with_key["id"]
    # 실행기는 /robot/me에서 맡은 배송이 없어진 것으로 수령을 알아차린다
    assert client.get(ME, headers=robot_with_key["headers"]).json()["active_delivery"] is None
    assert [message["event"] for message in published][-1] == "delivery_received"
    history = client.get(f"{DELIVERIES}/{delivery_id}/events", headers=auth_headers).json()
    assert (history[-1]["event_type"], history[-1]["actor_type"]) == ("received", "nurse")

    again = _receipt(client, auth_headers, delivery_id)
    assert again.status_code == 409 and again.json()["code"] == "delivery_not_arrived"


@requires_db
def test_button_rejections(client, auth_headers, general_nurse_headers, arrived_delivery, reserve_overdue):
    other = _receipt(client, general_nurse_headers, arrived_delivery["id"])
    assert other.status_code == 403 and other.json()["code"] == "delivery_not_owned"
    assert _receipt(client, auth_headers, 999999).status_code == 404
    not_yet = reserve_overdue()
    early = _receipt(client, auth_headers, not_yet["id"])
    assert early.status_code == 409 and early.json()["code"] == "delivery_not_arrived"


@requires_db
def test_robot_marker_receipt_still_works_in_button_mode(client, robot_with_key, arrived_delivery):
    """마커는 도착 때 여전히 만들어진다 — 로봇이 읽어 보내면 받는다(카메라 노드가 생겼을 때 대비)."""
    response = client.post(f"/api/v1/robot/deliveries/{arrived_delivery['id']}/receipt", headers=robot_with_key["headers"],
                           json={"aruco_marker_id": arrived_delivery["receipt_marker_id"]})
    assert response.status_code == 200 and response.json()["status"] == "received"


@requires_db
def test_marker_mode_turns_button_off(marker_mode, client, auth_headers, robot_with_key, arrived_delivery):
    mine = client.get(f"{DELIVERIES}/{arrived_delivery['id']}", headers=auth_headers).json()
    assert mine["receipt_method"] == "marker" and 50 <= mine["receipt_marker_id"] <= 249
    assert client.get(ME, headers=robot_with_key["headers"]).json()["active_delivery"]["receipt_method"] == "marker"
    refused = _receipt(client, auth_headers, arrived_delivery["id"])
    assert refused.status_code == 409 and refused.json()["code"] == "delivery_receipt_by_marker"
