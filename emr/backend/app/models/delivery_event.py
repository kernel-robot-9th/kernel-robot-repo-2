# =============================================================================
# 파일   : app/models/delivery_event.py
# 역할   : delivery_events — 배송 기록 (로드맵 4단계, 2026-10-21)
# 작성일 : 2026-10-21
# 구성   :
#   - DeliveryEvent  배송 한 건에 일어난 일 하나 (언제·무엇·누가·내용). 추가만 하고 고치거나 지우지 않는다
# 범위(사용자 결정 2026-10-21): 간호사 예약·변경·취소 + 로봇 출발·도착·수령·실패. 로봇 키·끊김·거부된 요청은 넣지 않음.
# 보관: 지우지 않음. 기존 배송(이 기능 전)은 기록을 채우지 않았다.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import DeliveryEventActor, DeliveryEventType, check_values

if TYPE_CHECKING:
    from app.models.delivery import Delivery
    from app.models.nurse import Nurse

# 아래 SQL은 마이그레이션 0009(사건 종류)·0010(행위자 — bedside 추가)·0017(사건 종류 — preparing 추가)에 같은 값으로 들어 있다 — 바꾸면 새 마이그레이션으로
EVENT_TYPE_SQL = f"event_type IN ({check_values(DeliveryEventType)})"
ACTOR_TYPE_SQL = f"actor_type IN ({check_values(DeliveryEventActor)})"
# 간호사 사건은 간호사 id가, 로봇 사건은 로봇 이름(스냅숏)이, 병상 사건은 병상 이름(스냅숏)이 있다.
# 로봇 id는 로봇을 지우면 NULL이 될 수 있다
ACTOR_CONSISTENCY_SQL = (
    "(actor_type = 'nurse' AND actor_nurse_id IS NOT NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL"
    " AND actor_bedside_name IS NULL)"
    " OR (actor_type = 'robot' AND actor_nurse_id IS NULL AND actor_robot_name IS NOT NULL AND actor_bedside_name IS NULL)"
    " OR (actor_type = 'bedside' AND actor_nurse_id IS NULL AND actor_robot_id IS NULL AND actor_robot_name IS NULL"
    " AND actor_bedside_name IS NOT NULL)"
)


class DeliveryEvent(Base):
    """배송 기록 한 줄. 상태가 실제로 바뀐 요청과 같은 트랜잭션에서 쓰여, 롤백된 요청(409 등)은 남지 않는다."""

    __tablename__ = "delivery_events"
    __table_args__ = (
        CheckConstraint(EVENT_TYPE_SQL, name="ck_delivery_events_event_type"),
        CheckConstraint(ACTOR_TYPE_SQL, name="ck_delivery_events_actor_type"),
        CheckConstraint(ACTOR_CONSISTENCY_SQL, name="ck_delivery_events_actor"),
        # 관리자 기록 화면: 최근 것부터
        Index("ix_delivery_events_occurred_at", "occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(  # 어느 배송
        ForeignKey("deliveries.id", name="fk_delivery_events_delivery_id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # DeliveryEventType
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 일어난 시각 (서비스의 now)
    actor_type: Mapped[str] = mapped_column(String(8), nullable=False)  # DeliveryEventActor
    actor_nurse_id: Mapped[int | None] = mapped_column(  # 간호사 사건의 간호사 (간호사는 지우지 않고 비활성화만)
        ForeignKey("nurses.id", name="fk_delivery_events_actor_nurse_id")
    )
    actor_robot_id: Mapped[int | None] = mapped_column(  # 로봇 사건의 로봇. 로봇을 지우면 NULL
        ForeignKey("robots.id", name="fk_delivery_events_actor_robot_id", ondelete="SET NULL"), index=True
    )
    actor_robot_name: Mapped[str | None] = mapped_column(String(64))  # 로봇 이름 스냅숏 (지워져도 누가 했는지 남김)
    actor_bedside_name: Mapped[str | None] = mapped_column(String(64))  # 병상 이름 스냅숏 (환자 요청·받았습니다, 2026-10-22)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 사건별 내용 (app/services/delivery_events.py)

    delivery: Mapped[Delivery] = relationship()
    actor_nurse: Mapped[Nurse | None] = relationship()

    @property
    def actor_name(self) -> str:
        """누가 했는지 화면에 보일 이름.
        [입력] 없음
        [출력] str: 간호사 이름, 로봇 이름 스냅숏 또는 병상 이름 스냅숏
        """
        if self.actor_type == DeliveryEventActor.NURSE and self.actor_nurse is not None:
            return self.actor_nurse.name
        if self.actor_type == DeliveryEventActor.BEDSIDE:
            return self.actor_bedside_name or ""
        return self.actor_robot_name or ""

    @property
    def destination_location_name(self) -> str:
        """배송 목적지 이름 — 지금 이름 (관리자 기록 화면).
        [입력] 없음
        [출력] str
        """
        return self.delivery.destination_location.name

    @property
    def requester_name(self) -> str:
        """배송을 예약한 쪽 이름 (관리자 기록 화면): 간호사 이름 또는 병상 이름 (2026-10-22, 전 nurse_name).
        [입력] 없음
        [출력] str
        """
        return self.delivery.requester_name

    @property
    def requester_type(self) -> str:
        """배송을 예약한 쪽 종류: nurse | bedside.
        [입력] 없음
        [출력] str
        """
        return self.delivery.requester_type
