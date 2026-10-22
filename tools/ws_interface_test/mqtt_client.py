#!/usr/bin/env python3
# =============================================================================
# 파일   : tools/ws_interface_test/mqtt_client.py
# 역할   : MQTT 인터페이스 시험 클라이언트 (터미널) — WebSocket client.py와 같은 메시지를 MQTT 토픽으로 주고받는다
# 작성일 : 2026-10-22
# 구성   :
#   - MqttTestClient   접속(로봇은 Last Will로 online=0), 역할별 구독, 보내기 전 규격 검사, 받은 메시지 찍기
#   - 한 번 보내기    --send task_assign --to pinky_mqtt [--payload '{...}']
#   - 대화형          명령: send <type> [to] [json] · types · quit
#   - 로봇 흉내       --role robot --auto : task_assign을 받으면 accepted → 이동 상태 → arrived → done
# 예: .venv/bin/python mqtt_client.py --role robot --name pinky_mqtt --auto
#     .venv/bin/python mqtt_client.py --role gui --name web-test --send task_assign --to pinky_mqtt
# 토픽 규칙은 mqtt_topics.py, 메시지 규격은 messages.py (WebSocket과 같음)
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from messages import MESSAGE_SPECS, ROLES, SAMPLES, MessageError, make_message, validate_message
from mqtt_topics import online_topic, parse_topic, subscriptions_for, topic_for


def show(direction: str, topic: str, message: dict[str, Any] | str) -> None:
    """한 줄로 찍기."""
    if isinstance(message, dict):
        print(f"{direction} {topic:<34} {message.get('type'):<14} from={message.get('from')} to={message.get('to')} "
              f"{json.dumps(message.get('payload'), ensure_ascii=False)}", flush=True)
    else:
        print(f"{direction} {topic:<34} {message}", flush=True)


