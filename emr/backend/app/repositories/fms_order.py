# =============================================================================
# 파일   : app/repositories/fms_order.py
# 역할   : fms_orders 조회 — 팀원 FMS에 보낸 물품 1개 주문 (2026-10-27, FMS API v1 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsOrderRepository  get_by_fms_order_id, list_for_delivery, list_assigned_for_batch(2026-10-29), delivery_has_orders, try_lock_send_round
# =============================================================================
from __future__ import annotations

from sqlalchemy import func, select

from app.models.enums import FmsOrderStatus
from app.models.fms_order import FmsOrder
from app.repositories.base import BaseRepository

# 보내기 회차 잠금 키(pg advisory lock) — uvicorn 워커가 여럿이어도 한 회차만 돈다. 값은 이 저장소 안에서만 겹치지 않으면 된다
FMS_SEND_LOCK_KEY = 20261027


class FmsOrderRepository(BaseRepository[FmsOrder]):
    """fms_orders 접근."""

    model = FmsOrder

    def get_by_fms_order_id(self, fms_order_id: str, lock: bool = False) -> FmsOrder | None:
        """FMS order_id(o-17)로 한 건. FMS를 다시 켜면 o-1부터 다시 쓰므로 같은 번호면 가장 나중에 보낸 것.
        [입력] fms_order_id / lock: True면 FOR UPDATE (같은 이벤트가 겹쳐 와도 한 번씩)
        [출력] FmsOrder | None — 우리가 보내지 않은 주문이면 None
        """
        statement = select(FmsOrder).where(FmsOrder.fms_order_id == fms_order_id).order_by(FmsOrder.id.desc()).limit(1)
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def list_for_delivery(self, delivery_id: int) -> list[FmsOrder]:
        """배송 하나의 주문 전부 (비품·n번째 순).
        [입력] delivery_id
        [출력] list[FmsOrder]
        """
        statement = select(FmsOrder).where(FmsOrder.delivery_id == delivery_id).order_by(FmsOrder.supply_id, FmsOrder.nth)
        return list(self.db.scalars(statement))

    def list_assigned_for_batch(self, batch_id: str) -> list[FmsOrder]:
        """FMS 묶음에 들어가 아직 배송되지 않은(assigned) 주문 — 묶음의 준비·출발을 신청에 옮길 때 (2026-10-29).
        FMS를 다시 켜면 b-1부터 다시라, 끝난 옛 묶음의 주문(delivered·failed)은 상태로 걸러진다.
        [입력] batch_id: FMS 묶음 b-5
        [출력] list[FmsOrder]: 보낸 순
        """
        statement = (
            select(FmsOrder).where(FmsOrder.batch_id == batch_id, FmsOrder.status == FmsOrderStatus.ASSIGNED).order_by(FmsOrder.id)
        )
        return list(self.db.scalars(statement))

    def delivery_has_orders(self, delivery_id: int) -> bool:
        """이 배송의 물품을 하나라도 FMS에 보냈는지 — 보냈으면 간호사가 변경·취소할 수 없다.
        [입력] delivery_id
        [출력] bool
        """
        return self.db.scalar(select(func.count()).select_from(FmsOrder).where(FmsOrder.delivery_id == delivery_id)) > 0

    def try_lock_send_round(self) -> bool:
        """보내기 회차 잠금(트랜잭션 동안).
        [입력] 없음
        [출력] bool: 잡았으면 True, 다른 회차가 돌고 있으면 False
        """
        return bool(self.db.scalar(select(func.pg_try_advisory_xact_lock(FMS_SEND_LOCK_KEY))))
