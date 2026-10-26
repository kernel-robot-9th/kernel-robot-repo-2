# =============================================================================
# 파일   : app/clients/robot_server.py
# 역할   : 로봇 서버(팀원 Pinky API, 로봇마다 :8080)에 지금 상태를 묻는다 — GET {robot_server_url}/status
# 작성일 : 2026-10-23
# 구성   :
#   - RobotServerError      연결 실패·시간 초과·200이 아님·JSON 객체가 아님
#   - fetch_robot_status()  /status 응답 JSON(dict)을 그대로 돌려준다. 필드 해석은 services/robot_status.py
# 사용자 결정(2026-10-23): "팀원도 서버가 있기에 로봇에 정확한 정보 요청해야" — 로봇이 보내는 보고 대신 EMR이 claim 때 묻는다.
# GET만 부른다(로봇을 움직이지 않음). 인증 없음 — 팀원 API에 인증이 생기면 여기에 헤더를 넣는다
# =============================================================================
from __future__ import annotations

from typing import Any

import httpx


class RobotServerError(Exception):
    """로봇 서버에서 상태를 받지 못함 (메시지는 로그용)."""


def fetch_robot_status(robot_server_url: str, timeout_seconds: float) -> dict[str, Any]:
    """로봇 서버의 GET /status.
    [입력] robot_server_url: 예 "http://192.168.129.107:8080" / timeout_seconds: 연결·읽기 제한
    [출력] dict: 응답 JSON 객체 (받지 못하면 RobotServerError)
    """
    url = robot_server_url.rstrip("/") + "/status"
    try:
        response = httpx.get(url, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise RobotServerError(f"GET {url} failed: {error.__class__.__name__}") from error
    if response.status_code != 200:
        raise RobotServerError(f"GET {url} returned {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise RobotServerError(f"GET {url} returned non-JSON") from error
    if not isinstance(body, dict):
        raise RobotServerError(f"GET {url} returned {type(body).__name__}, not an object")
    return body
