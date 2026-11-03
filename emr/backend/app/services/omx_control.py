# =============================================================================
# 파일   : app/services/omx_control.py
# 역할   : 관리자가 EMR에서 OMX(로봇팔)에 명령을 보내고 상태를 본다 (2026-10-26)
# 작성일 : 2026-10-26
# 구성   :
#   - OmxControlService  send_command(command, admin_id) — request_id를 만들어 OMX POST /command
#                        status() — OMX GET /status 그대로
#   - new_request_id()   "emr-20261026T063012-1a2b3c" — 완료 신호 주소(/robot/{request_id}/end-point) 규칙에 맞는 값
# OMX가 끝나면 같은 request_id로 GET /api/v1/robot/{request_id}/end-point를 부른다(services/omx_signal.py).
# /command는 예전 형식(명령 문장). DB는 쓰지 않는다 — 보낸 명령은 서버 로그(omx_command_sent)에만
# =============================================================================
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

import structlog

from app.clients.omx import OmxRejected, OmxUnavailable, get_status, send_command
from app.core.config import settings
from app.core.exceptions import Conflict, ServiceUnavailable

log = structlog.get_logger(__name__)


def new_request_id(now: datetime) -> str:
    """EMR이 보내는 OMX 작업 번호. 영문·숫자·`-`만 써서 완료 신호 주소 규칙(^[A-Za-z0-9._-]{1,64}$)에 맞다.
    [입력] now [출력] str: 예 "emr-20261026T063012-1a2b3c"
    """
    return f"emr-{now.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


class OmxControlService:
    """OMX 명령·상태. OMX 응답이 없으면 503 omx_unavailable, 거절(4xx)이면 409 omx_rejected."""

    def send_command(self, command: str, admin_id: int) -> tuple[str, datetime, dict[str, Any]]:
        """명령 문장을 OMX에 보낸다 — 로봇팔이 움직인다.
        [입력] command: 예 "pick and place green gauze" / admin_id: 보낸 관리자(로그용)
        [출력] (request_id, 보낸 시각, OMX 응답 JSON)
        """
        sent_at = datetime.now(UTC)
        request_id = new_request_id(sent_at)
        attempt = log.bind(request_id=request_id, admin_id=admin_id, command=command)
        try:
            response = send_command(settings.OMX_BASE_URL, command, request_id, settings.OMX_TIMEOUT_SECONDS)
        except OmxUnavailable as error:
            attempt.warning("omx_command_failed", error=str(error))
            raise ServiceUnavailable(str(error), code="omx_unavailable") from error
        except OmxRejected as error:
            attempt.warning("omx_command_rejected", omx_status=error.status_code, detail=error.detail)
            raise Conflict(f"OMX rejected the command: {error.status_code} {error.detail}", code="omx_rejected") from error
        attempt.info("omx_command_sent")
        return request_id, sent_at, response

    def status(self) -> dict[str, Any]:
        """OMX 지금 상태 (OMX가 주는 그대로).
        [입력] 없음 [출력] dict
        """
        try:
            return get_status(settings.OMX_BASE_URL, settings.OMX_TIMEOUT_SECONDS)
        except OmxUnavailable as error:
            raise ServiceUnavailable(str(error), code="omx_unavailable") from error
        except OmxRejected as error:
            raise Conflict(f"OMX rejected status: {error.status_code} {error.detail}", code="omx_rejected") from error
