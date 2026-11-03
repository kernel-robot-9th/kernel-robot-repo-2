"""WebSocket 인터페이스 시험 서버 — 규격 검사(단위)와 실제 접속 중계(통합). 시스템 파이썬으로:
    cd tools/ws_interface_test && /usr/bin/python3 -m pytest -q test_ws_interface.py
"""
from __future__ import annotations

import asyncio
import json
import urllib.request

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from messages import SAMPLES, MessageError, make_message, validate_message
from server import InterfaceTestServer, serve_page


# ---- 규격 검사 (단위) ------------------------------------------------------------

def test_samples_pass_their_own_spec():
    sender_role = {"task_assign": "gui", "task_cancel": "gui", "alert": "gui", "ping": "gui"}
    for message_type, payload in SAMPLES.items():
        validate_message(make_message(message_type, payload, "someone"), sender_role.get(message_type, "robot"))


@pytest.mark.parametrize("raw, role, code", [
    ("not a dict", "gui", "invalid_envelope"),
    ({"type": "teleport", "payload": {}}, "gui", "unknown_type"),
    ({"type": "robot_status", "payload": SAMPLES["robot_status"]}, "gui", "sender_not_allowed"),
    ({"type": "task_assign", "payload": SAMPLES["task_assign"]}, "robot", "sender_not_allowed"),
    ({"type": "robot_status", "payload": {"mode": "moving"}}, "robot", "missing_field"),
    ({"type": "robot_status", "payload": {**SAMPLES["robot_status"], "battery_percent": 130}}, "robot", "invalid_value"),
    ({"type": "robot_status", "payload": {**SAMPLES["robot_status"], "mode": "flying"}}, "robot", "invalid_value"),
    ({"type": "task_progress", "payload": {"task_id": "T-1", "stage": "failed"}}, "robot", "invalid_value"),
    ({"type": "task_assign", "payload": {**SAMPLES["task_assign"], "destination": {"name": "301호"}}}, "gui", "invalid_value"),
    ({"type": "hello", "payload": {}}, "gui", "sender_not_allowed"),
])
def test_invalid_messages_are_rejected_with_code(raw, role, code):
    with pytest.raises(MessageError) as error:
        validate_message(raw, role)
    assert error.value.code == code


# ---- 실제 접속 (통합) ------------------------------------------------------------

async def _start():
    server = InterfaceTestServer()
    ws_server = await serve(server.handle, "127.0.0.1", 0, process_request=serve_page)
    port = ws_server.sockets[0].getsockname()[1]
    return ws_server, port


async def _recv(connection, timeout: float = 2.0) -> dict:
    return json.loads(await asyncio.wait_for(connection.recv(), timeout))


async def _send(connection, message_type: str, to: str = "*", payload: dict | None = None) -> dict:
    message = make_message(message_type, payload if payload is not None else SAMPLES[message_type], "ignored", to)
    await connection.send(json.dumps(message))
    return message


def test_routing_ack_presence_and_errors():
    async def scenario():
        ws_server, port = await _start()
        url = f"ws://127.0.0.1:{port}/?role="
        try:
            async with connect(url + "gui&name=nurse-ui") as gui:
                hello = await _recv(gui)
                assert hello["type"] == "hello" and hello["payload"]["role"] == "gui"
                async with connect(url + "robot&name=pinky_1") as robot:
                    assert (await _recv(robot))["type"] == "hello"
                    presence = await _recv(gui)
                    assert presence["type"] == "presence" and presence["payload"] == {
                        "client_name": "pinky_1", "role": "robot", "online": True}

                    # GUI → 로봇 작업 지시: 로봇이 받고, 서버가 from을 다시 찍고, GUI는 ack
                    sent = await _send(gui, "task_assign", "pinky_1")
                    received = await _recv(robot)
                    assert received["type"] == "task_assign" and received["from"] == "nurse-ui"
                    assert received["payload"] == SAMPLES["task_assign"] and received["id"] == sent["id"]
                    ack = await _recv(gui)
                    assert ack["type"] == "ack" and ack["payload"] == {"message_id": sent["id"], "delivered_to": ["pinky_1"]}

                    # 로봇 → 모든 GUI: 상태 보고
                    await _send(robot, "robot_status")
                    status = await _recv(gui)
                    assert status["type"] == "robot_status" and status["from"] == "pinky_1"
                    assert (await _recv(robot))["payload"]["delivered_to"] == ["nurse-ui"]

                    # 오류: 규격 위반, 없는 대상, 역할이 안 맞는 대상, JSON 아님, ping
                    await _send(robot, "task_assign", "nurse-ui")
                    assert (await _recv(robot))["payload"]["code"] == "sender_not_allowed"
                    await _send(gui, "task_assign", "pinky_9")
                    assert (await _recv(gui))["payload"]["code"] == "target_not_found"
                    await _send(gui, "alert", "pinky_1")
                    assert (await _recv(gui))["payload"]["code"] == "target_role_mismatch"
                    await gui.send("{not json")
                    assert (await _recv(gui))["payload"]["code"] == "invalid_json"
                    await _send(gui, "ping", payload={})
                    assert (await _recv(gui))["type"] == "pong"

                offline = await _recv(gui)
                assert offline["type"] == "presence" and offline["payload"]["online"] is False
        finally:
            ws_server.close()
            await ws_server.wait_closed()
    asyncio.run(scenario())


def test_bad_connect_is_closed_with_reason():
    async def scenario():
        ws_server, port = await _start()
        try:
            async with connect(f"ws://127.0.0.1:{port}/?role=admin&name=x") as bad:
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(bad.recv(), 2)
                assert closed.value.rcvd.code == 1008
            async with connect(f"ws://127.0.0.1:{port}/?role=gui&name=same") as first:
                await _recv(first)
                async with connect(f"ws://127.0.0.1:{port}/?role=gui&name=same") as second:
                    with pytest.raises(ConnectionClosed) as closed:
                        await asyncio.wait_for(second.recv(), 2)
                    assert "already connected" in closed.value.rcvd.reason
        finally:
            ws_server.close()
            await ws_server.wait_closed()
    asyncio.run(scenario())


def test_http_serves_page_and_specs():
    async def scenario():
        ws_server, port = await _start()
        try:
            loop = asyncio.get_running_loop()
            fetch = lambda path: urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2).read()  # noqa: E731
            page = await loop.run_in_executor(None, fetch, "/")
            specs = json.loads(await loop.run_in_executor(None, fetch, "/specs.json"))
            assert b"WebSocket" in page
            assert specs["messages"]["task_assign"]["receivers"] == ["robot"]
            assert "robot_status" in specs["samples"]
        finally:
            ws_server.close()
            await ws_server.wait_closed()
    asyncio.run(scenario())
