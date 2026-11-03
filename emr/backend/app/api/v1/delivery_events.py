# =============================================================================
# 파일   : app/api/v1/delivery_events.py
# 역할   : 배송 기록 — 관리자 기록 화면 (/delivery-events) (로드맵 4단계)
# 작성일 : 2026-10-21
# 구성   :
#   - list_delivery_events  거르기·최근 순. 배송 한 건 기록은 GET /deliveries/{id}/events (예약 간호사 본인도)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.core.deps import ADMIN_RESPONSES, DB, get_current_admin
from app.models.enums import DeliveryEventType
from app.schemas.delivery_event import AdminDeliveryEventOut
from app.services.delivery_events import DeliveryEventService

router = APIRouter()


@router.get(
    "", response_model=list[AdminDeliveryEventOut],
    summary="배송 기록 목록 (관리자)",
    description="간호사 예약·변경·취소와 로봇 출발·도착·수령·실패 기록. 최근 것부터. "
                "`nurse_id`는 그 간호사가 **예약한** 배송의 기록, `robot_id`는 그 로봇이 한 일. "
                "`since`는 포함, `until`은 미포함.",
    dependencies=[Depends(get_current_admin)],
    responses=ADMIN_RESPONSES,
)
def list_delivery_events(
    db: DB,
    event_type: DeliveryEventType | None = Query(default=None, description="있으면 그 사건만"),
    robot_id: int | None = Query(default=None, description="그 로봇이 한 일"),
    nurse_id: int | None = Query(default=None, description="그 간호사가 예약한 배송"),
    delivery_id: int | None = Query(default=None, description="그 배송"),
    since: AwareDatetime | None = Query(default=None, description="이 시각부터 (포함, 시간대 필수)"),
    until: AwareDatetime | None = Query(default=None, description="이 시각 전까지 (미포함, 시간대 필수)"),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> list[AdminDeliveryEventOut]:
    """
    [입력] 거르기 조건 / limit / offset
    [출력] list[AdminDeliveryEventOut]
    """
    events = DeliveryEventService(db).list_for_admin(
        event_type, robot_id, nurse_id, delivery_id, since, until, limit, offset,
    )
    return [AdminDeliveryEventOut.model_validate(event) for event in events]
