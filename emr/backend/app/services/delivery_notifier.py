# =============================================================================
# 파일   : app/services/delivery_notifier.py
# 역할   : 배송 단계 알림 발행 — DeliveryService·DispatchService가 함께 쓴다 (2026-10-20 분리)
# 작성일 : 2026-10-20
# 구성   :
#   - DeliveryNotifier  notify_dispatched·arrived·received (예약한 간호사에게만), notify_failed (+ 관리자) — 2026-10-20
#                       병상(환자) 배송은 출발·도착·수령을 보내지 않고 실패만 관리자에게 (2026-10-22, 사용자 결정).
#                       recipient_nurse_id 없이 발행하면 모든 간호사에게 퍼지므로 병상 배송은 반드시 여기서 거른다
# 알림은 저장하지 않는다. NotificationRepository.publish가 트랜잭션 안에서 pg_notify → commit될 때만 전달된다
# (409 등으로 롤백된 요청의 알림은 나가지 않는다). 받는 사람 거르기는 app/core/notification_hub.py
# =============================================================================
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.delivery import Delivery
from app.models.enums import DeliveryRequester, NotificationEvent, NurseRole
from app.repositories.notification import NotificationRepository

NOTIFICATION_MAX_ITEMS = 5   # 알림에 이름을 싣는 품목 수 — NOTIFY 한도(8000바이트) 안에 들도록


class DeliveryNotifier:
    """배송 알림 payload를 만들어 발행한다."""

    def __init__(self, db: Session) -> None:
        self.notifications = NotificationRepository(db)

    def notify_dispatched(self, delivery: Delivery) -> None:
        """출발 알림 — 예약한 간호사에게만.
        [입력] delivery: dispatched로 바꾼 배송
        [출력] 없음 (commit될 때 전달)
        """
        if self._is_bedside(delivery):   # 병상 배송: 간호사에게 보내지 않음
            return
        self.notifications.publish({
            **self._base(delivery, NotificationEvent.DELIVERY_DISPATCHED),
            "dispatched_at": delivery.dispatched_at.isoformat() if delivery.dispatched_at else None,
        })

    def notify_arrived(self, delivery: Delivery) -> None:
        """도착 알림 — 일회용 수령 마커가 들어 있으므로 **예약한 간호사에게만**(역할 수신자를 붙이지 않는다).
        [입력] delivery: arrived로 바꾼 배송
        [출력] 없음
        """
        if self._is_bedside(delivery):   # 병상 배송: 간호사에게 보내지 않음
            return
        deadline = delivery.receipt_deadline_at
        self.notifications.publish({
            **self._base(delivery, NotificationEvent.DELIVERY_ARRIVED),
            "receipt_marker_id": delivery.receipt_marker_id,
            "receipt_deadline_at": deadline.isoformat() if deadline else None,
            "receipt_method": delivery.receipt_method,   # button이면 화면의 "받았습니다" (2026-10-22)
        })

    def notify_failed(self, delivery: Delivery) -> None:
        """실패 알림 — 예약한 간호사와 관리자에게 (한 메시지).
        [입력] delivery: failed로 바꾼 배송
        [출력] 없음
        """
        self.notifications.publish({
            **self._base(delivery, NotificationEvent.DELIVERY_FAILED),
            "recipient_role": NurseRole.ADMIN.value,
            "failure_reason": delivery.failure_reason,
        })

    def notify_received(self, delivery: Delivery) -> None:
        """수령 완료 알림 — 예약한 간호사에게만.
        [입력] delivery: received로 바꾼 배송 (품목·목적지·맡은 로봇 로드됨)
        [출력] 없음 (commit될 때 전달)
        """
        if self._is_bedside(delivery):   # 병상 배송: 간호사에게 보내지 않음
            return
        self.notifications.publish({
            **self._base(delivery, NotificationEvent.DELIVERY_RECEIVED),
            "received_at": delivery.received_at.isoformat() if delivery.received_at else None,
        })

    @staticmethod
    def _is_bedside(delivery: Delivery) -> bool:
        """병상 단말(환자) 배송인지."""
        return delivery.requester_type == DeliveryRequester.BEDSIDE

    @staticmethod
    def _base(delivery: Delivery, event: NotificationEvent) -> dict[str, Any]:
        """모든 배송 알림에 공통인 필드.
        [입력] delivery / event
        [출력] dict: event·recipient_nurse_id·delivery_id·destination_location_name·robot_name·items(앞 5개)·item_count
        """
        return {
            "event": event.value,
            "recipient_nurse_id": delivery.nurse_id,
            "bedside_name": delivery.bedside_name,   # 병상 요청이면 병상 이름 (관리자 실패 알림, 2026-10-22)
            "delivery_id": delivery.id,
            "destination_location_name": delivery.destination_location.name,
            "robot_name": delivery.assigned_robot_name,
            "items": [{"name": item.supply.name, "quantity": item.quantity}
                      for item in delivery.items[:NOTIFICATION_MAX_ITEMS]],
            "item_count": len(delivery.items),
        }
