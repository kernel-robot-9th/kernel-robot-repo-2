# =============================================================================
# 파일   : app/core/config.py
# 역할   : 환경변수(.env) 기반 전역 설정
# 작성일 : 2026-10-13
# 구성   :
#   - Settings  설정 클래스
#   - settings  모듈 import 시 생성되는 싱글턴
# =============================================================================
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env) 기반 전역 설정. 비밀값은 .env에만 두고 커밋하지 않는다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "dev"                   # dev | staging | prod — prod면 /docs 비활성
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+psycopg://emr:emr@localhost:5432/emr"  # docker-compose 기본값과 동일

    JWT_SECRET: str                    # 기본값 없음 — .env에 없으면 기동 실패
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480      # 간호사 1교대(8h) 동안 재로그인 없음

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    def db_host_for_log(self) -> str:
        """로그용 DB 주소 — 비밀번호 제거.
        [입력] 없음
        [출력] str: 'host:port/db' 부분만
        """
        return self.DATABASE_URL.split("@")[-1]


settings = Settings()  # 전역 싱글턴. 모듈 import 시점에 .env 로드
