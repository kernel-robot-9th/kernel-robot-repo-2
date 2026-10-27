# =============================================================================
# 파일   : app/clients/omx.py
# 역할   : 팀원 OMX(로봇팔) API 부르기 — POST /command(색깔별 개수), GET /status
# 작성일 : 2026-10-26
# 구성   :
#   - OmxUnavailable  연결 실패·시간 초과·5xx·JSON 아님
#   - OmxRejected     4xx (OMX가 명령을 받지 않음 — 예: 다른 작업 실행 중). status_code·detail
#   - send_command()  POST {base}/command {"command": {"blue": n, "green": n} 또는 임시 문장, "request_id"} → 응답 JSON
#   - send_pinky()    POST {base}/pinky {"pinky_arrive": true, "request_id"} — 들고 있는 물품을 Pinky 위에 놓기 (2026-10-27, FMS 연동 2단계)
#   - get_status()    GET {base}/status → 응답 JSON
# OMX API는 인증이 없다. POST /command는 로봇팔을 움직인다 — 관리자 API(app/api/v1/omx.py)에서만 부른다.
# 2026-10-27 사용자 결정: 10-26 합의한 색깔별 개수 형식으로 바꿈(예전 형식 = 명령 문장). blue = 약품, green = 비품 (services/omx_items.py)
# =============================================================================
from __future__ import annotations

from typing import Any

import httpx


class OmxUnavailable(Exception):
    """OMX가 응답하지 않음 (메시지는 로그용)."""


class OmxRejected(Exception):
    """OMX가 4xx로 거절함."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"OMX returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _json_or_raise(response: httpx.Response, what: str) -> dict[str, Any]:
    """OMX 응답을 JSON 객체로 꺼낸다.
    [입력] response / what: 로그용 "POST /command" 등 [출력] dict (4xx는 OmxRejected, 그 밖은 OmxUnavailable)
    """
    if 400 <= response.status_code < 500:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = response.text[:200]
        raise OmxRejected(response.status_code, detail)
    if response.status_code >= 300:
        raise OmxUnavailable(f"{what} returned {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise OmxUnavailable(f"{what} returned non-JSON") from error
    if not isinstance(body, dict):
        raise OmxUnavailable(f"{what} returned {type(body).__name__}, not an object")
    return body


def send_command(omx_base_url: str, command: dict[str, int] | str, request_id: str, timeout_seconds: float) -> dict[str, Any]:
    """명령을 보낸다 — OMX가 이미지(YOLO)로 찾아 집고 끝나면 시작 자세로 돌아간다(로봇팔이 움직인다).
    [입력] omx_base_url / command: 색깔별 개수 {"blue": 2, "green": 0} 또는 임시 문장 "pick and place blue gauze"
    (services/omx_items.py omx_command가 설정 OMX_COMMAND_FORMAT으로 고른다) / request_id / timeout_seconds
    [출력] dict: OMX 응답 JSON
    """
    url = omx_base_url.rstrip("/") + "/command"
    try:
        response = httpx.post(url, json={"command": command, "request_id": request_id}, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise OmxUnavailable(f"POST {url} failed: {error.__class__.__name__}") from error
    return _json_or_raise(response, "POST /command")


def send_pinky(omx_base_url: str, request_id: str, timeout_seconds: float) -> dict[str, Any]:
    """Pinky가 약제실에 왔다고 알린다 — OMX가 양팔로 들고 있던 물품을 Pinky 위에 놓고 시작 자세로 돌아간다(로봇팔이 움직인다).
    OMX는 들기(lift) 전에 받아도 기억했다가 들고 나서 놓는다. 끝나면 같은 request_id로 EMR end-point를 다시 부른다.
    [입력] omx_base_url / request_id: 그 물품을 집은 /command의 request_id / timeout_seconds
    [출력] dict: OMX 응답 JSON (accepted: 바로 시작했는지)
    """
    url = omx_base_url.rstrip("/") + "/pinky"
    try:
        response = httpx.post(url, json={"pinky_arrive": True, "request_id": request_id}, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise OmxUnavailable(f"POST {url} failed: {error.__class__.__name__}") from error
    return _json_or_raise(response, "POST /pinky")


def get_status(omx_base_url: str, timeout_seconds: float) -> dict[str, Any]:
    """OMX 지금 상태 (state·phase·command·request_id·end_point 등 OMX가 주는 그대로).
    [입력] omx_base_url / timeout_seconds
    [출력] dict
    """
    url = omx_base_url.rstrip("/") + "/status"
    try:
        response = httpx.get(url, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise OmxUnavailable(f"GET {url} failed: {error.__class__.__name__}") from error
    return _json_or_raise(response, "GET /status")
