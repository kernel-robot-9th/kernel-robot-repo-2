# =============================================================================
# 파일   : tools/ws_interface_test/messages.py
# 역할   : WebSocket 인터페이스 시험용 메시지 규격 — 서버·클라이언트·테스트가 같이 쓴다 (EMR과 별개)
# 작성일 : 2026-10-22
# 구성   :
#   - ROLES / MESSAGE_SPECS   접속 역할(gui·robot)과 메시지 종류별 보내는 쪽·받는 쪽·필수 필드
#   - make_message            봉투(envelope) 만들기
#   - validate_message        받은 메시지 검사 → (정상 메시지, 오류 코드)
#   - SAMPLES                 메시지 종류별 예시 payload (클라이언트 --send, 시험 페이지)
# 블록도(Lv.1)의 두 구간을 흉내 낸다: GUI ↔ 서버(실시간 상태·알림 push), 서버 ↔ 로봇(작업 지시, 상태·위치 보고, 이벤트).
# 단위는 이름에 붙인다(EMR 규칙): x_m, yaw_rad, battery_percent.
# =============================================================================
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ROLES = ("gui", "robot")
SERVER = "server"
BROADCAST = "*"


@dataclass(frozen=True)
class MessageSpec:
    """메시지 한 종류의 규칙."""
    senders: tuple[str, ...]      # 보낼 수 있는 역할 (server = 서버만 만든다)
    receivers: tuple[str, ...]    # 받는 역할
    required: tuple[str, ...]     # payload 필수 필드
    description: str


MESSAGE_SPECS: dict[str, MessageSpec] = {
    # ---- 공통 ----
    "hello": MessageSpec((SERVER,), ROLES, ("client_name", "role", "connected"), "접속 직후 서버가 보냄: 내 이름·역할·지금 접속한 클라이언트"),
    "ack": MessageSpec((SERVER,), ROLES, ("message_id", "delivered_to"), "서버가 메시지를 받아 전달했음 (delivered_to = 받은 클라이언트 이름 목록)"),
    "error": MessageSpec((SERVER,), ROLES, ("code", "detail"), "서버가 메시지를 거부함 (code는 아래 ERROR_CODES)"),
    "ping": MessageSpec(ROLES, (SERVER,), (), "연결 확인 → 서버가 pong"),
    "pong": MessageSpec((SERVER,), ROLES, (), "ping 응답"),
    "presence": MessageSpec((SERVER,), ("gui",), ("client_name", "role", "online"), "클라이언트 접속·끊김을 GUI에 알림"),
    # ---- 서버(GUI) → 로봇: 작업 지시 ----
    "task_assign": MessageSpec(("gui",), ("robot",), ("task_id", "delivery_id", "destination"), "배송 작업 지시 (destination = {name, x_m, y_m, yaw_rad})"),
    "task_cancel": MessageSpec(("gui",), ("robot",), ("task_id", "reason"), "작업 취소"),
    # ---- 로봇 → 서버(GUI): 상태·위치 보고, 이벤트 ----
    "robot_status": MessageSpec(("robot",), ("gui",), ("mode", "battery_percent", "x_m", "y_m", "yaw_rad"), "상태·위치 보고 (mode = idle|moving|waiting|charging|error)"),
    "task_progress": MessageSpec(("robot",), ("gui",), ("task_id", "stage"), "작업 단계 (stage = accepted|arrived|done|failed, failed면 failure_reason)"),
    "robot_event": MessageSpec(("robot",), ("gui",), ("level", "code", "message"), "이벤트 업링크 (level = info|warning|critical)"),
    # ---- 서버 → GUI: 알림 ----
    "alert": MessageSpec(("gui", "robot"), ("gui",), ("level", "code", "message"), "알림 push (시험에선 GUI·로봇이 보내면 서버가 GUI 전체에 전달)"),
}

ROBOT_MODES = ("idle", "moving", "waiting", "charging", "error")
TASK_STAGES = ("accepted", "arrived", "done", "failed")
LEVELS = ("info", "warning", "critical")

ERROR_CODES = {
    "invalid_json": "JSON이 아님",
    "invalid_envelope": "type·payload 등 봉투 필드가 없거나 형식이 틀림",
    "unknown_type": "규격에 없는 메시지 종류",
    "sender_not_allowed": "이 역할은 이 메시지를 보낼 수 없음",
    "missing_field": "payload 필수 필드 없음",
    "invalid_value": "값이 허용 범위 밖",
    "target_not_found": "to로 지정한 클라이언트가 접속해 있지 않음",
    "target_role_mismatch": "to로 지정한 클라이언트가 이 메시지를 받는 역할이 아님",
}


