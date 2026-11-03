# =============================================================================
# 파일   : app/schemas/bedside.py
# 역할   : 병상 단말(환자 요청) 스키마 — 관리자 등록과 병상 단말 API (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - BedsideDeviceCreate / BedsideDeviceUpdate / BedsideDeviceOut / BedsideApiKeyOut   관리자
#   - BedsideRoomOut, BedsideSupplyOut, BedsideRequestItemIn, BedsideRequestIn,
#     BedsideDeliveryItemOut, BedsideDeliveryOut, BedsideMeOut                            병상 단말 (X-Bedside-Api-Key)
# 병상 단말 응답에는 일회용 마커·간호사 정보·재고 수량을 넣지 않는다.
# =============================================================================
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import OrmOut

MAX_REQUEST_QUANTITY = 5   # 환자 요청 한 품목 최대 수량 (사용자 결정 2026-10-22: 남용 방지)


# ---- 관리자 ----------------------------------------------------------------------

class BedsideDeviceCreate(BaseModel):
    """병상 단말 등록."""
    name: str = Field(min_length=1, max_length=64, description="병상 이름 (UNIQUE)", examples=["301호-1"])
    location_id: int = Field(description="병실 locations.id — 요청한 배송의 목적지. 맵 좌표가 있어야 로봇이 간다")


class BedsideDeviceUpdate(BaseModel):
    """병상 단말 수정 (보낸 필드만, null은 무시)."""
    name: str | None = Field(default=None, min_length=1, max_length=64)
    location_id: int | None = Field(default=None, description="병실 locations.id")


class BedsideDeviceOut(OrmOut):
    """병상 단말 응답 (키 해시는 내보내지 않는다)."""
    id: int
    name: str
    location_id: int
    has_api_key: bool = Field(description="병상 단말 API(/bedside/...)용 키가 발급되어 있는지")
    api_key_issued_at: datetime | None
    updated_at: datetime


class BedsideApiKeyOut(BaseModel):
    """병상 단말 키 발급 응답. api_key는 다시 조회할 수 없다 — 단말에 바로 넣는다."""
    bedside_device_id: int
    api_key: str = Field(description="평문 키. 요청 헤더 X-Bedside-Api-Key에 넣는다. 서버는 해시만 보관")
    issued_at: datetime


# ---- 병상 단말 -------------------------------------------------------------------

class BedsideRoomOut(OrmOut):
    """병실."""
    id: int
    name: str
    has_position: bool = Field(description="맵 좌표가 있는지 — 없으면 요청할 수 없다(로봇이 갈 수 없음)")


class BedsideSupplyOut(OrmOut):
    """환자가 요청할 수 있는 품목 (requestable_by = patient). 재고 수량은 숨긴다."""
    id: int
    name: str
    in_stock: bool = Field(description="재고가 있는지")


class BedsideRequestItemIn(BaseModel):
    """요청 품목 한 줄."""
    supply_id: int
    quantity: int = Field(ge=1, le=MAX_REQUEST_QUANTITY, description=f"1–{MAX_REQUEST_QUANTITY}")


class BedsideRequestIn(BaseModel):
    """환자 비품 요청 (SR-02). 간호사 승인 없이 바로 배송이 생긴다."""
    items: list[BedsideRequestItemIn] = Field(min_length=1, max_length=10)


class BedsideDeliveryItemOut(OrmOut):
    """배송 품목 (이름·수량)."""
    name: str = Field(validation_alias="supply_name")
    quantity: int


class BedsideDeliveryOut(OrmOut):
    """병상 화면용 배송 — 마커·간호사 정보 없음."""
    id: int
    status: str = Field(description="reserved(요청됨) | dispatched(출발) | arrived(도착) | received(받음) | failed(실패)")
    created_at: datetime
    items: list[BedsideDeliveryItemOut]
    assigned_robot_name: str | None
    dispatched_at: datetime | None
    arrived_at: datetime | None
    received_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    receipt_deadline_at: datetime | None = Field(description="도착 후 '받았습니다'를 눌러야 하는 마감 (arrived일 때만)")


class BedsideMeOut(BaseModel):
    """GET /bedside/me."""
    id: int
    name: str
    room: BedsideRoomOut
    active_delivery: BedsideDeliveryOut | None = Field(description="진행 중(요청됨·출발·도착) 배송. 있으면 새 요청을 할 수 없다")
