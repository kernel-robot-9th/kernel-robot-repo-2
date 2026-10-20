# =============================================================================
# 파일   : app/repositories/base.py
# 역할   : 리포지토리 공통 베이스 (get/list/add)
# 작성일 : 2026-10-13
# 구성   :
#   - BaseRepository  제네릭 CRUD
# =============================================================================
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """단일 모델 CRUD의 공통 뼈대. 서브클래스가 `model = X`로 대상 테이블을 지정한다.
    쿼리만 담당하고 업무 규칙(취소 가능 여부 등)은 서비스 몫이다.
    """

    model: type[ModelT]  # 서브클래스에서 지정

    def __init__(self, db: Session) -> None:
        """
        [입력] db: 요청/작업 단위 세션
        [출력] 없음
        """
        self.db = db

    def get(self, record_id: int) -> ModelT | None:
        """PK로 한 건 조회. identity map 히트 시 쿼리 없음.
        [입력] record_id: PK
        [출력] ModelT | None
        """
        return self.db.get(self.model, record_id)

    def list(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        """id 순 페이지 조회.
        [입력] limit / offset
        [출력] list[ModelT]
        """
        statement = select(self.model).order_by(self.model.id).limit(limit).offset(offset)  # type: ignore[attr-defined]
        return list(self.db.scalars(statement))

    def add(self, record: ModelT) -> ModelT:
        """세션에 추가하고 flush해 PK를 확정한다. commit은 호출자 몫.
        [입력] record: 새 ORM 객체
        [출력] ModelT: id가 채워진 같은 객체
        """
        self.db.add(record)
        self.db.flush()
        return record
