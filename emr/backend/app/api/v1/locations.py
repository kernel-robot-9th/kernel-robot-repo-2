# =============================================================================
# 파일   : app/api/v1/locations.py
# 역할   : 장소(배송 위치·맵 좌표) 엔드포인트 (/locations)
# 작성일 : 2026-10-14
# 구성   :
#   - list/get                누구나 (로그인 없이 조회 — 2026-10-15 결정)
#   - create/update/delete    관리자만
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import ADMIN_RESPONSES, DB, get_current_admin
from app.schemas.location import LocationCreate, LocationOut, LocationUpdate
from app.services.location import LocationService

router = APIRouter()
NOT_FOUND_RESPONSE = {404: {"description": "장소 없음"}}
NAME_CONFLICT_RESPONSE = {409: {"description": "name 중복"}}


@router.get("", response_model=list[LocationOut], summary="장소 목록", description="이름 순. 좌표가 null이면 좌표 미등록.")
def list_locations(db: DB, limit: int = Query(100, le=500), offset: int = 0) -> list[LocationOut]:
    """
    [입력] limit / offset
    [출력] list[LocationOut]
    """
    return [LocationOut.model_validate(location) for location in LocationService(db).list(limit, offset)]


@router.get("/{location_id}", response_model=LocationOut, summary="장소 단건", responses=NOT_FOUND_RESPONSE)
def get_location(db: DB, location_id: int) -> LocationOut:
    """
    [입력] location_id
    [출력] LocationOut
    """
    return LocationOut.model_validate(LocationService(db).get(location_id))


@router.post(
    "", response_model=LocationOut, status_code=status.HTTP_201_CREATED,
    summary="장소 등록 (관리자)",
    description="좌표(`map_x_m`·`map_y_m`·`map_yaw_rad`)는 세 값을 함께 보내거나 함께 생략한다.",
    responses={**ADMIN_RESPONSES, **NAME_CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def create_location(db: DB, data: LocationCreate) -> LocationOut:
    """
    [입력] data
    [출력] LocationOut
    """
    return LocationOut.model_validate(LocationService(db).create(data))


@router.patch(
    "/{location_id}", response_model=LocationOut,
    summary="장소 편집 (관리자)",
    description="보낸 필드만 바뀐다. 좌표는 세 값을 함께 보낸다.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, **NAME_CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def update_location(db: DB, location_id: int, data: LocationUpdate) -> LocationOut:
    """
    [입력] location_id / data: 부분
    [출력] LocationOut
    """
    return LocationOut.model_validate(LocationService(db).update(location_id, data))


@router.delete(
    "/{location_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="장소 삭제 (관리자)",
    description="행을 지운다. 배송 예약이 참조하는 장소는 409.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, 409: {"description": "배송 예약이 참조 중"}},
    dependencies=[Depends(get_current_admin)],
)
def delete_location(db: DB, location_id: int) -> None:
    """
    [입력] location_id
    [출력] 없음 (204)
    """
    LocationService(db).delete(location_id)
