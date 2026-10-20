# =============================================================================
# 파일   : delivery_executor/emr_client.py
# 역할   : EMR 로봇 전용 API 클라이언트 (X-Robot-Api-Key) — 표준 라이브러리만
# 작성일 : 2026-10-20
# 구성   :
#   - EmrUnavailable     EMR에 닿지 않음(네트워크·5xx) — 실행기는 잠시 뒤 다시 시도한다
#   - EmrResponse        상태 코드 + JSON 본문 + 오류 코드
#   - RobotEmrClient     me / claim / progress / receipt / get_map
#   - read_api_key()     키 파일 읽기 (권한이 600보다 넓으면 경고)
# 계약: dev_ws/docs/api_contract_delivery_2026-10-20.md
# =============================================================================
from __future__ import annotations

import json
import logging
import os
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HTTP_TIMEOUT_S = 10.0
log = logging.getLogger(__name__)


class EmrUnavailable(Exception):
    """EMR에 연결하지 못했거나 서버 오류(5xx)."""


@dataclass
class EmrResponse:
    status: int
    body: Any

    @property
    def code(self) -> str | None:
        """오류 응답의 code ({"code","detail"}). [출력] str | None"""
        return self.body.get("code") if isinstance(self.body, dict) else None


class RobotEmrClient:
    """로봇 한 대의 키로 EMR 로봇 API를 부른다."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"X-Robot-Api-Key": api_key, "Content-Type": "application/json"}

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, authenticated: bool = True) -> EmrResponse:
        """[입력] method / path: /robot/... 등 / body / authenticated: 키 헤더를 붙일지
        [출력] EmrResponse (4xx도 그대로 돌려준다. 연결 실패·5xx는 EmrUnavailable)
        """
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self._headers if authenticated else {"Content-Type": "application/json"}
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                text = response.read().decode("utf-8")
                return EmrResponse(response.status, json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = {"detail": text[:200]}
            if error.code >= 500:
                raise EmrUnavailable(f"HTTP {error.code} {path}: {parsed}") from error
            return EmrResponse(error.code, parsed)
        except (urllib.error.URLError, OSError) as error:
            raise EmrUnavailable(f"{method} {path}: {error}") from error

    def me(self) -> EmrResponse:
        """GET /robot/me"""
        return self.request("GET", "/robot/me")

    def claim(self) -> EmrResponse:
        """POST /robot/deliveries/claim — 200(배송) | 204(없음)"""
        return self.request("POST", "/robot/deliveries/claim")

    def progress(self, delivery_id: int, stage: str, failure_reason: str | None = None) -> EmrResponse:
        """POST /robot/deliveries/{id}/progress"""
        body: dict[str, Any] = {"stage": stage}
        if failure_reason:
            body["failure_reason"] = failure_reason
        return self.request("POST", f"/robot/deliveries/{delivery_id}/progress", body)

    def receipt(self, delivery_id: int, aruco_marker_id: int) -> EmrResponse:
        """POST /robot/deliveries/{id}/receipt"""
        return self.request("POST", f"/robot/deliveries/{delivery_id}/receipt", {"aruco_marker_id": aruco_marker_id})

    def get_map(self, map_id: int) -> EmrResponse:
        """GET /maps/{id} (로그인 없이 조회 가능) — 로봇 맵과 비교용"""
        return self.request("GET", f"/maps/{map_id}", authenticated=False)


def read_api_key(path: str) -> str:
    """키 파일(한 줄)을 읽는다. 다른 사용자가 읽을 수 있는 권한이면 경고한다.
    [입력] path: ~ 사용 가능
    [출력] str: 키 (파일이 없거나 비면 ValueError)
    """
    key_path = Path(os.path.expanduser(path))
    if not key_path.is_file():
        raise ValueError(f"API 키 파일이 없습니다: {key_path} — EMR 로봇 탭에서 키를 발급해 이 파일에 한 줄로 저장하세요(chmod 600)")
    mode = stat.S_IMODE(key_path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        log.warning("API 키 파일 권한이 넓습니다(%o): %s — chmod 600 권장", mode, key_path)
    key = key_path.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"API 키 파일이 비어 있습니다: {key_path}")
    return key
