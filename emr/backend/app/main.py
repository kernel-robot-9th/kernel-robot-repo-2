# =============================================================================
# 파일   : app/main.py
# 역할   : FastAPI 진입점 — 앱 조립·예외 핸들러·라이프사이클
# 작성일 : 2026-10-13
# 구성   :
#   - lifespan()    기동 시 DB 검증·알림 LISTEN 시작·FMS 주문 보내기 주기 작업(FMS_BASE_URL)·OMX 적재 주기 작업(FMS_OMX_ENABLED), 종료 시 정리
#   - create_app()  앱 팩토리
#   - app           uvicorn app.main:app 대상
# =============================================================================
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import api_router, api_v2_router
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import DomainError
from app.core.notification_hub import notification_hub
from app.core.logging import configure_logging
from app.services.fms_omx import run_omx_round
from app.services.fms_order import run_send_round

configure_logging(settings.LOG_LEVEL)
log = structlog.get_logger(__name__)


async def _send_to_fms_forever() -> None:
    """신청 시각이 된 배송을 FMS로 보내는 회차를 계속 돈다 (2026-10-27). DB·HTTP가 동기라 스레드에서.
    [입력] 없음
    [출력] 없음 (lifespan이 취소할 때까지)
    """
    while True:
        await asyncio.to_thread(run_send_round)
        await asyncio.sleep(settings.FMS_SEND_INTERVAL_SECONDS)


async def _run_omx_forever() -> None:
    """FMS 묶음을 실제 OMX로 싣는 회차를 계속 돈다 (2026-10-27, 2단계). 로봇팔이 움직인다 — FMS_OMX_ENABLED일 때만.
    [입력] 없음
    [출력] 없음 (lifespan이 취소할 때까지)
    """
    while True:
        await asyncio.to_thread(run_omx_round)
        await asyncio.sleep(settings.FMS_OMX_ROUND_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """기동 시 DB 연결 검증(SELECT 1)과 알림 LISTEN 시작, 종료 시 정리. DB 안 붙으면 기동 실패.
    [입력] _: FastAPI 앱 (미사용)
    [출력] 없음 (컨텍스트 매니저)
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    notification_hub.start()
    log.info("startup", env=settings.ENV, db=settings.db_host_for_log())
    background_tasks: list[asyncio.Task] = []
    if settings.FMS_BASE_URL:
        background_tasks.append(asyncio.create_task(_send_to_fms_forever(), name="fms-send"))
        log.info("fms_send_enabled", fms_base_url=settings.FMS_BASE_URL, interval_seconds=settings.FMS_SEND_INTERVAL_SECONDS,
                 robot_map=settings.FMS_ROBOT_MAP)
        if settings.FMS_OMX_ENABLED:
            background_tasks.append(asyncio.create_task(_run_omx_forever(), name="fms-omx"))
            log.warning("fms_omx_enabled", omx_base_url=settings.OMX_BASE_URL,
                        detail="FMS batches are loaded by the real OMX arm — the arm moves (FMS_OMX_ENABLED=1)")
    if settings.AUTH_DISABLED:
        log.warning("auth_disabled", acting_as=settings.AUTH_DISABLED_AS,
                    detail="JWT login is OFF — anyone on the network acts as this admin (AUTH_DISABLED=1)")
    if settings.ROBOT_KEY_DISABLED:
        log.warning("robot_key_disabled", acting_as_robot_id=settings.ROBOT_KEY_DISABLED_AS,
                    detail="robot API key check is OFF — calls without a key act as this robot (ROBOT_KEY_DISABLED=1)")
    yield
    for task in background_tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    await notification_hub.stop()
    engine.dispose()
    log.info("shutdown")


def create_app() -> FastAPI:
    """FastAPI 앱 팩토리. 미들웨어·예외 핸들러·라우터를 조립한다.
    [입력] 없음
    [출력] FastAPI: 구성 완료된 앱 인스턴스
    """
    app = FastAPI(
        title="EMR Supply API",
        version="0.1.0",
        description=(
            "비품 관리 백엔드.\n\n"
            "- `POST /api/v1/auth/login`으로 Bearer 토큰 발급. 비품·간호사·배송 API는 토큰 필수, 맵·장소·로봇 API는 아직 토큰 없이 호출 가능\n"
            "- `/robot/...`은 로봇 전용: 관리자가 발급한 로봇별 키를 `X-Robot-Api-Key` 헤더로 보낸다\n"
            "- 오류 응답은 `{\"code\": str, \"detail\": str}` 형식"
        ),
        openapi_tags=[
            {"name": "auth", "description": "간호사 로그인·토큰 발급"},
            {"name": "supplies", "description": "SR-01 비품 관리 — 등록·편집(수량)·검색·soft delete"},
            {"name": "nurses", "description": "간호사 관리 — 등록·편집·조회·비활성화"},
            {"name": "maps", "description": "맵 관리 — 맵 yaml 파일 이름과 resolution·origin"},
            {"name": "locations", "description": "장소 관리 — 배송 위치, 맵 좌표(미터·라디안), 소속 맵"},
            {"name": "deliveries", "description": "배송 일정 예약 — 간호사 본인 예약 등록·조회·변경·취소 (로그인 필요)"},
            {"name": "delivery-events", "description": "배송 기록 — 예약·변경·취소·출발·도착·수령·실패 (관리자 목록, 2026-10-21)"},
            {"name": "robots", "description": "로봇 관리 — 등록·조회·수정·삭제, 종류(매니퓰레이터·AMR)·이름·상태"},
            {"name": "notifications", "description": "알림 — 재고 부족 목록과 실시간 스트림(SSE) (로그인 필요)"},
            {"name": "bedside-devices", "description": "병상 단말 관리 — 등록·병실·키 발급 (관리자, 2026-10-22)"},
            {"name": "bedside-access", "description": "병상 단말 전용 — 환자 비품 요청·\"받았습니다\". `X-Bedside-Api-Key`로 호출"},
            {"name": "robot-access", "description": "로봇 전용 — 배송 수령 확인. 간호사 토큰이 아니라 `X-Robot-Api-Key`(로봇별 키)로 호출"},
            {"name": "fms", "description": "팀원 FMS → EMR 웹훅 — 로봇 상태·이벤트 (인증 없음, FMS API v1 연동 1단계, 2026-10-27)"},
        ],
        docs_url="/docs" if settings.ENV != "prod" else None,  # 운영에선 OpenAPI 비노출
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_: Request, error: DomainError) -> JSONResponse:
        """DomainError → {"code","detail"} JSON. 서비스 레이어가 HTTP를 모르게 하는 유일한 변환점.
        [입력] _: 요청 (미사용) / error: 서비스가 던진 도메인 예외
        [출력] JSONResponse: error.status_code 와 code/detail 본문
        """
        return JSONResponse(status_code=error.status_code, content={"code": error.code, "detail": error.detail})

    @app.get("/health", tags=["ops"], include_in_schema=False)
    def health() -> dict[str, str]:
        """로드밸런서·헬스체크용. DB를 치지 않는다.
        [입력] 없음
        [출력] dict: {"status": "ok"}
        """
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(api_v2_router, prefix="/api/v2")   # 고도화 중인 기능 — 음성 (2026-10-26)
    return app


app = create_app()  # uvicorn app.main:app 진입점
