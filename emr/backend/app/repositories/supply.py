# =============================================================================
# 파일   : app/repositories/supply.py
# 역할   : 비품 조회·검색
# 작성일 : 2026-10-13
# 구성   :
#   - SupplyRepository  list_active, list_low_stock, get_by_code, lock_many(재고 변경 전 행 잠금)
# =============================================================================
from __future__ import annotations

from sqlalchemy import select

from app.models.supply import Supply
from app.repositories.base import BaseRepository


class SupplyRepository(BaseRepository[Supply]):
    """supplies 조회."""

    model = Supply

    def list_active(self, limit: int = 100, offset: int = 0, q: str | None = None) -> list[Supply]:
        """삭제되지 않은 비품 목록. q가 있으면 이름·코드 부분 일치 (SR-01 검색).
        [입력] limit / offset / q: 검색어
        [출력] list[Supply]: code 순
        """
        statement = select(Supply).where(Supply.is_deleted.is_(False))
        if q:
            statement = statement.where(Supply.name.ilike(f"%{q}%") | Supply.code.ilike(f"%{q}%"))
        return list(self.db.scalars(statement.order_by(Supply.code).limit(limit).offset(offset)))

    def list_low_stock(self) -> list[Supply]:
        """재고가 알림 기준 이하인 활성 비품. 기준이 NULL이면 제외. 조건은 services/low_stock.py의 is_low_stock과 같다.
        [입력] 없음
        [출력] list[Supply]: 재고가 적은 순, 같으면 code 순
        """
        statement = select(Supply).where(
            Supply.is_deleted.is_(False),
            Supply.low_stock_threshold_qty.is_not(None),
            Supply.stock_qty <= Supply.low_stock_threshold_qty,
        )
        return list(self.db.scalars(statement.order_by(Supply.stock_qty, Supply.code)))

    def get_by_code(self, code: str) -> Supply | None:
        """고유번호로 조회 (등록 시 중복 검사).
        [입력] code
        [출력] Supply | None
        """
        return self.db.scalar(select(Supply).where(Supply.code == code))

    def lock_many(self, supply_ids: list[int]) -> dict[int, Supply]:
        """재고를 바꾸기 전에 비품 행을 잠근다 (SELECT ... FOR UPDATE). id 순으로 잠가 교착을 피한다.
        [입력] supply_ids
        [출력] dict[int, Supply]: supply_id → Supply (트랜잭션이 끝날 때까지 다른 요청은 대기)
        """
        statement = select(Supply).where(Supply.id.in_(supply_ids)).order_by(Supply.id).with_for_update()
        return {supply.id: supply for supply in self.db.scalars(statement)}
