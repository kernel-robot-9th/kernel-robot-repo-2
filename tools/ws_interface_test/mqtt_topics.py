# =============================================================================
# 파일   : tools/ws_interface_test/mqtt_topics.py
# 역할   : MQTT 토픽 규칙 — WebSocket과 같은 메시지 봉투(messages.py)를 어느 토픽에 싣는지 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - TOPIC_ROOT, topic_for(type, robot)     메시지 종류 → 토픽 · QoS · retain
#   - parse_topic(topic)                     토픽 → (로봇 이름, 칸) — 브리지·모니터가 보낸 쪽을 알아낸다
#   - online_topic / subscriptions_for(role, name)
# 토픽:
#   hospital/robot/<로봇>/cmd       task_assign · task_cancel           gui → robot   QoS 1
#   hospital/robot/<로봇>/status    robot_status (retain = 최신 상태)   robot → gui   QoS 0
#   hospital/robot/<로봇>/progress  task_progress                       robot → gui   QoS 1
#   hospital/robot/<로봇>/event     robot_event                         robot → gui   QoS 1
#   hospital/robot/<로봇>/online    "1" / "0" (retain, 끊기면 브로커가 "0" = Last Will)
#   hospital/gui/alert              alert                               → gui         QoS 1
# 페이로드는 WebSocket과 같은 봉투 JSON: {"id","type","from","to","ts","payload"}
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

TOPIC_ROOT = "hospital"
ROBOT_PREFIX = f"{TOPIC_ROOT}/robot"
ALERT_TOPIC = f"{TOPIC_ROOT}/gui/alert"


@dataclass(frozen=True)
class TopicRule:
    """메시지 종류 하나를 싣는 토픽 칸."""
    slot: str          # cmd | status | progress | event | alert
    qos: int
    retain: bool


TYPE_RULES: dict[str, TopicRule] = {
    "task_assign": TopicRule("cmd", 1, False),
    "task_cancel": TopicRule("cmd", 1, False),
    "robot_status": TopicRule("status", 0, True),
    "task_progress": TopicRule("progress", 1, False),
    "robot_event": TopicRule("event", 1, False),
    "alert": TopicRule("alert", 1, False),
}
# 토픽 칸마다 실릴 수 있는 메시지 종류 (모니터가 대조)
SLOT_TYPES: dict[str, tuple[str, ...]] = {
    "cmd": ("task_assign", "task_cancel"),
    "status": ("robot_status",),
    "progress": ("task_progress",),
    "event": ("robot_event",),
    "alert": ("alert",),
}
# 토픽 칸을 보낼 수 있는 역할
SLOT_SENDER_ROLE: dict[str, str] = {"cmd": "gui", "status": "robot", "progress": "robot", "event": "robot", "alert": "gui"}


def topic_for(message_type: str, robot: str | None) -> tuple[str, int, bool]:
    """메시지 종류 → (토픽, QoS, retain).
    [입력] message_type / robot: 로봇 이름 (cmd면 받는 로봇, status·progress·event면 보내는 로봇)
    [출력] tuple. MQTT로 보내지 않는 종류(ping·hello 등)면 KeyError
    """
    rule = TYPE_RULES[message_type]
    if rule.slot == "alert":
        return ALERT_TOPIC, rule.qos, rule.retain
    if not robot or robot == "*" or "/" in robot or "+" in robot or "#" in robot:
        raise ValueError(f"'{message_type}' needs one robot name (got {robot!r})")
    return f"{ROBOT_PREFIX}/{robot}/{rule.slot}", rule.qos, rule.retain


def online_topic(robot: str) -> str:
    """[입력] robot / [출력] str: hospital/robot/<로봇>/online"""
    return f"{ROBOT_PREFIX}/{robot}/online"


def parse_topic(topic: str) -> tuple[str | None, str] | None:
    """토픽 → (로봇 이름 또는 None, 칸).
    [입력] topic
    [출력] (robot, slot) — hospital/gui/alert면 (None, "alert"), 규칙에 없는 토픽이면 None
    """
    if topic == ALERT_TOPIC:
        return None, "alert"
    parts = topic.split("/")
    if len(parts) == 4 and f"{parts[0]}/{parts[1]}" == ROBOT_PREFIX and parts[3] in (*SLOT_TYPES, "online"):
        return parts[2], parts[3]
    return None


def subscriptions_for(role: str, name: str) -> list[tuple[str, int]]:
    """역할별 구독 토픽.
    [입력] role: gui | robot / name: 내 이름
    [출력] [(토픽 필터, QoS)]
    """
    if role == "robot":
        return [(f"{ROBOT_PREFIX}/{name}/cmd", 1)]
    return [(f"{ROBOT_PREFIX}/+/status", 0), (f"{ROBOT_PREFIX}/+/progress", 1), (f"{ROBOT_PREFIX}/+/event", 1),
            (f"{ROBOT_PREFIX}/+/online", 1), (ALERT_TOPIC, 1)]
