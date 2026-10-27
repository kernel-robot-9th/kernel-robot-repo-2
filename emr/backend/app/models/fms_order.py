# =============================================================================
# 파일   : app/models/fms_order.py
# 역할   : fms_orders — EMR 배송의 물품 1개를 팀원 FMS에 보낸 주문 한 건 (FMS API v1 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsOrder  배송·비품·n번째, request_id(EMR이 만듦), FMS order_id·batch_id·로봇 번호·주문 상태, 보낸·배송된 시각
# FMS는 물품 1개 = 주문 1건이라 배송(품목 줄 × 수량) 하나가 여러 줄이 된다. 배송이 arrived가 되는 때 = 이 표의 그 배송 줄이
# 모두 delivered (services/fms_events.py). 계약 docs/api_contract_delivery_2026-10-20.md 10장
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import FmsOrderStatus, check_values


class FmsOrder(Base):
    """FMS에 보낸 주문 한 건. 배송을 지우면 함께 지운다."""

    __tablename__ = "fms_orders"
    __table_args__ = (
        UniqueConstraint("delivery_id", "supply_id", "nth", name="uq_fms_orders_delivery_supply_nth"),
        CheckConstraint(f"status IN ({check_values(FmsOrderStatus)})", name="ck_fms_orders_status"),
        CheckConstraint("nth >= 1", name="ck_fms_orders_nth"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("deliveries.id", name="fk_fms_orders_delivery_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    supply_id: Mapped[int] = mapped_column(ForeignKey("supplies.id", name="fk_fms_orders_supply_id"), nullable=False)
    nth: Mapped[int] = mapped_column(Integer, nullable=False)   # 같은 비품의 몇 번째 개(1부터)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)   # emr-d{배송}-s{비품}-{n}
    fms_order_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)   # FMS가 준 o-17 — FMS를 다시 켜면 o-1부터 다시라 UNIQUE 아님
    batch_id: Mapped[str | None] = mapped_column(String(32))          # batch_assigned 때 (b-5)
    fms_robot_number: Mapped[int | None] = mapped_column(Integer)     # FMS 로봇 번호 1·2·3 (EMR 로봇 id 아님)
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # FMS 주문 상태 (enums.FmsOrderStatus)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   # FMS가 받은(202·200) 시각
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))       # order_delivered를 받은 시각
