# =============================================================================
# 파일   : app/api/v1/bedside_devices.py
# 역할   : 병상 단말 등록·수정·삭제·키 발급 (/bedside-devices) — 관리자만 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - list/get/create/update/delete
#   - issue/revoke api key   병상 단말 API(/bedside/...)를 부를 단말 키 (로봇 키와 같은 방식)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import ADMIN_RESPONSES, DB, get_current_admin
from app.schemas.bedside import BedsideApiKeyOut, BedsideDeviceCreate, BedsideDeviceOut, BedsideDeviceUpdate
from app.services.bedside_device import BedsideDeviceService

router = APIRouter(dependencies=[Depends(get_current_admin)], responses=ADMIN_RESPONSES)
NOT_FOUND_RESPONSE = {404: {"description": "병상 단말 없음 (bedside_device_not_found)"}}
BAD_REQUEST_RESPONSE = {400: {"description": "병실 장소 없음 (location_not_found)"}}
NAME_CONFLICT_RESPONSE = {409: {"description": "이름 중복 (bedside_name_duplicate)"}}


@router.get("", response_model=list[BedsideDeviceOut], summary="병상 단말 목록 (관리자)", description="이름 순.")
def list_bedside_devices(db: DB, limit: int = Query(100, le=500), offset: int = 0) -> list[BedsideDeviceOut]:
    """
    [입력] limit / offset
    [출력] list[BedsideDeviceOut]
    """
    return [BedsideDeviceOut.model_validate(device) for device in BedsideDeviceService(db).list(limit, offset)]


@router.post(
    "", response_model=BedsideDeviceOut, status_code=status.HTTP_201_CREATED, summary="병상 단말 등록 (관리자)",
    description="병상 이름과 병실(장소)을 등록한다. 키는 따로 발급한다.",
    responses={**BAD_REQUEST_RESPONSE, **NAME_CONFLICT_RESPONSE},
)
def create_bedside_device(db: DB, data: BedsideDeviceCreate) -> BedsideDeviceOut:
    """
    [입력] data
    [출력] BedsideDeviceOut
    """
    return BedsideDeviceOut.model_validate(BedsideDeviceService(db).create(data))


@router.patch(
    "/{device_id}", response_model=BedsideDeviceOut, summary="병상 단말 수정 (관리자)",
    responses={**NOT_FOUND_RESPONSE, **BAD_REQUEST_RESPONSE, **NAME_CONFLICT_RESPONSE},
)
def update_bedside_device(db: DB, device_id: int, data: BedsideDeviceUpdate) -> BedsideDeviceOut:
    """
    [입력] device_id / data
    [출력] BedsideDeviceOut
    """
    return BedsideDeviceOut.model_validate(BedsideDeviceService(db).update(device_id, data))


@router.delete(
    "/{device_id}", status_code=status.HTTP_204_NO_CONTENT, summary="병상 단말 삭제 (관리자)",
    description="진행 중(요청됨·출발·도착) 배송이 있으면 409 bedside_has_active_delivery. 지난 배송의 병상 이름은 남는다.",
    responses={**NOT_FOUND_RESPONSE, 409: {"description": "진행 중 배송 있음 (bedside_has_active_delivery)"}},
)
def delete_bedside_device(db: DB, device_id: int) -> None:
    """
    [입력] device_id
    [출력] 없음
    """
    BedsideDeviceService(db).delete(device_id)


@router.post(
    "/{device_id}/api-key", response_model=BedsideApiKeyOut, status_code=status.HTTP_201_CREATED,
    summary="병상 단말 키 발급·재발급 (관리자)",
    description="평문 키는 이 응답에서만 한 번 나온다. 재발급하면 이전 키는 바로 쓸 수 없다.", responses=NOT_FOUND_RESPONSE,
)
def issue_bedside_api_key(db: DB, device_id: int) -> BedsideApiKeyOut:
    """
    [입력] device_id
    [출력] BedsideApiKeyOut
    """
    device, raw_api_key = BedsideDeviceService(db).issue_api_key(device_id)
    return BedsideApiKeyOut(bedside_device_id=device.id, api_key=raw_api_key, issued_at=device.api_key_issued_at)


@router.delete(
    "/{device_id}/api-key", status_code=status.HTTP_204_NO_CONTENT, summary="병상 단말 키 폐기 (관리자)",
    responses=NOT_FOUND_RESPONSE,
)
def revoke_bedside_api_key(db: DB, device_id: int) -> None:
    """
    [입력] device_id
    [출력] 없음
    """
    BedsideDeviceService(db).revoke_api_key(device_id)
