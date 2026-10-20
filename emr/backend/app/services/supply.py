# =============================================================================
# 파일   : app/services/supply.py
# 역할   : SR-01 비품 관리
# 작성일 : 2026-10-13
# 구성   :
#   - SupplyService       search/list_low_stock/get/create/update/delete — 재고 부족 상태가 바뀌면 알림 (low_stock.py)
#   - auto_expiry_date()  유효기간 자동값: 오늘부터 6개월~1년 사이 무작위 (2026-10-19 사용자 결정 — 화면에서 고르지 않음)
# =============================================================================
from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.supply import Supply
from app.repositories.supply import SupplyRepository
from app.schemas.supply import SupplyCreate, SupplyUpdate
from app.services.low_stock import LowStockNotifier, is_low_stock

# PATCH에서 null로 지울 수 있는 필드. 나머지는 NOT NULL 컬럼
NULLABLE_UPDATE_FIELDS = frozenset({"expiry_date", "low_stock_threshold_qty"})

# 등록 때 유효기간을 보내지 않으면 오늘부터 이 범위(일) 안에서 무작위로 정한다 — 6개월 ~ 1년
AUTO_EXPIRY_MIN_DAYS = 183
AUTO_EXPIRY_MAX_DAYS = 365


def auto_expiry_date(today: date | None = None) -> date:
    """유효기간 자동값.
    [입력] today: 기준일 (없으면 오늘)
    [출력] date: today + AUTO_EXPIRY_MIN_DAYS ~ AUTO_EXPIRY_MAX_DAYS일 (양끝 포함)
    """
    base_date = today or date.today()
    return base_date + timedelta(days=random.randint(AUTO_EXPIRY_MIN_DAYS, AUTO_EXPIRY_MAX_DAYS))


class SupplyService:
    """SR-01 비품 관리 — 등록·편집(수량)·검색·soft delete."""

    def __init__(self, db: Session) -> None:
        self.repo = SupplyRepository(db)
        self.low_stock_notifier = LowStockNotifier(db)

    def search(self, q: str | None = None, limit: int = 100, offset: int = 0) -> list[Supply]:
        """활성 비품 검색.
        [입력] q: 이름·코드 부분 일치 / limit / offset
        [출력] list[Supply]
        """
        return self.repo.list_active(limit, offset, q)

    def list_low_stock(self) -> list[Supply]:
        """지금 재고가 알림 기준 이하인 비품 (알림창 목록).
        [입력] 없음
        [출력] list[Supply]: 재고가 적은 순
        """
        return self.repo.list_low_stock()

    def get(self, supply_id: int) -> Supply:
        """한 건 조회. 삭제된 비품은 없는 것으로 취급.
        [입력] supply_id
        [출력] Supply (없으면 NotFound)
        """
        supply = self.repo.get(supply_id)
        if supply is None or supply.is_deleted:
            raise NotFound(f"supply {supply_id} not found", code="supply_not_found")
        return supply

    def create(self, data: SupplyCreate) -> Supply:
        """비품 등록. code 중복이면 Conflict. 유효기간을 보내지 않으면 auto_expiry_date()로 채운다.
        [입력] data
        [출력] Supply
        """
        if self.repo.get_by_code(data.code):
            raise Conflict(f"supply code {data.code} already exists", code="supply_code_duplicate")
        fields = data.model_dump()
        if fields["expiry_date"] is None:
            fields["expiry_date"] = auto_expiry_date()
        supply = self.repo.add(Supply(**fields))
        self.low_stock_notifier.notify_if_changed(supply, was_low_stock=False)
        return supply

    def update(self, supply_id: int, data: SupplyUpdate) -> Supply:
        """보낸 필드만 수정. null은 유효기간·알림 기준에만 허용.
        [입력] supply_id / data: exclude_unset 적용
        [출력] Supply (이름·재고·요청 주체에 null이면 BadRequest)
        """
        supply = self.get(supply_id)
        was_low_stock = is_low_stock(supply)
        changes = data.model_dump(exclude_unset=True)
        null_fields = [field for field, value in changes.items() if value is None and field not in NULLABLE_UPDATE_FIELDS]
        if null_fields:
            raise BadRequest(f"{', '.join(null_fields)} cannot be null", code="supply_field_required")
        for field, value in changes.items():
            setattr(supply, field, value)
        self.low_stock_notifier.notify_if_changed(supply, was_low_stock)
        return supply

    def delete(self, supply_id: int) -> None:
        """soft delete.
        [입력] supply_id
        [출력] 없음
        """
        supply = self.get(supply_id)
        was_low_stock = is_low_stock(supply)
        supply.is_deleted = True
        supply.deleted_at = datetime.now(UTC)
        self.low_stock_notifier.notify_if_changed(supply, was_low_stock)  # 부족했던 비품이면 알림창에서 빠지도록
