# =============================================================================
# 파일   : app/api/v1/deliveries.py
# 역할   : 배송 일정 예약 엔드포인트 (/deliveries) — 전부 로그인 필요
# 작성일 : 2026-10-14
# 구성   :
#   - create/list/get/update/cancel  
#   - events  배송 한 건의 기록 — 예약 간호사 본인·관리자 (2026-10-21, 로드맵 4단계)
#   - receipt "받았습니다" 버튼 수령 — 도착한 본인 배송 (2026-10-22, 마커 대신)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.core.deps import DB, CurrentNurse
from app.models.enums import DeliveryStatus
from app.schemas.delivery import (
    DeliveryCreate, DeliveryOut, DeliveryUpdate,
)
from app.schemas.delivery_event import DeliveryEventOut
from app.services.delivery import DeliveryService
from app.services.delivery_events import DeliveryEventService

router = APIRouter()
UNAUTHORIZED_RESPONSE = {401: {"description": "토큰 없음·만료"}}
OWNERSHIP_RESPONSES = {**UNAUTHORIZED_RESPONSE, 403: {"description": "다른 간호사의 예약"}, 404: {"description": "예약 없음"}}
BAD_REQUEST_RESPONSE = {400: {"description": "과거 시각, 없는 장소, 없는 비품, 중복 품목"}}
NOT_RESERVED_RESPONSE = {409: {"description": "reserved 상태가 아님 (이미 취소·수령됨)"}}


@router.post(
    "", response_model=DeliveryOut, status_code=status.HTTP_201_CREATED,
    summary="배송 예약 등록",
    description="언제(`scheduled_at`)·어디로(`destination_location_id`)·무엇을(`items`) 보낼지 예약한다. 예약자는 토큰의 간호사.",
    responses={**UNAUTHORIZED_RESPONSE, **BAD_REQUEST_RESPONSE},
)
def create_delivery(db: DB, nurse: CurrentNurse, data: DeliveryCreate) -> DeliveryOut:
    """
    [입력] data / nurse: 토큰에서 복원
    [출력] DeliveryOut
    """
    return DeliveryOut.model_validate(DeliveryService(db).create(data, nurse.id))


@router.get(
    "", response_model=list[DeliveryOut],
    summary="내 배송 예약 목록",
    description="토큰의 간호사가 등록한 예약. 배송 예정 시각이 빠른 순.",
    responses=UNAUTHORIZED_RESPONSE,
)
def list_my_deliveries(
    db: DB, nurse: CurrentNurse,
    status_filter: DeliveryStatus | None = Query(default=None, alias="status", description="있으면 그 상태만"),
    limit: int = Query(100, le=500), offset: int = 0,
) -> list[DeliveryOut]:
    """
    [입력] nurse / status / limit / offset
    [출력] list[DeliveryOut]
    """
    deliveries = DeliveryService(db).list_for_nurse(nurse.id, status_filter, limit, offset)
    return [DeliveryOut.model_validate(delivery) for delivery in deliveries]


@router.get(
    "/{delivery_id}", response_model=DeliveryOut,
    summary="배송 예약 단건", responses=OWNERSHIP_RESPONSES,
)
def get_delivery(db: DB, nurse: CurrentNurse, delivery_id: int) -> DeliveryOut:
    """
    [입력] delivery_id / nurse
    [출력] DeliveryOut
    """
    return DeliveryOut.model_validate(DeliveryService(db).get(delivery_id, nurse.id))


@router.get(
    "/{delivery_id}/events", response_model=list[DeliveryEventOut],
    summary="배송 기록 (한 건)",
    description="예약·변경·취소·출발·도착·수령·실패를 일어난 순서로. 예약한 간호사 본인과 관리자만. "
                "2026-10-21 이전에 만든 배송은 기록이 없다.",
    responses={**UNAUTHORIZED_RESPONSE, 403: {"description": "다른 간호사의 예약 (관리자는 가능)"},
               404: {"description": "예약 없음"}},
)
def list_delivery_history(db: DB, nurse: CurrentNurse, delivery_id: int) -> list[DeliveryEventOut]:
    """
    [입력] delivery_id / nurse
    [출력] list[DeliveryEventOut]
    """
    return [DeliveryEventOut.model_validate(event) for event in DeliveryEventService(db).history(delivery_id, nurse)]


@router.patch(
    "/{delivery_id}", response_model=DeliveryOut,
    summary="배송 예약 변경",
    description="reserved 상태만. 보낸 필드만 바뀌고, `items`를 보내면 품목 전체 교체.",
    responses={**OWNERSHIP_RESPONSES, **BAD_REQUEST_RESPONSE, **NOT_RESERVED_RESPONSE},
)
def update_delivery(
    db: DB, nurse: CurrentNurse, delivery_id: int, data: DeliveryUpdate,
) -> DeliveryOut:
    """
    [입력] delivery_id / data: 부분 / nurse
    [출력] DeliveryOut
    """
    return DeliveryOut.model_validate(DeliveryService(db).update(delivery_id, data, nurse.id))


@router.post(
    "/{delivery_id}/cancel", response_model=DeliveryOut,
    summary="배송 예약 취소",
    description="reserved → cancelled. 행은 남는다.",
    responses={**OWNERSHIP_RESPONSES, **NOT_RESERVED_RESPONSE},
)
def cancel_delivery(db: DB, nurse: CurrentNurse, delivery_id: int) -> DeliveryOut:
    """
    [입력] delivery_id / nurse
    [출력] DeliveryOut: cancelled
    """
    return DeliveryOut.model_validate(DeliveryService(db).cancel(delivery_id, nurse.id))


@router.post(
    "/{delivery_id}/receipt", response_model=DeliveryOut,
    summary='"받았습니다" (수령 확인)',
    description="arrived → received. 도착한 본인 배송만. 로봇(배송 실행기)은 대기 중 /robot/me로 알아차리고 돌아간다. "
                "NURSE_RECEIPT_METHOD=marker로 마커를 되살리면 409 delivery_receipt_by_marker (2026-10-22)",
    responses={**OWNERSHIP_RESPONSES, 409: {"description": "도착 전이거나 끝난 배송 (delivery_not_arrived) · 마커 방식 (delivery_receipt_by_marker)"}},
)
def confirm_delivery_receipt(db: DB, nurse: CurrentNurse, delivery_id: int) -> DeliveryOut:
    """
    [입력] delivery_id / nurse
    [출력] DeliveryOut: received
    """
    return DeliveryOut.model_validate(DeliveryService(db).confirm_receipt(delivery_id, nurse.id))
