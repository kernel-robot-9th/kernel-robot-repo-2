# =============================================================================
# 파일   : app/schemas/delivery_event.py
# 역할   : 배송 기록 응답 (로드맵 4단계)
# 작성일 : 2026-10-21
# 구성   :
#   - DeliveryEventOut       배송 한 건의 기록 (예약 간호사 본인·관리자)
#   - AdminDeliveryEventOut  관리자 기록 화면 — 목적지·예약 간호사 이름 추가
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import OrmOut

EVENT_TYPE_DESCRIPTION = "reserved | updated | cancelled (간호사) · dispatched | arrived | received | failed (로봇)"
DETAILS_DESCRIPTION = (
    "사건별 내용. reserved: scheduled_at·destination{id,name}·items[{supply_id,name,quantity}] / "
    "updated: 바뀐 것만 {필드: {from, to}} / failed: failure_reason / 그 밖: null. 이름은 당시 값. 일회용 마커 번호는 없음"
)


class DeliveryEventOut(OrmOut):
    """배송 기록 한 줄."""
    id: int
    delivery_id: int
    event_type: str = Field(description=EVENT_TYPE_DESCRIPTION)
    occurred_at: datetime
    actor_type: str = Field(description="nurse | robot | bedside(병상 단말, 2026-10-22)")
    actor_name: str = Field(description="간호사 이름 또는 로봇 이름(당시 이름, 로봇을 지워도 남음)")
    actor_robot_id: int | None = Field(description="로봇 사건의 로봇 id. 로봇을 지웠으면 null")
    details: dict[str, Any] | None = Field(description=DETAILS_DESCRIPTION)


class AdminDeliveryEventOut(DeliveryEventOut):
    """관리자 기록 화면 한 줄."""
    destination_location_name: str = Field(description="배송 목적지 (지금 이름)")
    requester_type: str = Field(description="배송을 예약한 쪽: nurse | bedside")
    requester_name: str = Field(description="배송을 예약한 간호사 이름 또는 병상 이름 (2026-10-22, 전 nurse_name)")
