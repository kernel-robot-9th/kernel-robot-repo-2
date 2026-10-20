"""알림 중계 — 받는 사람 거르기 (2026-10-19). DB 없이 도는 단위 테스트."""
from __future__ import annotations

from app.core.notification_hub import NotificationHub


def _drain(queue) -> list[str]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait()["event"])
    return events


def test_message_without_recipient_goes_to_everyone():
    hub = NotificationHub()
    nurse_a, nurse_b = hub.subscribe(1), hub.subscribe(2)
    hub.broadcast({"event": "low_stock"})
    assert _drain(nurse_a) == ["low_stock"] and _drain(nurse_b) == ["low_stock"]


def test_message_with_recipient_goes_only_to_that_nurse_all_tabs():
    hub = NotificationHub()
    nurse_a_tab1, nurse_a_tab2, nurse_b = hub.subscribe(1), hub.subscribe(1), hub.subscribe(2)
    hub.broadcast({"event": "delivery_received", "recipient_nurse_id": 1})
    assert _drain(nurse_a_tab1) == ["delivery_received"] and _drain(nurse_a_tab2) == ["delivery_received"]
    assert _drain(nurse_b) == []


def test_unsubscribed_queue_gets_nothing():
    hub = NotificationHub()
    queue = hub.subscribe(1)
    hub.unsubscribe(queue)
    hub.unsubscribe(queue)  # 두 번 해제해도 괜찮다
    hub.broadcast({"event": "low_stock"})
    assert _drain(queue) == []


def test_role_recipient_reaches_role_and_named_nurse_once():
    """실패 알림: 예약 간호사(nurse 1) + 관리자 역할. 관리자이면서 예약자여도 한 번만 받는다 (2026-10-20)."""
    hub = NotificationHub()
    owner = hub.subscribe(1, "nurse")
    admin = hub.subscribe(2, "admin")
    other_nurse = hub.subscribe(3, "nurse")
    hub.broadcast({"event": "delivery_failed", "recipient_nurse_id": 1, "recipient_role": "admin"})
    assert _drain(owner) == ["delivery_failed"] and _drain(admin) == ["delivery_failed"]
    assert _drain(other_nurse) == []

    admin_owner = hub.subscribe(4, "admin")
    hub.broadcast({"event": "delivery_failed", "recipient_nurse_id": 4, "recipient_role": "admin"})
    assert _drain(admin_owner) == ["delivery_failed"]   # 한 번만


def test_arrival_marker_goes_only_to_owner_not_admins():
    hub = NotificationHub()
    owner, admin = hub.subscribe(1, "nurse"), hub.subscribe(2, "admin")
    hub.broadcast({"event": "delivery_arrived", "recipient_nurse_id": 1, "receipt_marker_id": 137})
    assert _drain(owner) == ["delivery_arrived"] and _drain(admin) == []
