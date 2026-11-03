# =============================================================================
# 파일   : tools/ws_interface_test/mqtt_bridge.py
# 역할   : WebSocket 시험 서버 ↔ MQTT 브로커 다리 — 웹(WebSocket)과 로봇(MQTT)이 같은 메시지로 서로 시험할 수 있게 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - MqttBridge  브로커에 GUI처럼 구독(status·progress·event·online·alert)하고,
#                 받은 메시지를 규격 검사(mqtt_monitor.check) 후 WebSocket GUI에 전달.
#                 WebSocket GUI가 MQTT 로봇에 보낸 task_assign·task_cancel·alert는 MQTT로 발행.
# 켜기: .venv/bin/python server.py --mqtt localhost:1883   (paho-mqtt 필요 — 그래서 --mqtt일 때만 import)
# 자기가 발행한 메시지가 구독으로 되돌아오면 id로 걸러 다시 보내지 않는다.
# =============================================================================
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from mqtt_monitor import check
from mqtt_topics import parse_topic, subscriptions_for, topic_for

if TYPE_CHECKING:
    from server import InterfaceTestServer

log = logging.getLogger("ws_interface_test.mqtt")


class MqttBridge:
    """브로커 연결 하나. paho 콜백(별도 스레드)은 asyncio 루프로 넘겨 처리한다."""

    def __init__(self, server: InterfaceTestServer, host: str, port: int, loop: asyncio.AbstractEventLoop) -> None:
        self.server, self.loop = server, loop
        self.address = f"{host}:{port}"
        self.robots: set[str] = set()                 # 지금 online인 MQTT 로봇 이름
        self.published_ids: deque[str] = deque(maxlen=500)
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="interface-ws-bridge")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.warning("MQTT %s 접속 실패: %s", self.address, reason_code)
            return
        client.subscribe(subscriptions_for("gui", "bridge"))
        log.info("MQTT bridge connected to %s", self.address)

    def _on_message(self, client, userdata, msg) -> None:
        asyncio.run_coroutine_threadsafe(self._handle(msg.topic, msg.payload.decode("utf-8", "replace")), self.loop)

    async def _handle(self, topic: str, text: str) -> None:
        """MQTT에서 온 메시지 한 개 (asyncio 루프에서).
        [입력] topic / text
        [출력] 없음 — 규격에 맞으면 WebSocket GUI에 전달, online이면 presence
        """
        parsed = parse_topic(topic)
        if parsed is None:
            return
        robot, slot = parsed
        if slot == "online":
            online = text == "1"
            if online:
                self.robots.add(robot)
            else:
                self.robots.discard(robot)
            await self.server.presence_from_mqtt(robot, online)
            return
        ok, detail = check(topic, text)
        if not ok:
            log.warning("MQTT 규격 위반 %s: %s", topic, detail)
            self.server.record("mqtt-invalid", topic, text)
            return
        message = json.loads(text)
        if message.get("id") in self.published_ids:   # 내가 발행한 것이 되돌아옴
            return
        if robot is not None and robot not in self.robots:
            self.robots.add(robot)
            await self.server.presence_from_mqtt(robot, True)
        await self.server.deliver_from_mqtt(message)

    def publish(self, message: dict[str, Any], robot: str | None) -> str:
        """WebSocket에서 온 메시지를 MQTT로.
        [입력] message: 서버가 from·ts를 다시 찍은 메시지 / robot: 받는 로봇 이름 (alert면 None)
        [출력] str: 발행한 토픽
        """
        topic, qos, retain = topic_for(message["type"], robot)
        self.published_ids.append(message["id"])
        self.client.publish(topic, json.dumps(message, ensure_ascii=False), qos=qos, retain=retain)
        self.server.record("mqtt-out", topic, json.dumps(message, ensure_ascii=False))
        return topic

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