def now_iso() -> str:
    """[입력] 없음 / [출력] str: UTC ISO 8601 (Z)"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def make_message(message_type: str, payload: dict[str, Any], sender: str, to: str = BROADCAST,
                 message_id: str | None = None) -> dict[str, Any]:
    """봉투 만들기.
    [입력] message_type / payload / sender: 보내는 클라이언트 이름 / to: 받는 클라이언트 이름 또는 "*"(그 메시지를 받는 역할 전체)
    [출력] dict: {"id", "type", "from", "to", "ts", "payload"}
    """
    return {"id": message_id or uuid.uuid4().hex[:12], "type": message_type, "from": sender, "to": to,
            "ts": now_iso(), "payload": payload}


class MessageError(ValueError):
    """규격 위반. code는 ERROR_CODES의 키."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def validate_message(raw: dict[str, Any], sender_role: str) -> dict[str, Any]:
    """클라이언트가 보낸 메시지 검사.
    [입력] raw: JSON으로 읽은 dict / sender_role: 보낸 클라이언트의 역할 (gui·robot)
    [출력] dict: 정상 메시지 (id가 없으면 채움). 규격 위반이면 MessageError
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str) or not isinstance(raw.get("payload", {}), dict):
        raise MessageError("invalid_envelope", "message must be an object with string 'type' and object 'payload'")
    message_type = raw["type"]
    spec = MESSAGE_SPECS.get(message_type)
    if spec is None:
        raise MessageError("unknown_type", f"unknown message type '{message_type}'")
    if sender_role not in spec.senders:
        raise MessageError("sender_not_allowed", f"role '{sender_role}' cannot send '{message_type}'")
    payload = raw.get("payload") or {}
    missing = [field for field in spec.required if field not in payload]
    if missing:
        raise MessageError("missing_field", f"'{message_type}' payload needs {missing}")
    _check_values(message_type, payload)
    to = raw.get("to", BROADCAST)
    if not isinstance(to, str) or not to:
        raise MessageError("invalid_envelope", "'to' must be a client name or '*'")
    return {**raw, "id": str(raw.get("id") or uuid.uuid4().hex[:12]), "to": to, "payload": payload}


def _check_values(message_type: str, payload: dict[str, Any]) -> None:
    """종류별 값 범위 검사.
    [입력] message_type / payload
    [출력] 없음 (틀리면 MessageError invalid_value)
    """
    def fail(detail: str) -> None:
        raise MessageError("invalid_value", detail)

    if message_type == "robot_status":
        if payload["mode"] not in ROBOT_MODES:
            fail(f"mode must be one of {ROBOT_MODES}")
        battery = payload["battery_percent"]
        if not isinstance(battery, (int, float)) or not 0 <= battery <= 100:
            fail("battery_percent must be a number 0..100")
        for field in ("x_m", "y_m", "yaw_rad"):
            if not isinstance(payload[field], (int, float)):
                fail(f"{field} must be a number")
    elif message_type == "task_progress":
        if payload["stage"] not in TASK_STAGES:
            fail(f"stage must be one of {TASK_STAGES}")
        if payload["stage"] == "failed" and not payload.get("failure_reason"):
            fail("failed stage needs failure_reason")
    elif message_type in ("robot_event", "alert"):
        if payload["level"] not in LEVELS:
            fail(f"level must be one of {LEVELS}")
    elif message_type == "task_assign":
        destination = payload["destination"]
        if not isinstance(destination, dict) or not all(key in destination for key in ("name", "x_m", "y_m", "yaw_rad")):
            fail("destination must have name, x_m, y_m, yaw_rad")


SAMPLES: dict[str, dict[str, Any]] = {
    "ping": {},
    "task_assign": {"task_id": "T-1", "delivery_id": 12,
                    "destination": {"name": "301호", "x_m": 0.26, "y_m": -0.92, "yaw_rad": 0.0}},
    "task_cancel": {"task_id": "T-1", "reason": "nurse_cancelled"},
    "robot_status": {"mode": "moving", "battery_percent": 82.5, "x_m": 0.11, "y_m": -0.40, "yaw_rad": 1.57},
    "task_progress": {"task_id": "T-1", "stage": "arrived"},
    "robot_event": {"level": "warning", "code": "path_blocked", "message": "경로에 장애물, 다시 계획 중"},
    "alert": {"level": "critical", "code": "battery_low", "message": "배송로봇 1호 배터리 15%"},
}
