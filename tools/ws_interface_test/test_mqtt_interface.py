"""MQTT 인터페이스 — 토픽 규칙·규격 감시(단위)와 WebSocket GUI ↔ 다리 ↔ MQTT 로봇(통합).
통합 테스트는 브로커(localhost:1883)가 떠 있을 때만 돈다:  cd mqtt && docker compose up -d
    .venv/bin/python -m pytest -q test_mqtt_interface.py
"""
from __future__ import annotations

import asyncio
import json
import socket
import uuid

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from messages import SAMPLES, make_message
from mqtt_monitor import check
from mqtt_topics import online_topic, parse_topic, subscriptions_for, topic_for

BROKER = ("localhost", 1883)


def _broker_up() -> bool:
    try:
        with socket.create_connection(BROKER, timeout=0.5):
            return True
    except OSError:
        return False


requires_broker = pytest.mark.skipif(not _broker_up(), reason="MQTT 브로커(localhost:1883)가 떠 있지 않음")


# ---- 토픽 규칙 (단위) -----------------------------------------------------------

def test_topics_round_trip():
    assert topic_for("task_assign", "pinky_1") == ("hospital/robot/pinky_1/cmd", 1, False)
    assert topic_for("robot_status", "pinky_1") == ("hospital/robot/pinky_1/status", 0, True)
    assert topic_for("alert", None) == ("hospital/gui/alert", 1, False)
    assert parse_topic("hospital/robot/pinky_1/progress") == ("pinky_1", "progress")
    assert parse_topic(online_topic("pinky_1")) == ("pinky_1", "online")
    assert parse_topic("hospital/gui/alert") == (None, "alert")
    assert parse_topic("hospital/robot/pinky_1/teleport") is None
    assert subscriptions_for("robot", "pinky_1") == [("hospital/robot/pinky_1/cmd", 1)]
    with pytest.raises(ValueError):
        topic_for("task_assign", "*")   # 명령은 로봇 하나에


@pytest.mark.parametrize("topic, message, ok, code", [
    ("hospital/robot/pinky_1/status", make_message("robot_status", SAMPLES["robot_status"], "pinky_1"), True, ""),
    ("hospital/robot/pinky_1/cmd", make_message("task_assign", SAMPLES["task_assign"], "web", "pinky_1"), True, ""),
    ("hospital/robot/pinky_1/status", make_message("task_progress", SAMPLES["task_progress"], "pinky_1"), False, "wrong_topic"),
    ("hospital/robot/pinky_1/status", make_message("robot_status", SAMPLES["robot_status"], "pinky_2"), False, "from_mismatch"),
    ("hospital/robot/pinky_1/cmd", make_message("task_assign", SAMPLES["task_assign"], "web", "pinky_2"), False, "to_mismatch"),
    ("hospital/robot/pinky_1/status", make_message("robot_status", {**SAMPLES["robot_status"], "battery_percent": 120}, "pinky_1"),
     False, "invalid_value"),
    ("hospital/robot/pinky_1/event", make_message("robot_event", {"level": "warning"}, "pinky_1"), False, "missing_field"),
    ("hospital/elsewhere", {}, False, "unknown_topic"),
])
def test_monitor_check(topic, message, ok, code):
    result, detail = check(topic, json.dumps(message))
    assert result is ok and detail.startswith(code)


def test_monitor_check_online_and_garbage():
    assert check(online_topic("pinky_1"), "1")[0] is True
    assert check(online_topic("pinky_1"), "yes")[0] is False
    assert check("hospital/robot/pinky_1/status", "{not json")[1].startswith("invalid_json")


# ---- WebSocket GUI ↔ 다리 ↔ MQTT 로봇 (통합) ----------------------------------------

@requires_broker
def test_bridge_between_websocket_gui_and_mqtt_robot():
    from mqtt_client import MqttTestClient
    from server import InterfaceTestServer, serve_page

    robot_name = f"pinky_t{uuid.uuid4().hex[:6]}"

    async def recv_until(gui, wanted_type: str, timeout: float = 3.0, **payload_match) -> dict:
        """wanted_type이고 payload가 payload_match와 맞는 메시지까지 받는다 (다른 로봇이 떠 있어도 섞이지 않게)."""
        async def loop():
            while True:
                message = json.loads(await gui.recv())
                payload = message.get("payload") or {}
                if message["type"] == wanted_type and all(payload.get(key) == value for key, value in payload_match.items()):
                    return message
        return await asyncio.wait_for(loop(), timeout)

    async def scenario():
        from mqtt_bridge import MqttBridge
        server = InterfaceTestServer()
        server.bridge = MqttBridge(server, *BROKER, asyncio.get_running_loop())
        ws_server = await serve(server.handle, "127.0.0.1", 0, process_request=serve_page)
        port = ws_server.sockets[0].getsockname()[1]
        robot = None
        try:
            async with connect(f"ws://127.0.0.1:{port}/?role=gui&name=web-test") as gui:
                await recv_until(gui, "hello")
                # MQTT 로봇이 붙으면 online=1 → GUI에 presence(via=mqtt)
                robot = await asyncio.to_thread(MqttTestClient, *BROKER, "robot", robot_name)
                presence = await recv_until(gui, "presence", client_name=robot_name)
                assert presence["payload"] == {"client_name": robot_name, "role": "robot", "online": True, "via": "mqtt"}

                # WebSocket GUI → MQTT 로봇: task_assign이 cmd 토픽으로
                received: list[dict] = []
                robot.client.on_message = lambda client, userdata, msg: received.append(json.loads(msg.payload))
                await gui.send(json.dumps(make_message("task_assign", SAMPLES["task_assign"], "x", robot_name)))
                ack = await recv_until(gui, "ack")
                assert ack["payload"]["delivered_to"] == [f"mqtt:{robot_name}"]
                for _ in range(30):
                    if received:
                        break
                    await asyncio.sleep(0.1)
                assert received and received[0]["type"] == "task_assign" and received[0]["from"] == "web-test"

                # MQTT 로봇 → WebSocket GUI: robot_status가 다리를 거쳐
                await asyncio.to_thread(robot.send, "robot_status", "*", None)
                status = await recv_until(gui, "robot_status")
                while status["from"] != robot_name:   # 다른 로봇의 상태 보고는 건너뜀
                    status = await recv_until(gui, "robot_status")
                assert status["from"] == robot_name and status["payload"] == SAMPLES["robot_status"]
        finally:
            if robot is not None:
                await asyncio.to_thread(robot.close)
                # retain으로 남은 상태 지우기
                robot_cleanup = robot.client
                robot_cleanup.reconnect()
                robot_cleanup.publish(topic_for("robot_status", robot_name)[0], b"", qos=1, retain=True)
                robot_cleanup.publish(online_topic(robot_name), b"", qos=1, retain=True)
                robot_cleanup.loop(1)
                robot_cleanup.disconnect()
            server.bridge.close()
            ws_server.close()
            await ws_server.wait_closed()
    asyncio.run(scenario())
