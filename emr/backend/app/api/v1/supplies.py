# =============================================================================
# 파일   : app/api/v1/supplies.py
# 역할   : SR-01 비품 CRUD 엔드포인트 (/supplies)
# 작성일 : 2026-10-13
# 구성   :
#   - search/get/create/update/delete  
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import DB, get_current_nurse
from app.schemas.supply import SupplyCreate, SupplyOut, SupplyUpdate
from app.services.supply import SupplyService

router = APIRouter(dependencies=[Depends(get_current_nurse)], responses={401: {"description": "토큰 없음·만료·비활성 간호사"}})  # 전 엔드포인트 로그인 필수
NOT_FOUND_RESPONSE = {404: {"description": "비품 없음 또는 삭제됨"}}


@router.get(
    "", response_model=list[SupplyOut],
    summary="비품 검색",
    description="SR-01 비품 검색. `q`는 이름·코드 부분 일치. soft delete된 행은 제외.",
)
def search_supplies(
    db: DB,
    q: str | None = Query(default=None, description="이름·코드 검색어"),
    limit: int = Query(100, le=500), offset: int = 0,
) -> list[SupplyOut]:
    """
    [입력] q / limit / offset
    [출력] list[SupplyOut]
    """
    return [SupplyOut.model_validate(supply) for supply in SupplyService(db).search(q, limit, offset)]


@router.get("/{supply_id}", response_model=SupplyOut, summary="비품 단건", responses=NOT_FOUND_RESPONSE)
def get_supply(db: DB, supply_id: int) -> SupplyOut:
    """
    [입력] supply_id
    [출력] SupplyOut
    """
    return SupplyOut.model_validate(SupplyService(db).get(supply_id))


@router.post(
    "", response_model=SupplyOut, status_code=status.HTTP_201_CREATED,
    summary="비품 등록",
    description="SR-01 등록. `code` 중복이면 409.",
    responses={409: {"description": "code 중복"}},
)
def create_supply(db: DB, data: SupplyCreate) -> SupplyOut:
    """
    [입력] data
    [출력] SupplyOut
    """
    return SupplyOut.model_validate(SupplyService(db).create(data))


@router.patch(
    "/{supply_id}", response_model=SupplyOut,
    summary="비품 편집",
    description="SR-01 편집(수량 포함). 보낸 필드만 바뀐다. `expiry_date`만 `null`로 지울 수 있다.",
    responses={**NOT_FOUND_RESPONSE, 400: {"description": "name·stock_qty·requestable_by에 null"}},
)
def update_supply(db: DB, supply_id: int, data: SupplyUpdate) -> SupplyOut:
    """
    [입력] supply_id / data: 부분
    [출력] SupplyOut
    """
    return SupplyOut.model_validate(SupplyService(db).update(supply_id, data))


@router.delete(
    "/{supply_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="비품 삭제 (soft)",
    description="is_deleted=true로 표시만 한다.",
    responses=NOT_FOUND_RESPONSE,
)
def delete_supply(db: DB, supply_id: int) -> None:
    """
    [입력] supply_id
    [출력] 없음 (204)
    """
    SupplyService(db).delete(supply_id)
