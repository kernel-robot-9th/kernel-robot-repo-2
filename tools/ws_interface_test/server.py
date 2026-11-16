#!/usr/bin/env python3
# =============================================================================
# 파일   : tools/ws_interface_test/server.py
# 역할   : WebSocket 인터페이스 시험 서버 — GUI·로봇 역할 클라이언트끼리 규격 메시지를 주고받게 중계 (EMR과 별개)
# 작성일 : 2026-10-22
# 구성   :
#   - InterfaceTestServer   접속 관리(이름·역할), 규격 검사(messages.validate_message), 라우팅, ack/error, JSONL 기록
#   - serve_page            같은 포트의 http://<host>:<port>/ 로 브라우저 시험 페이지(test_page.html), /specs.json 으로 메시지 규격을 준다
#   - main                  python3 server.py --host 0.0.0.0 --port 8765 --log logs/ [--mqtt localhost:1883]
# --mqtt를 주면 mqtt_bridge.MqttBridge가 MQTT 로봇과 이어 준다 (WebSocket GUI ↔ MQTT 로봇, .venv 파이썬 필요)
# 접속: ws://<host>:<port>/?role=gui&name=nurse-ui   또는   ?role=robot&name=pinky_1
# 시스템 파이썬(/usr/bin/python3)의 websockets 16 asyncio API를 쓴다. 인증·암호화 없음 — 시험망에서만.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from messages import (
    BROADCAST, ERROR_CODES, MESSAGE_SPECS, ROLES, SAMPLES, SERVER, MessageError, make_message, now_iso, validate_message,
)

PAGE_PATH = Path(__file__).with_name("test_page.html")
CLOSE_POLICY_VIOLATION = 1008
log = logging.getLogger("ws_interface_test")


