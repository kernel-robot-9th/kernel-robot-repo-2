# =============================================================================
# 파일   : app/models/delivery.py
# 역할   : deliveries / delivery_items — 배송 예약
# 작성일 : 2026-10-14
# 구성   :
#   - Delivery      예약 헤더 (누가·어디로·언제) + 수령 기록 (받은 시각·간호사·확인한 로봇 — 2026-10-19)
#                   + 배정·진행 (맡은 로봇·출발·도착·실패 시각·실패 사유·일회용 수령 마커 — 2026-10-20)
#                   + 예약한 쪽 (간호사 또는 병상 단말 — 환자 요청, 버튼 수령 — 2026-10-22)
#   - DeliveryItem  예약 품목 라인
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, TimestampMixin
from app.models.enums import DeliveryFailureReason, DeliveryRequester, DeliveryStatus, check_values

# received면 받은 시각이 있고, 간호사 배송이면 받은 간호사도 있다(병상 배송은 버튼 수령이라 간호사 없음 — 0010).
# 아니면 수령 기록이 모두 비어 있다. 확인한 로봇은 로봇 행 삭제(ON DELETE SET NULL)로 received여도 비어 있을 수 있다
# 아래 수령·예약한 쪽 SQL은 마이그레이션 0010에 같은 문자열로 들어 있다
RECEIPT_CONSISTENCY_SQL = (
    "(status = 'received' AND received_at IS NOT NULL"
    " AND (received_by_nurse_id IS NOT NULL OR requester_type = 'bedside'))"
    " OR (status <> 'received' AND received_at IS NULL AND received_by_nurse_id IS NULL AND received_by_robot_id IS NULL)"
)
# 간호사 예약이면 간호사가, 병상 요청이면 병상 이름(스냅숏)이 있다. 병상 단말 id는 단말을 지우면 NULL
REQUESTER_CONSISTENCY_SQL = (
    "(requester_type = 'nurse' AND nurse_id IS NOT NULL AND bedside_device_id IS NULL AND bedside_name IS NULL)"
    " OR (requester_type = 'bedside' AND nurse_id IS NULL AND bedside_name IS NOT NULL)"
)
BEDSIDE_ACTIVE_SQL = "status IN ('reserved', 'dispatched', 'arrived')"

# 일회용 수령 마커: ArUco DICT_4X4_250의 50~249번. 0~49는 간호사 고정 마커(DICT_4X4_50 = DICT_4X4_250 앞 50개)
RECEIPT_MARKER_ID_MIN = 50
RECEIPT_MARKER_ID_MAX = 249
# 도착 후 수령을 기다리는 시간. 지나면 로봇(실행기)이 not_received로 실패 보고 (사용자 결정 2026-10-20: 5분)
RECEIPT_WAIT_SECONDS = 300

# 아래 SQL은 마이그레이션 0008에 같은 문자열로 들어 있다 — 바꾸면 새 마이그레이션으로
# dispatched·arrived면 출발 시각과 맡은 로봇이 있다 (로봇 삭제는 진행 중이면 서비스가 막는다)
DISPATCH_CONSISTENCY_SQL = (
    "status NOT IN ('dispatched', 'arrived') OR (dispatched_at IS NOT NULL AND assigned_robot_id IS NOT NULL)"
)
# arrived면 도착 시각과 일회용 마커가 있다 (마커는 arrived를 벗어나도 기록으로 남긴다)
ARRIVAL_CONSISTENCY_SQL = "status <> 'arrived' OR (arrived_at IS NOT NULL AND receipt_marker_id IS NOT NULL)"
# failed와 실패 시각·사유는 함께 있거나 함께 없다
FAILURE_CONSISTENCY_SQL = (
    "(status = 'failed' AND failed_at IS NOT NULL AND failure_reason IS NOT NULL)"
    " OR (status <> 'failed' AND failed_at IS NULL AND failure_reason IS NULL)"
)
RECEIPT_MARKER_RANGE_SQL = (
    f"receipt_marker_id IS NULL OR receipt_marker_id BETWEEN {RECEIPT_MARKER_ID_MIN} AND {RECEIPT_MARKER_ID_MAX}"
)
ACTIVE_STATUSES_SQL = "status IN ('dispatched', 'arrived')"

