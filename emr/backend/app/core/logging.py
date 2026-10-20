# =============================================================================
# 파일   : app/core/logging.py
# 역할   : structlog JSON 로깅 설정
# 작성일 : 2026-10-13
# 구성   :
#   - configure_logging()  기동 시 1회 호출
# =============================================================================
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """structlog를 JSON 라인 출력으로 설정한다. 기동 시 한 번 호출.
    [입력] level: 로그 레벨 문자열 (DEBUG/INFO/WARNING/ERROR)
    [출력] 없음
    """
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )
