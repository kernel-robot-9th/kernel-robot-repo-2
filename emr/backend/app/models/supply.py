# =============================================================================
# 파일   : app/models/supply.py
# 역할   : supplies — SRD-01 비품 마스터·재고
# 작성일 : 2026-10-13
# 구성   :
#   - Supply  soft delete, stock_qty, low_stock_threshold_qty(재고 부족 알림 기준 — 2026-10-16)
# =============================================================================
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import RequestableBy, SupplyCategory, check_values


class Supply(TimestampMixin, Base):
    """SRD-01 비품 마스터. 약품과 일반 비품(이불·환자복 등)을 한 테이블로. 삭제는 soft delete."""

    __tablename__ = "supplies"
    __table_args__ = (
        CheckConstraint(f"category IN ({check_values(SupplyCategory)})", name="ck_supplies_category"),
        CheckConstraint(f"requestable_by IN ({check_values(RequestableBy)})", name="ck_supplies_requestable_by"),
        CheckConstraint("stock_qty >= 0", name="ck_supplies_stock_qty"),  # 음수 재고 DB 차단
        CheckConstraint("low_stock_threshold_qty >= 0", name="ck_supplies_low_stock_threshold_qty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # 비품 고유번호 (SRD-01)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)  # medication | supply
    requestable_by: Mapped[str] = mapped_column(String(16), nullable=False)  # nurse | patient 
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 현재 재고
    low_stock_threshold_qty: Mapped[int | None] = mapped_column(Integer)  # 재고가 이 수량 이하가 되면 알림. NULL=알림 안 함
    expiry_date: Mapped[date | None] = mapped_column(Date)  # 유효기간 (SRD-01). 등록 때 비우면 6개월~1년 자동 (2026-10-19). PATCH로 null 가능
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
