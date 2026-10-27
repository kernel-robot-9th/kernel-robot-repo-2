# =============================================================================
# 파일   : app/api/v1/omx.py
# 역할   : 관리자용 OMX(로봇팔) 명령·상태 (/omx) — 팀원 OMX API(192.168.129.86:8000)를 EMR이 대신 부른다
# 작성일 : 2026-10-26
# 구성   :
#   - send_omx_command  POST /omx/command  — 색깔별 개수 {"command": {"blue": n, "green": n}} 또는 임시 문장 {"command": "pick and place blue gauze"} (로봇팔이 움직인다, 관리자만)
#   - get_omx_status    GET  /omx/status   — OMX 상태 그대로 (관리자만)
# OMX가 끝나면 GET /robot/{request_id}/end-point(robot_access.py, 인증 없음)로 완료 신호를 보낸다
# =============================================================================
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.deps import ADMIN_RESPONSES, CurrentAdmin
from app.schemas.omx import OmxCommandIn, OmxCommandOut
from app.services.omx_control import OmxControlService

router = APIRouter(responses=ADMIN_RESPONSES)
OMX_ERRORS = {
    400: {"description": "omx_sentence_disabled — 문장 명령은 임시 스위치(OMX_COMMAND_FORMAT=sentence)를 켰을 때만"},
    409: {"description": "omx_rejected — OMX가 거절함(예: 다른 작업 실행 중). detail에 OMX 응답"},
    503: {"description": "omx_unavailable — OMX가 응답하지 않음(꺼짐·시간 초과)"},
}


@router.post(
    "/command", response_model=OmxCommandOut,
    summary="OMX에 명령 보내기 (관리자)",
    description=(
        "색깔별 개수를 OMX POST /command로 보낸다 — `{\"command\": {\"blue\": n, \"green\": n}, \"request_id\"}`. "
        "blue = 약품(파란 거즈), green = 비품(녹색 거즈), 합계 1~3. **로봇팔이 움직인다.** "
        "request_id는 EMR이 만든다 — OMX가 끝나면 같은 값으로 GET /api/v1/robot/{request_id}/end-point를 부른다. 2026-10-26, 2026-10-27 형식 변경(예전 = 명령 문장). "
        "**임시(10-27)**: 설정 `OMX_COMMAND_FORMAT=sentence`일 때만 문장 `{\"command\": \"pick and place blue gauze\"}`도 받아 OMX에 그대로 보낸다 "
        "(기본 counts면 400 `omx_sentence_disabled`)"
    ),
    responses=OMX_ERRORS,
)
def send_omx_command(admin: CurrentAdmin, data: OmxCommandIn) -> OmxCommandOut:
    """
    [입력] admin: 관리자 / data.command: 색깔별 개수 또는 문장(임시)
    [출력] OmxCommandOut
    """
    command = data.command if isinstance(data.command, str) else data.command.model_dump()
    request_id, sent_at, omx_response = OmxControlService().send_command(command, admin.id)
    return OmxCommandOut(request_id=request_id, command=data.command, sent_at=sent_at, omx_response=omx_response)


@router.get(
    "/status", summary="OMX 상태 (관리자)",
    description="OMX GET /status를 그대로 돌려준다(state·phase·command·request_id·end_point 등). 2026-10-26",
    responses=OMX_ERRORS,
)
def get_omx_status(admin: CurrentAdmin) -> dict[str, Any]:
    """
    [입력] admin: 관리자
    [출력] dict: OMX 상태
    """
    return OmxControlService().status()
