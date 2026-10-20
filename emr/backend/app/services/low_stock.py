# =============================================================================
# 파일   : app/services/low_stock.py
# 역할   : 재고 부족 판단과 알림 발행 (2026-10-16)
# 작성일 : 2026-10-16
# 구성   :
#   - is_low_stock()     비품이 지금 부족한가
#   - LowStockNotifier   재고·기준이 바뀐 뒤 부족 상태가 달라졌으면 알림 (SupplyService·DeliveryService가 사용)
# 알림은 상태가 바뀔 때만 보낸다 — 부족한 채로 더 줄어도 다시 보내지 않는다. 지금 부족한 목록은 GET /notifications/low-stock
# =============================================================================
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.enums import NotificationEvent
from app.models.supply import Supply
from app.repositories.notification import NotificationRepository


def is_low_stock(supply: Supply) -> bool:
    """재고가 알림 기준 이하인가. 기준이 없거나 삭제된 비품은 부족으로 보지 않는다.
    SupplyRepository.list_low_stock의 SQL 조건과 같게 유지한다.
    [입력] supply
    [출력] bool
    """
    return (
        not supply.is_deleted
        and supply.low_stock_threshold_qty is not None
        and supply.stock_qty <= supply.low_stock_threshold_qty
    )


class LowStockNotifier:
    """변경 전 부족 여부를 받아, 변경 후와 다르면 알림을 발행한다."""

    def __init__(self, db: Session) -> None:
        self.notifications = NotificationRepository(db)

    def notify_if_changed(self, supply: Supply, was_low_stock: bool) -> None:
        """부족 상태가 바뀌었으면 low_stock 또는 low_stock_resolved 알림을 보낸다.
        [입력] supply: 변경을 반영한 비품 / was_low_stock: 변경 전 is_low_stock 값
        [출력] 없음 (commit될 때 전달)
        """
        now_low_stock = is_low_stock(supply)
        if now_low_stock == was_low_stock:
            return
        event = NotificationEvent.LOW_STOCK if now_low_stock else NotificationEvent.LOW_STOCK_RESOLVED
        self.notifications.publish({
            "event": event.value,
            "supply_id": supply.id,
            "code": supply.code,
            "name": supply.name,
            "stock_qty": supply.stock_qty,
            "low_stock_threshold_qty": supply.low_stock_threshold_qty,
        })
