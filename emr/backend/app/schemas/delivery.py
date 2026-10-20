# =============================================================================
# 파일   : app/schemas/delivery.py
# 역할   : 배송 일정 예약 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - DeliveryItemIn/Out  품목 라인
#   - DeliveryCreate      예약 등록
#   - DeliveryUpdate      예약 변경
#   - DeliveryOut         간호사용 — 단계 시각·맡은 로봇·실패 사유·일회용 수령 마커 포함 (본인 예약만 나간다)
#   - DeliveryReceiptIn   수령 확인 (로봇이 읽은 일회용 마커 번호)
#   - DeliveryProgressIn  도착·실패 보고 (로봇, 2026-10-20)
#   - RobotDeliveryOut / RobotMeOut   로봇용 — 일회용 마커·간호사 정보는 넣지 않는다 (2026-10-20)
# 계약: docs/api_contract_delivery_2026-10-20.md
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models.delivery import RECEIPT_MARKER_ID_MAX
from app.models.enums import DeliveryFailureReason
from app.schemas.common import OrmOut
from app.schemas.location import LocationOut

STATUS_DESCRIPTION = (
    "reserved(예약, 로봇 배정 전) | cancelled(취소) | dispatched(로봇 출발) | arrived(도착, 수령 대기) | "
    "received(수령 — 로봇이 일회용 마커를 읽음) | failed(실패, failure_reason)"
)
FAILURE_REASON_DESCRIPTION = (
    "navigation_failed(주행 실패) | not_received(도착 후 수령 없음) | destination_blocked(금지 장소) | robot_error"
)
SCHEDULED_AT_DESCRIPTION = "배송 예정 시각. 시간대 필수(ISO 8601), 현재보다 미래"


class DeliveryItemIn(BaseModel):
    """예약 품목 한 줄."""

    supply_id: int = Field(description="supplies.id")
    quantity: int = Field(gt=0, description="예약 수량")


class DeliveryCreate(BaseModel):
    """배송 예약 등록 본문 (로그인 필요). 예약자는 토큰의 간호사."""

    destination_location_id: int = Field(description="배송 위치 locations.id")
    scheduled_at: AwareDatetime = Field(description=SCHEDULED_AT_DESCRIPTION, examples=["2026-10-15T09:00:00+09:00"])
    items: list[DeliveryItemIn] = Field(min_length=1, description="같은 supply_id는 한 번만")


class DeliveryUpdate(BaseModel):
    """배송 예약 변경 본문. status=reserved일 때만 가능, 보낸 필드만 바뀐다."""

    destination_location_id: int | None = Field(default=None, description="배송 위치 locations.id")
    scheduled_at: AwareDatetime | None = Field(default=None, description=SCHEDULED_AT_DESCRIPTION)
    items: list[DeliveryItemIn] | None = Field(default=None, min_length=1, description="보내면 품목 전체 교체")


class DeliveryItemOut(OrmOut):
    supply_id: int
    quantity: int


class DeliveryOut(OrmOut):
    """배송 응답 (간호사용). 본인 예약만 나가므로 일회용 수령 마커를 넣는다 — 로봇용 응답(RobotDeliveryOut)에는 없다."""

    id: int
    nurse_id: int = Field(description="예약한 간호사")
    destination_location_id: int
    destination_location: LocationOut = Field(description="배송 위치 상세 (이름·맵 좌표)")
    scheduled_at: datetime
    status: str = Field(description=STATUS_DESCRIPTION)
    items: list[DeliveryItemOut]
    created_at: datetime
    received_at: datetime | None = Field(description="수령 확인 시각. received가 아니면 null")
    received_by_nurse_id: int | None = Field(description="마커로 확인된 간호사 (예약한 간호사)")
    received_by_robot_id: int | None = Field(description="마커를 읽은 로봇. 로봇을 삭제했으면 null")
    assigned_robot_id: int | None = Field(description="맡은 로봇. 배정 전이거나 로봇을 삭제했으면 null")
    assigned_robot_name: str | None = Field(description="맡은 로봇 이름")
    dispatched_at: datetime | None = Field(description="로봇이 맡아 출발한 시각")
    arrived_at: datetime | None = Field(description="목적지 도착 시각")
    failed_at: datetime | None = Field(description="실패 시각")
    failure_reason: str | None = Field(description=FAILURE_REASON_DESCRIPTION)
    receipt_marker_id: int | None = Field(
        description="일회용 수령 마커 (ArUco DICT_4X4_250, 50~249). 도착 때 생긴다 — 로봇 카메라에 보여 준다",
    )
    receipt_deadline_at: datetime | None = Field(description="수령 마감 시각 (arrived일 때만). 지나면 로봇이 실패 처리")


class DeliveryReceiptIn(BaseModel):
    """수령 확인 본문 (로봇). 로봇 카메라가 읽은 마커 번호 — 그 배송의 일회용 마커여야 한다."""

    aruco_marker_id: int = Field(
        ge=0, le=RECEIPT_MARKER_ID_MAX, description="ArUco DICT_4X4_250 마커 번호 (0~249). 일회용 마커는 50~249",
    )


class DeliveryProgressIn(BaseModel):
    """진행 보고 본문 (로봇)."""

    stage: Literal["arrived", "failed"] = Field(description="arrived(도착) | failed(실패)")
    failure_reason: DeliveryFailureReason | None = Field(default=None, description=FAILURE_REASON_DESCRIPTION)

    @model_validator(mode="after")
    def _reason_only_for_failed(self) -> DeliveryProgressIn:
        """failed면 사유 필수, arrived면 사유 없음.
        [입력] 없음
        [출력] self (어긋나면 ValueError → 422)
        """
        if self.stage == "failed" and self.failure_reason is None:
            raise ValueError("failure_reason is required when stage is failed")
        if self.stage == "arrived" and self.failure_reason is not None:
            raise ValueError("failure_reason is only for stage failed")
        return self


class RobotLocationOut(OrmOut):
    """로봇용 장소 (맵 좌표)."""

    id: int
    name: str
    map_id: int | None
    map_x_m: float | None
    map_y_m: float | None
    map_yaw_rad: float | None


class RobotDeliveryItemOut(OrmOut):
    name: str = Field(validation_alias="supply_name", description="비품 이름")
    quantity: int


class RobotDeliveryOut(OrmOut):
    """로봇용 배송. 일회용 마커·간호사 정보는 넣지 않는다(로봇은 읽은 번호를 보내기만 하고 판정은 EMR)."""

    id: int
    status: str = Field(description=STATUS_DESCRIPTION)
    scheduled_at: datetime
    destination: RobotLocationOut = Field(validation_alias="destination_location", description="목적지 (map 프레임 좌표)")
    items: list[RobotDeliveryItemOut]
    dispatched_at: datetime | None
    arrived_at: datetime | None
    receipt_deadline_at: datetime | None = Field(description="arrived일 때 수령 마감 시각. 지나면 failed not_received로 보고")


class RobotBriefOut(OrmOut):
    id: int
    name: str
    robot_type: str


class RobotMeOut(OrmOut):
    """GET /robot/me — 실행기가 시작·재시작할 때."""

    robot: RobotBriefOut
    home_location: RobotLocationOut | None = Field(description="좌표가 있는 복귀 장소. 없으면 배송을 맡을 수 없다")
    active_delivery: RobotDeliveryOut | None = Field(description="이 로봇이 맡고 있는 dispatched·arrived 배송")
    receipt_wait_seconds: int = Field(description="도착 후 수령을 기다리는 시간(초)")