class InterfaceTestServer:
    """접속한 클라이언트를 이름으로 관리하고 메시지를 규격대로 중계한다."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.clients: dict[str, tuple[str, ServerConnection]] = {}   # 이름 → (역할, 연결)
        self.bridge = None   # mqtt_bridge.MqttBridge (--mqtt일 때)
        self.log_file = None
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = (log_dir / f"ws_{now_iso()[:10]}.jsonl").open("a", encoding="utf-8")

    # ---- 연결 -----------------------------------------------------------------

    async def handle(self, connection: ServerConnection) -> None:
        """클라이언트 하나의 수명: 역할·이름 확인 → hello → 메시지 반복 → 끊김 정리.
        [입력] connection
        [출력] 없음
        """
        query = parse_qs(urlsplit(connection.request.path).query)
        role = (query.get("role") or [""])[0]
        name = (query.get("name") or [""])[0].strip()
        if role not in ROLES or not name or name == SERVER:
            await connection.close(CLOSE_POLICY_VIOLATION, f"need ?role={'|'.join(ROLES)}&name=<unique name>")
            return
        if name in self.clients:
            await connection.close(CLOSE_POLICY_VIOLATION, f"name '{name}' is already connected")
            return
        self.clients[name] = (role, connection)
        log.info("connected %s (%s), now %d", name, role, len(self.clients))
        await self._send(connection, make_message("hello", {
            "client_name": name, "role": role,
            "connected": [{"name": other, "role": other_role} for other, (other_role, _) in self.clients.items()]
                         + [{"name": robot, "role": "robot", "via": "mqtt"} for robot in sorted(self._mqtt_robots())],
        }, SERVER, to=name))
        await self._presence(name, role, online=True)
        try:
            async for text in connection:
                await self._on_text(name, role, connection, text)
        except ConnectionClosed:
            pass
        finally:
            self.clients.pop(name, None)
            log.info("disconnected %s, now %d", name, len(self.clients))
            await self._presence(name, role, online=False)

    # ---- 메시지 ---------------------------------------------------------------

    async def _on_text(self, name: str, role: str, connection: ServerConnection, text: str | bytes) -> None:
        """받은 메시지 한 개 처리.
        [입력] name·role: 보낸 클라이언트 / connection / text: 받은 프레임
        [출력] 없음 (보낸 쪽에 ack 또는 error)
        """
        self.record("in", name, text)
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._error(connection, name, "invalid_json", "frame is not JSON", None)
            return
        try:
            message = validate_message(raw, role)
        except MessageError as error:
            await self._error(connection, name, error.code, error.detail, raw.get("id") if isinstance(raw, dict) else None)
            return
        if message["type"] == "ping":
            await self._send(connection, make_message("pong", {}, SERVER, to=name, message_id=message["id"]))
            return
        targets = self._targets(message, name)
        if isinstance(targets, MessageError):
            await self._error(connection, name, targets.code, targets.detail, message["id"])
            return
        # 서버가 보낸 사람·시각을 다시 찍는다 (클라이언트가 from을 속이지 못하게)
        forwarded = {**message, "from": name, "ts": now_iso()}
        for target_name, target_connection in targets:
            if target_connection is None:   # MQTT 쪽 (다리): "mqtt:<로봇>" 또는 "mqtt:alert"
                robot = None if message["type"] == "alert" else target_name.removeprefix("mqtt:")
                self.bridge.publish(forwarded, robot)
            else:
                await self._send(target_connection, forwarded)
        await self._send(connection, make_message("ack", {
            "message_id": message["id"], "delivered_to": [target_name for target_name, _ in targets],
        }, SERVER, to=name))

    def _targets(self, message: dict[str, Any], sender: str) -> list[tuple[str, ServerConnection | None]] | MessageError:
        """받을 클라이언트 고르기. to="*"면 그 메시지를 받는 역할 전체(보낸 사람 제외).
        --mqtt면 MQTT 로봇도 받는 쪽이 된다: ("mqtt:<로봇>", None), GUI가 보낸 alert는 ("mqtt:alert", None)도.
        [입력] message: 검사를 통과한 메시지 / sender: 보낸 클라이언트 이름
        [출력] [(이름, 연결 또는 None=MQTT)] 또는 MessageError
        """
        receivers = MESSAGE_SPECS[message["type"]].receivers
        to = message["to"]
        mqtt_robots = self._mqtt_robots() if "robot" in receivers else set()
        if to == BROADCAST:
            targets: list[tuple[str, ServerConnection | None]] = [
                (other, connection) for other, (other_role, connection) in self.clients.items()
                if other_role in receivers and other != sender]
            targets += [(f"mqtt:{robot}", None) for robot in sorted(mqtt_robots) if robot not in self.clients]
            if message["type"] == "alert" and self.bridge is not None:
                targets.append(("mqtt:alert", None))
            return targets
        if to not in self.clients and to in mqtt_robots:
            return [(f"mqtt:{to}", None)]
        if to not in self.clients:
            return MessageError("target_not_found", f"no connected client named '{to}'")
        target_role, connection = self.clients[to]
        if target_role not in receivers:
            return MessageError("target_role_mismatch", f"'{to}' is {target_role}; {message['type']} goes to {receivers}")
        return [(to, connection)]

    async def _presence(self, name: str, role: str, online: bool) -> None:
        """접속·끊김을 GUI 클라이언트에 알림."""
        message = make_message("presence", {"client_name": name, "role": role, "online": online}, SERVER)
        for other, (other_role, connection) in list(self.clients.items()):
            if other_role == "gui" and other != name:
                await self._send(connection, message)

    def _mqtt_robots(self) -> set[str]:
        """[출력] set: 지금 online인 MQTT 로봇 이름 (--mqtt가 없으면 빈 집합)"""
        return set(self.bridge.robots) if self.bridge is not None else set()

    async def presence_from_mqtt(self, robot: str, online: bool) -> None:
        """MQTT 로봇의 online 토픽 → WebSocket GUI에 presence (via=mqtt)."""
        message = make_message("presence", {"client_name": robot, "role": "robot", "online": online, "via": "mqtt"}, SERVER)
        for other, (other_role, connection) in list(self.clients.items()):
            if other_role == "gui":
                await self._send(connection, message)

    async def deliver_from_mqtt(self, message: dict[str, Any]) -> None:
        """MQTT에서 온 규격 메시지 → WebSocket GUI. to가 접속한 GUI 이름이면 그 GUI에만, 아니면 GUI 전체.
        [입력] message: mqtt_monitor.check를 통과한 메시지
        """
        to = message.get("to")
        for other, (other_role, connection) in list(self.clients.items()):
            if other_role == "gui" and (to not in self.clients or other == to):
                await self._send(connection, message)

    async def _error(self, connection: ServerConnection, name: str, code: str, detail: str, message_id: Any) -> None:
        await self._send(connection, make_message("error", {"code": code, "detail": detail, "message_id": message_id},
                                                  SERVER, to=name))

    async def _send(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        text = json.dumps(message, ensure_ascii=False)
        self.record("out", message.get("to", ""), text)
        try:
            await connection.send(text)
        except ConnectionClosed:
            pass

    def record(self, direction: str, client: str, text: str | bytes) -> None:
        """주고받은 프레임을 JSONL로 남김 (--log를 줬을 때만).
        [입력] direction: in | out / client: 상대 이름 / text: 프레임
        """
        if self.log_file is None:
            return
        frame = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
        self.log_file.write(json.dumps({"ts": now_iso(), "dir": direction, "client": client, "frame": frame},
                                       ensure_ascii=False) + "\n")
        self.log_file.flush()


def serve_page(connection: ServerConnection, request: Request) -> Response | None:
    """WebSocket 업그레이드가 아닌 일반 GET이면 시험 페이지(/)나 404를 돌려준다.
    [입력] connection / request
    [출력] Response | None: None이면 WebSocket 핸드셰이크를 계속한다
    """
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    path = urlsplit(request.path).path
    if path in ("/", "/test_page.html"):
        return _ok(PAGE_PATH.read_bytes(), "text/html; charset=utf-8")
    if path == "/specs.json":
        specs = {
            "roles": list(ROLES), "broadcast": BROADCAST, "error_codes": ERROR_CODES, "samples": SAMPLES,
            "messages": {message_type: {"senders": spec.senders, "receivers": spec.receivers, "required": spec.required,
                                        "description": spec.description}
                         for message_type, spec in MESSAGE_SPECS.items()},
        }
        return _ok(json.dumps(specs, ensure_ascii=False).encode(), "application/json; charset=utf-8")
    return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")


def _ok(body: bytes, content_type: str) -> Response:
    headers = Headers([("Content-Type", content_type), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
    return Response(HTTPStatus.OK.value, "OK", headers, body)


async def run(host: str, port: int, log_dir: Path | None, mqtt_address: str | None = None) -> None:
    server = InterfaceTestServer(log_dir)
    if mqtt_address:
        from mqtt_bridge import MqttBridge   # paho-mqtt가 있을 때만 (.venv)
        mqtt_host, _, mqtt_port = mqtt_address.partition(":")
        server.bridge = MqttBridge(server, mqtt_host, int(mqtt_port or 1883), asyncio.get_running_loop())
    async with serve(server.handle, host, port, process_request=serve_page, ping_interval=20, ping_timeout=20):
        log.info("listening on ws://%s:%d  (test page http://%s:%d/)", host, port, host, port)
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser(description="WebSocket 인터페이스 시험 서버 (GUI·로봇 역할 중계)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=None, help="주고받은 프레임을 JSONL로 남길 폴더")
    parser.add_argument("--mqtt", default=None, help="MQTT 브로커 host:port — 주면 WebSocket GUI ↔ MQTT 로봇 다리를 켠다")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(run(args.host, args.port, args.log, args.mqtt))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
