# =============================================================================
# 파일   : app/clients/fms.py
# 역할   : 팀원 FMS API v1 부르기 — 주문 1건 넣기 POST {FMS_BASE_URL}/api/v1/orders (2026-10-27, 연동 1단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsUnavailable  연결 실패·시간 초과·5xx·JSON이 아님 — 받았는지 알 수 없으니 다음 회차에 같은 request_id로 다시
#   - FmsRejected     FMS가 4xx로 거절 (unknown_room·missing_field·bad_json) — error 코드·message
#   - create_order()  주문 1건. 202(새 주문)·200(같은 request_id로 이미 받음)이면 FMS Order dict
#   - batch_step()    POST /api/v1/batches/{id}/ready·loaded (2026-10-27, 2단계 OMX 연동) — 409 bad_batch_state는 '이미 넘어감'으로 본다
# 계약: docs/api_contract_delivery_2026-10-20.md 10장, 원본 kernel-robot-repo-2/fms/API.md. 인증 없음(10-27 사용자 결정).
# 업무 판단(무엇을 언제 보낼지·저장)은 services/fms_order.py, ready·loaded는 services/fms_omx.py
# =============================================================================
from __future__ import annotations

from typing import Any

import httpx


class FmsUnavailable(Exception):
    """FMS가 주문을 받았는지 알 수 없음 (메시지는 로그용)."""


class FmsRejected(Exception):
    """FMS가 4xx로 거절. code = FMS error 값(예 unknown_room)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


def create_order(fms_base_url: str, request_id: str, room: str, item: str, timeout_seconds: float) -> dict[str, Any]:
    """FMS에 주문 1건(물품 1개)을 넣는다. 같은 request_id를 다시 보내면 FMS가 처음 주문을 200으로 돌려준다(다시 보내도 안전).
    [입력] fms_base_url: 예 "http://192.168.129.50:8770" / request_id: EMR이 만든 고유 값 / room: FMS 방 번호(101호…) / item: 비품 이름
    / timeout_seconds
    [출력] dict: FMS Order {order_id, request_id, room, item, status, …} (4xx면 FmsRejected, 그 밖은 FmsUnavailable)
    """
    url = fms_base_url.rstrip("/") + "/api/v1/orders"
    try:
        response = httpx.post(url, json={"request_id": request_id, "room": room, "item": item}, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise FmsUnavailable(f"POST {url} failed: {error.__class__.__name__}") from error
    try:
        body = response.json()
    except ValueError as error:
        raise FmsUnavailable(f"POST {url} returned {response.status_code} without JSON") from error
    if 400 <= response.status_code < 500:
        body = body if isinstance(body, dict) else {}
        raise FmsRejected(response.status_code, str(body.get("error", "unknown")), str(body.get("message", ""))[:200])
    if response.status_code not in (200, 202) or not isinstance(body, dict) or not body.get("order_id"):
        raise FmsUnavailable(f"POST {url} returned {response.status_code}: {str(body)[:200]}")
    return body


def batch_step(fms_base_url: str, batch_id: str, step: str, timeout_seconds: float) -> dict[str, Any]:
    """묶음 단계 알리기 — ready(OMX 물품 준비 끝 → FMS가 핑키를 약제실로) · loaded(다 실음 → 병실로).
    두 번째로 보내면 FMS는 409 bad_batch_state를 준다 — 10-27 사용자 결정: FMS는 그대로 두고 EMR이 '이미 넘어감'으로 본다.
    [입력] fms_base_url / batch_id: b-5 / step: "ready" | "loaded" / timeout_seconds
    [출력] dict: FMS 응답 (409 bad_batch_state면 {"already": True, …}). 그 밖의 4xx는 FmsRejected, 응답 없음·5xx는 FmsUnavailable
    """
    url = f"{fms_base_url.rstrip('/')}/api/v1/batches/{batch_id}/{step}"
    try:
        response = httpx.post(url, timeout=timeout_seconds)
    except httpx.HTTPError as error:
        raise FmsUnavailable(f"POST {url} failed: {error.__class__.__name__}") from error
    try:
        body = response.json()
    except ValueError as error:
        raise FmsUnavailable(f"POST {url} returned {response.status_code} without JSON") from error
    body = body if isinstance(body, dict) else {}
    if response.status_code == 409 and body.get("error") == "bad_batch_state":
        return {**body, "already": True}
    if 400 <= response.status_code < 500:
        raise FmsRejected(response.status_code, str(body.get("error", "unknown")), str(body.get("message", ""))[:200])
    if response.status_code != 200:
        raise FmsUnavailable(f"POST {url} returned {response.status_code}: {str(body)[:200]}")
    return body
