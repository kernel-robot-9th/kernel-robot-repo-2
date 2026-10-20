# =============================================================================
# 파일   : app/schemas/supply.py
# 역할   : SR-01 비품 CRUD 스키마
# 작성일 : 2026-10-13
# 구성   :
#   - SupplyCreate  
#   - SupplyUpdate  PATCH 부분 수정
#   - SupplyOut     
# =============================================================================
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.models.enums import RequestableBy, SupplyCategory
from app.schemas.common import OrmOut

LOW_STOCK_THRESHOLD_DESCRIPTION = "재고 부족 알림 기준. 재고가 이 수량 이하가 되면 알린다. null=알림 안 함"


class SupplyCreate(BaseModel):
    """SR-01 비품 등록 본문."""

    code: str = Field(min_length=1, max_length=32, description="비품 고유번호 (UNIQUE)", examples=["MED-A"])
    name: str = Field(min_length=1, max_length=128, description="비품 이름", examples=["A 약품"])
    category: SupplyCategory = Field(description="medication | supply")
    requestable_by: RequestableBy = Field(description="nurse | patient — 누가 요청할 수 있는가")
    stock_qty: int = Field(default=0, ge=0, description="초기 재고")
    low_stock_threshold_qty: int | None = Field(default=None, ge=0, description=LOW_STOCK_THRESHOLD_DESCRIPTION)
    expiry_date: date | None = Field(default=None, description="유효기간. 생략(또는 null)하면 오늘부터 6개월~1년 사이로 서버가 정한다")


class SupplyUpdate(BaseModel):
    """SR-01 비품 편집 본문. 보낸 필드만 바뀐다(PATCH). code·category는 변경 불가.
    null은 expiry_date·low_stock_threshold_qty만 허용(나머지는 400).
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    stock_qty: int | None = Field(default=None, ge=0, description="SR-01 수량 편집 (입고·실사 보정)")
    low_stock_threshold_qty: int | None = Field(default=None, ge=0, description=LOW_STOCK_THRESHOLD_DESCRIPTION)
    expiry_date: date | None = None
    requestable_by: RequestableBy | None = None


class SupplyOut(OrmOut):
    """비품 응답. is_deleted=true 행은 목록·단건 조회에서 제외된다."""

    id: int
    code: str
    name: str
    category: str
    requestable_by: str
    stock_qty: int = Field(description="현재 재고")
    low_stock_threshold_qty: int | None = Field(description=LOW_STOCK_THRESHOLD_DESCRIPTION)
    expiry_date: date | None
    is_deleted: bool