class MqttTestClient:
    """역할(gui·robot)과 이름으로 브로커에 붙는 시험 클라이언트."""

    def __init__(self, host: str, port: int, role: str, name: str, auto_robot: bool = False) -> None:
        self.role, self.name, self.auto_robot = role, name, auto_robot
        self.connected = threading.Event()
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"{role}-{name}", clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        if role == "robot":   # 끊기면 브로커가 online=0을 대신 보낸다
            self.client.will_set(online_topic(name), "0", qos=1, retain=True)
        self.client.connect(host, port, keepalive=30)
        self.client.loop_start()
        if not self.connected.wait(5):
            raise ConnectionError(f"MQTT broker {host}:{port} did not accept the connection in 5s")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            print(f"접속 실패: {reason_code}", file=sys.stderr)
            return
        client.subscribe(subscriptions_for(self.role, self.name))
        if self.role == "robot":
            client.publish(online_topic(self.name), "1", qos=1, retain=True)
        self.connected.set()

    def _on_message(self, client, userdata, msg) -> None:
        text = msg.payload.decode("utf-8", "replace")
        parsed = parse_topic(msg.topic)
        if parsed and parsed[1] == "online":
            show("<<", msg.topic, f"online={text}")
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            show("<<", msg.topic, f"(JSON 아님) {text[:80]}")
            return
        show("<<", msg.topic, message)
        if self.auto_robot and message.get("type") == "task_assign":
            threading.Thread(target=self._play_task, args=(message,), daemon=True).start()

    def send(self, message_type: str, to: str = "*", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """규격 검사 후 발행. cmd는 받는 로봇(to)의 토픽, status·progress·event는 내 토픽.
        [입력] message_type / to / payload: 없으면 SAMPLES 예시
        [출력] dict: 보낸 메시지 (규격 위반이면 MessageError)
        """
        message = make_message(message_type, payload if payload is not None else dict(SAMPLES.get(message_type, {})),
                               self.name, to)
        validate_message(message, self.role)   # WebSocket 서버가 하던 검사를 보내기 전에
        robot = to if MESSAGE_SPECS[message_type].receivers == ("robot",) else self.name
        topic, qos, retain = topic_for(message_type, robot)
        info = self.client.publish(topic, json.dumps(message, ensure_ascii=False), qos=qos, retain=retain)
        info.wait_for_publish(5)
        show(">>", topic, message)
        return message

    def _play_task(self, assign: dict[str, Any]) -> None:
        """로봇 흉내: 작업 단계 보고를 차례로 (WebSocket client.py와 같은 순서)."""
        task_id = assign["payload"]["task_id"]
        destination = assign["payload"]["destination"]
        reply_to = assign.get("from") or "*"
        self.send("task_progress", reply_to, {"task_id": task_id, "stage": "accepted"})
        for step in range(1, 4):
            time.sleep(1.0)
            self.send("robot_status", "*", {
                "mode": "moving", "battery_percent": 80 - step,
                "x_m": round(destination["x_m"] * step / 3, 3), "y_m": round(destination["y_m"] * step / 3, 3),
                "yaw_rad": destination["yaw_rad"]})
        self.send("task_progress", reply_to, {"task_id": task_id, "stage": "arrived"})
        time.sleep(1.0)
        self.send("task_progress", reply_to, {"task_id": task_id, "stage": "done"})
        self.send("robot_status", "*", {"mode": "idle", "battery_percent": 77, "x_m": destination["x_m"],
                                        "y_m": destination["y_m"], "yaw_rad": destination["yaw_rad"]})

    def close(self) -> None:
        if self.role == "robot":   # 정상 종료는 직접 online=0
            self.client.publish(online_topic(self.name), "0", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()


def interactive(client: MqttTestClient) -> None:
    """표준 입력 명령: send <type> [to] [json] · types · quit"""
    print("명령: send <type> [to] [json payload] · types · quit", flush=True)
    for line in sys.stdin:
        words = line.strip().split(maxsplit=3)
        if not words:
            continue
        if words[0] in ("quit", "exit"):
            return
        if words[0] == "types":
            for message_type, spec in MESSAGE_SPECS.items():
                print(f"  {message_type:<14} {'/'.join(spec.senders)} → {'/'.join(spec.receivers)}  {spec.description}")
            continue
        if words[0] == "send" and len(words) >= 2:
            try:
                payload = json.loads(words[3]) if len(words) == 4 else None
                client.send(words[1], words[2] if len(words) >= 3 else "*", payload)
            except (json.JSONDecodeError, MessageError, KeyError, ValueError) as error:
                print(f"보내지 않음: {error}")
            continue
        print("알 수 없는 명령")


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT 인터페이스 시험 클라이언트")
    parser.add_argument("--broker", default="localhost:1883", help="host:port (기본 localhost:1883)")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--name", required=True, help="이름 (로봇이면 토픽 hospital/robot/<이름>/…)")
    parser.add_argument("--send", choices=sorted(t for t in MESSAGE_SPECS if t in
                                                  ("task_assign", "task_cancel", "robot_status", "task_progress", "robot_event", "alert")))
    parser.add_argument("--to", default="*", help="task_assign·task_cancel이면 받는 로봇 이름 (필수)")
    parser.add_argument("--payload", help="payload JSON (없으면 예시 값)")
    parser.add_argument("--auto", action="store_true", help="로봇 흉내: task_assign을 받으면 단계 보고를 자동으로")
    args = parser.parse_args()
    host, _, port = args.broker.partition(":")
    client = MqttTestClient(host, int(port or 1883), args.role, args.name, auto_robot=args.auto)
    try:
        if args.send:
            try:
                client.send(args.send, args.to, json.loads(args.payload) if args.payload else None)
            except (MessageError, ValueError) as error:
                print(f"보내지 않음: {error}", file=sys.stderr)
                sys.exit(1)
            time.sleep(0.3)
        elif args.auto:
            print(f"로봇 흉내 {args.name}: hospital/robot/{args.name}/cmd 를 기다리는 중 (Ctrl+C로 끝)", flush=True)
            while True:
                time.sleep(1)
        else:
            interactive(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()


if __name__ == "__main__":
    main()
