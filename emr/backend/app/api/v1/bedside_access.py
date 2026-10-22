# =============================================================================
# 파일   : app/api/v1/bedside_access.py
# 역할   : 병상 단말 API (/bedside) — 환자 비품 요청(SR-02)·"받았습니다" 버튼(SR-06). 헤더 X-Bedside-Api-Key (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - me, supplies, requests(POST), deliveries(GET), deliveries/{id}/receipt(POST)
# 응답에는 일회용 마커·간호사 정보·재고 수량을 넣지 않는다. 계약: docs/api_contract_delivery_2026-10-20.md 8장
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import BEDSIDE_RESPONSES, DB, CurrentBedside
from app.schemas.bedside import (
    BedsideDeliveryOut, BedsideMeOut, BedsideRequestIn, BedsideRoomOut, BedsideSupplyOut,
)
from app.services.bedside_request import BedsideRequestService

router = APIRouter(responses=BEDSIDE_RESPONSES)


@router.get("/me", response_model=BedsideMeOut, summary="내 병상",
            description="병상 이름, 병실(맵 좌표가 있는지), 진행 중 배송(있으면 새 요청을 할 수 없다).")
def bedside_me(db: DB, device: CurrentBedside) -> BedsideMeOut:
    """
    [입력] device: 키로 확인된 병상 단말
    [출력] BedsideMeOut
    """
    room = device.location
    active = BedsideRequestService(db).overview(device)
    return BedsideMeOut(
        id=device.id, name=device.name,
        room=BedsideRoomOut(id=room.id, name=room.name, has_position=room.map_id is not None and room.map_x_m is not None),
        active_delivery=BedsideDeliveryOut.model_validate(active) if active else None,
    )


@router.get("/supplies", response_model=list[BedsideSupplyOut], summary="환자가 요청할 수 있는 품목",
            description="requestable_by = patient, 삭제 안 된 것. 재고 수량은 숨기고 있음 여부만.")
def bedside_supplies(db: DB, device: CurrentBedside) -> list[BedsideSupplyOut]:
    """
    [입력] device
    [출력] list[BedsideSupplyOut]
    """
    return [BedsideSupplyOut(id=supply.id, name=supply.name, in_stock=supply.stock_qty > 0)
            for supply in BedsideRequestService(db).list_supplies()]


@router.post(
    "/requests", response_model=BedsideDeliveryOut, status_code=status.HTTP_201_CREATED, summary="비품 요청 (SR-02)",
    description="간호사 승인 없이 바로 배송이 생기고(예약 시각 = 지금, 목적지 = 이 병상의 병실) 로봇이 다음 claim에서 가져간다. "
                "품목당 1–5, 환자가 요청할 수 있는 품목만, 병상당 진행 중 1건.",
    responses={
        400: {"description": "supply_not_found · supply_not_patient_requestable · delivery_item_duplicate"},
        409: {"description": "bedside_request_in_progress · bedside_room_has_no_position · stock_insufficient"},
    },
)
def create_bedside_request(db: DB, device: CurrentBedside, data: BedsideRequestIn) -> BedsideDeliveryOut:
    """
    [입력] device / data: 품목·수량
    [출력] BedsideDeliveryOut: reserved
    """
    return BedsideDeliveryOut.model_validate(BedsideRequestService(db).create_request(device, data.items))


@router.get("/deliveries", response_model=list[BedsideDeliveryOut], summary="이 병상의 최근 배송",
            description="최근 것부터 10건.")
def list_bedside_deliveries(db: DB, device: CurrentBedside) -> list[BedsideDeliveryOut]:
    """
    [입력] device
    [출력] list[BedsideDeliveryOut]
    """
    return [BedsideDeliveryOut.model_validate(delivery) for delivery in BedsideRequestService(db).list_deliveries(device)]


@router.post(
    "/deliveries/{delivery_id}/receipt", response_model=BedsideDeliveryOut, summary='"받았습니다" (SR-06)',
    description="도착한 이 병상의 배송을 수령 처리한다. 로봇은 대기 중 /robot/me로 알아차리고 돌아간다.",
    responses={403: {"description": "다른 병상의 배송 (delivery_not_for_bedside)"}, 404: {"description": "배송 없음"},
               409: {"description": "도착 전이거나 끝난 배송 (delivery_not_arrived)"}},
)
def confirm_bedside_receipt(db: DB, device: CurrentBedside, delivery_id: int) -> BedsideDeliveryOut:
    """
    [입력] device / delivery_id
    [출력] BedsideDeliveryOut: received
    """
    return BedsideDeliveryOut.model_validate(BedsideRequestService(db).confirm_receipt(device, delivery_id))