if TYPE_CHECKING:
    from app.models.bedside_device import BedsideDevice
    from app.models.location import Location
    from app.models.nurse import Nurse
    from app.models.robot import Robot
    from app.models.supply import Supply


class Delivery(TimestampMixin, Base):
    """배송 예약. 간호사가 입력한 "언제·어디로·무엇을"과 상태.
    로봇(AMR)이 claim해서 맡고(dispatched), 도착을 보고하면(arrived) 일회용 마커가 생기고,
    로봇이 그 마커를 읽으면 received. 실패하면 failed(사유). 상태 흐름은 enums.DeliveryStatus.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(f"status IN ({check_values(DeliveryStatus)})", name="ck_deliveries_status"),
        CheckConstraint(RECEIPT_CONSISTENCY_SQL, name="ck_deliveries_receipt"),
        CheckConstraint(DISPATCH_CONSISTENCY_SQL, name="ck_deliveries_dispatch"),
        CheckConstraint(ARRIVAL_CONSISTENCY_SQL, name="ck_deliveries_arrival"),
        CheckConstraint(FAILURE_CONSISTENCY_SQL, name="ck_deliveries_failure"),
        CheckConstraint(
            f"failure_reason IS NULL OR failure_reason IN ({check_values(DeliveryFailureReason)})",
            name="ck_deliveries_failure_reason",
        ),
        CheckConstraint(RECEIPT_MARKER_RANGE_SQL, name="ck_deliveries_receipt_marker_range"),
        # 지금 도착해 있는 배송끼리는 일회용 마커가 겹치지 않는다
        Index("uq_deliveries_receipt_marker_arrived", "receipt_marker_id", unique=True,
              postgresql_where=text("status = 'arrived'")),
        # 로봇 한 대는 진행 중 배송을 하나만 맡는다
        Index("uq_deliveries_assigned_robot_active", "assigned_robot_id", unique=True,
              postgresql_where=text(ACTIVE_STATUSES_SQL)),
        # claim: reserved이고 예약 시각이 지난 것을 이른 순으로
        Index("ix_deliveries_status_scheduled_at", "status", "scheduled_at"),
        # 예약한 쪽 (2026-10-22)
        CheckConstraint(f"requester_type IN ({check_values(DeliveryRequester)})", name="ck_deliveries_requester_type"),
        CheckConstraint(REQUESTER_CONSISTENCY_SQL, name="ck_deliveries_requester"),
        # 병상 하나는 진행 중(예약·출발·도착) 배송을 하나만 (사용자 결정: 승인 없이 바로 가므로 남용 방지)
        Index("uq_deliveries_bedside_active", "bedside_device_id", unique=True,
              postgresql_where=text(BEDSIDE_ACTIVE_SQL)),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nurse_id: Mapped[int | None] = mapped_column(ForeignKey("nurses.id"), index=True)  # 예약한 간호사 (병상 요청이면 NULL)
    destination_location_id: Mapped[int] = mapped_column(  # 배송 위치
        ForeignKey("locations.id", name="fk_deliveries_destination_location_id"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 배송 예정 시각 (시간대 포함)
    status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.RESERVED, nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 수령 확인 시각
    received_by_nurse_id: Mapped[int | None] = mapped_column(  # 마커로 확인된 간호사 (= 예약한 간호사)
        ForeignKey("nurses.id", name="fk_deliveries_received_by_nurse_id")
    )
    received_by_robot_id: Mapped[int | None] = mapped_column(  # 마커를 읽은 로봇. 로봇을 지우면 NULL
        ForeignKey("robots.id", name="fk_deliveries_received_by_robot_id", ondelete="SET NULL")
    )
    # ---- 배정·진행 (2026-10-20) ----
    assigned_robot_id: Mapped[int | None] = mapped_column(  # claim한 로봇. 진행 중엔 삭제 불가, 끝난 뒤 지우면 NULL
        ForeignKey("robots.id", name="fk_deliveries_assigned_robot_id", ondelete="SET NULL")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 로봇이 맡아 출발한 시각
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))     # 목적지 도착 보고 시각
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))      # 실패 보고 시각
    failure_reason: Mapped[str | None] = mapped_column(String(32))                    # DeliveryFailureReason
    receipt_marker_id: Mapped[int | None] = mapped_column(Integer)  # 일회용 수령 마커 (DICT_4X4_250 50~249), 도착 때 생성
    # ---- 예약한 쪽 (2026-10-22) ----
    requester_type: Mapped[str] = mapped_column(  # DeliveryRequester: nurse(간호사 예약) | bedside(환자 요청)
        String(8), default=DeliveryRequester.NURSE, server_default=DeliveryRequester.NURSE.value, nullable=False
    )
    bedside_device_id: Mapped[int | None] = mapped_column(  # 요청한 병상 단말. 단말을 지우면 NULL
        ForeignKey("bedside_devices.id", name="fk_deliveries_bedside_device_id", ondelete="SET NULL"), index=True
    )
    bedside_name: Mapped[str | None] = mapped_column(String(64))  # 요청한 병상 이름 스냅숏 (단말을 지워도 남음)

    destination_location: Mapped[Location] = relationship()
    nurse: Mapped[Nurse | None] = relationship(foreign_keys=[nurse_id])  # 예약한 간호사 (배송 기록 화면 — 2026-10-21)
    assigned_robot: Mapped[Robot | None] = relationship(foreign_keys=[assigned_robot_id])
    bedside_device: Mapped[BedsideDevice | None] = relationship()
    items: Mapped[list[DeliveryItem]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryItem.id"
    )

    @property
    def receipt_deadline_at(self) -> datetime | None:
        """수령 마감 시각 (arrived일 때만).
        [입력] 없음
        [출력] datetime | None: arrived_at + RECEIPT_WAIT_SECONDS
        """
        if self.status != DeliveryStatus.ARRIVED or self.arrived_at is None:
            return None
        return self.arrived_at + timedelta(seconds=RECEIPT_WAIT_SECONDS)

    @property
    def requester_name(self) -> str:
        """예약한 쪽 이름 (배송 기록 화면): 간호사 이름 또는 병상 이름.
        [입력] 없음
        [출력] str
        """
        if self.requester_type == DeliveryRequester.BEDSIDE:
            return self.bedside_name or ""
        return self.nurse.name if self.nurse else ""

    @property
    def receipt_method(self) -> str:
        """수령 방법: button = "받았습니다" 버튼(병상 배송은 항상, 간호사 배송은 NURSE_RECEIPT_METHOD=button일 때 — 2026-10-22 기본)
        / marker = 로봇이 일회용 마커를 읽음(간호사 배송, NURSE_RECEIPT_METHOD=marker)
        / none = 로봇 전용 장소(충전 등)로의 이동 — 도착 보고가 곧 완료(received).
        [입력] 없음
        [출력] str
        """
        if self.destination_location is not None and self.destination_location.robot_only:
            return "none"   # 로봇 전용 장소(충전 등)로의 품목 없는 이동 — 도착하면 끝 (2026-10-22)
        if self.requester_type == DeliveryRequester.BEDSIDE:
            return "button"
        return settings.NURSE_RECEIPT_METHOD

    @property
    def assigned_robot_name(self) -> str | None:
        """맡은 로봇 이름 (DeliveryOut용).
        [입력] 없음
        [출력] str | None: 배정 전이거나 로봇을 지웠으면 None
        """
        return self.assigned_robot.name if self.assigned_robot else None


class DeliveryItem(Base):
    """예약 품목 라인. 한 예약에 같은 비품은 한 줄만 (UNIQUE)."""

    __tablename__ = "delivery_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_delivery_items_quantity"),
        UniqueConstraint("delivery_id", "supply_id", name="uq_delivery_items_delivery_supply"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_id: Mapped[int] = mapped_column(ForeignKey("supplies.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # 예약 수량

    delivery: Mapped[Delivery] = relationship(back_populates="items")
    supply: Mapped[Supply] = relationship()

    @property
    def supply_name(self) -> str:
        """비품 이름 (로봇용 응답·알림).
        [입력] 없음
        [출력] str
        """
        return self.supply.name
