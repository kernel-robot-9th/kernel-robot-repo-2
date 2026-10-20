# =============================================================================
# 파일   : app/models/base.py
# 역할   : DeclarativeBase와 타임스탬프 믹스인
# 작성일 : 2026-10-13
# 구성   :
#   - Base            모든 모델의 베이스
#   - TimestampMixin  created_at/updated_at
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스. Base.metadata가 Alembic autogenerate의 비교 대상이다."""


class TimestampMixin:
    """created_at / updated_at 두 컬럼을 붙여주는 믹스인.
    DB 서버 시각(now())을 쓰므로 프로세스 간 시계 차이가 없다.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
