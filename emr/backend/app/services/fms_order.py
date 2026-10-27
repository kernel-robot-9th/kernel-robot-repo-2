# =============================================================================
# 파일   : app/services/fms_order.py
# 역할   : 신청 시각이 된 배송을 팀원 FMS에 물품 1개당 주문 1건으로 보낸다 (2026-10-27, FMS API v1 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - request_id_for()     emr-d{배송}-s{비품}-{n} — 같은 물품은 언제 보내도 같은 값(FMS가 같은 request_id를 처음 주문으로 돌려줌)
#   - FmsOrderSender       send_due(now) — 한 회차(app/main.py 주기 작업이 FMS_SEND_INTERVAL_SECONDS마다)
#   - run_send_round()     주기 작업용: 세션을 열어 한 회차 → commit (실패하면 rollback 후 로그)
# 받음(202·200) → fms_orders에 한 줄, 배송은 reserved 그대로(출발은 FMS batch_assigned 이벤트 — services/fms_events.py).
# 거절(4xx) → 로그만, 다음 회차에 다시. 응답 없음·5xx → 그 회차를 멈춘다. 1단계는 실패로 바꾸지 않는다.
# 계약: docs/api_contract_delivery_2026-10-20.md 10.1
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.clients.fms import FmsRejected, FmsUnavailable, create_order
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.delivery import Delivery
from app.models.enums import FmsOrderStatus
from app.models.fms_order import FmsOrder
from app.repositories.delivery import DeliveryRepository
from app.repositories.fms_order import FmsOrderRepository

log = structlog.get_logger(__name__)


def request_id_for(delivery_id: int, supply_id: int, nth: int) -> str:
    """FMS 주문의 request_id.
    [입력] delivery_id / supply_id / nth: 같은 비품의 몇 번째 개(1부터)
    [출력] str: 예 "emr-d55-s1-2"
    """
    return f"emr-d{delivery_id}-s{supply_id}-{nth}"


class FmsOrderSender:
    """reserved·신청 시각 지남·목적지 robot_dest 있음 → 아직 안 보낸 물품을 FMS로. 한 회차 = 한 트랜잭션(commit은 부르는 쪽)."""

    def __init__(self, db: Session) -> None:
        self.deliveries = DeliveryRepository(db)
        self.orders = FmsOrderRepository(db)

    def send_due(self, now: datetime) -> int:
        """한 회차.
        [입력] now: 지금 시각
        [출력] int: 이번 회차에 FMS가 받은 주문 수 (FMS_BASE_URL이 없거나 다른 회차가 돌고 있으면 0)
        """
        if not settings.FMS_BASE_URL or not self.orders.try_lock_send_round():
            return 0
        accepted = 0
        for delivery in self.deliveries.lock_due_for_fms(now):
            try:
                accepted += self._send_delivery(delivery, now)
            except FmsUnavailable as error:
                log.warning("fms_unavailable", delivery_id=delivery.id, error=str(error))
                break   # 남은 배송도 같은 FMS — 다음 회차에
        return accepted

    def _send_delivery(self, delivery: Delivery, now: datetime) -> int:
        """배송 하나의 아직 안 보낸 물품을 하나씩 보낸다.
        [입력] delivery: 품목·목적지 로드됨 / now
        [출력] int: FMS가 받은 주문 수 (FmsUnavailable은 그대로 올린다)
        """
        sent = {(order.supply_id, order.nth) for order in self.orders.list_for_delivery(delivery.id)}
        room = delivery.destination_location.robot_dest
        accepted = 0
        for item in delivery.items:
            for nth in range(1, item.quantity + 1):
                if (item.supply_id, nth) in sent:
                    continue
                request_id = request_id_for(delivery.id, item.supply_id, nth)
                try:
                    order = create_order(settings.FMS_BASE_URL, request_id, room, item.supply_name, settings.FMS_TIMEOUT_SECONDS)
                except FmsRejected as rejection:
                    log.warning("fms_order_rejected", delivery_id=delivery.id, request_id=request_id, room=room,
                                code=rejection.code, detail=rejection.message)
                    return accepted   # 이 배송은 다음 회차에 다시 (방 이름이 틀렸으면 관리자가 장소를 고친다)
                self.orders.add(FmsOrder(
                    delivery_id=delivery.id, supply_id=item.supply_id, nth=nth, request_id=request_id,
                    fms_order_id=str(order["order_id"]), status=str(order.get("status") or FmsOrderStatus.QUEUED),
                    batch_id=order.get("batch_id"), fms_robot_number=order.get("robot"), sent_at=now,
                ))
                accepted += 1
                log.info("fms_order_sent", delivery_id=delivery.id, request_id=request_id, fms_order_id=order["order_id"], room=room)
        return accepted


def run_send_round() -> None:
    """주기 작업 한 회차 — 자기 세션으로 돌고 commit. 예외는 로그만 남기고 다음 회차로.
    [입력] 없음
    [출력] 없음
    """
    with SessionLocal() as db:
        try:
            FmsOrderSender(db).send_due(datetime.now(UTC))
            db.commit()
        except Exception:   # 주기 작업이 죽지 않게 — 원인은 로그로
            db.rollback()
            log.exception("fms_send_round_failed")
