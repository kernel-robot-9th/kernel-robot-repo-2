# =============================================================================
# 파일   : app/core/database.py
# 역할   : SQLAlchemy 엔진·세션 팩토리
# 작성일 : 2026-10-13
# 구성   :
#   - engine        프로세스당 커넥션 풀
#   - SessionLocal  세션 팩토리 (expire_on_commit=False)
#   - get_db()      FastAPI Depends용 요청 단위 세션
# =============================================================================
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# 프로세스당 하나.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # 끊긴 커넥션을 체크아웃 전에 감지해 재연결
    pool_size=5,
    max_overflow=5,
    echo=settings.ENV == "dev" and settings.LOG_LEVEL == "DEBUG",
)

# expire_on_commit=False: commit 후에도 ORM 객체 속성 접근 시 재조회하지 않음
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI Depends용 요청 단위 세션. 정상 종료면 commit, 예외면 rollback.
    [입력] 없음
    [출력] Session: 요청 수명 동안 유효한 세션 (제너레이터)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
