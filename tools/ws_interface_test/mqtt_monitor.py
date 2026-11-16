#!/usr/bin/env python3
# =============================================================================
# 파일   : tools/ws_interface_test/mqtt_monitor.py
# 역할   : MQTT 규격 감시 — hospital/# 전체를 구독해 모든 메시지를 messages.py 규격으로 검사하고 OK/위반을 찍는다
# 작성일 : 2026-10-22
# 구성   :
#   - check(topic, text)   토픽 칸과 메시지 종류가 맞는지, 보낸 쪽 역할·필수 필드·값 범위(validate_message),
#                          로봇 토픽이면 from이 토픽의 로봇 이름과 같은지 → (ok, 설명)
#   - main                 .venv/bin/python mqtt_monitor.py [--broker localhost:1883] [--log logs/]
# 브로커(Mosquitto)는 내용을 검사하지 않는다. WebSocket 서버가 하던 검사를 이 감시기가 대신 보여 준다(막지는 않음).
# =============================================================================
from __future__ import annotations

import argparse
import json
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from messages import MessageError, now_iso, validate_message
from mqtt_topics import SLOT_SENDER_ROLE, SLOT_TYPES, TOPIC_ROOT, parse_topic


def check(topic: str, text: str) -> tuple[bool, str]:
    """메시지 한 개 검사.
    [입력] topic / text: 페이로드 문자열
    [출력] (규격에 맞는지, 설명 — 위반이면 오류 코드와 이유)
    """
    parsed = parse_topic(topic)
    if parsed is None:
        return False, "unknown_topic: 토픽 규칙(mqtt_topics.py)에 없는 토픽"
    robot, slot = parsed
    if slot == "online":
        return (text in ("0", "1")), f"online={text}" if text in ("0", "1") else "invalid_value: online은 '0' 또는 '1'"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return False, "invalid_json: JSON이 아님"
    message_type = raw.get("type") if isinstance(raw, dict) else None
    if message_type not in SLOT_TYPES[slot]:
        return False, f"wrong_topic: '{message_type}'은 …/{slot} 토픽에 실을 수 없음 (허용 {SLOT_TYPES[slot]})"
    try:
        message = validate_message(raw, SLOT_SENDER_ROLE[slot])
    except MessageError as error:
        return False, f"{error.code}: {error.detail}"
    if slot in ("status", "progress", "event") and message.get("from") != robot:
        return False, f"from_mismatch: 토픽 로봇 '{robot}'인데 from='{message.get('from')}'"
    if slot == "cmd" and message.get("to") not in (robot, "*"):
        return False, f"to_mismatch: 토픽 로봇 '{robot}'인데 to='{message.get('to')}'"
    return True, f"{message_type} from={message.get('from')} to={message.get('to')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT 규격 감시 (hospital/# 전체)")
    parser.add_argument("--broker", default="localhost:1883")
    parser.add_argument("--log", type=Path, default=None, help="검사 결과를 JSONL로 남길 폴더")
    args = parser.parse_args()
    host, _, port = args.broker.partition(":")
    log_file = None
    if args.log:
        args.log.mkdir(parents=True, exist_ok=True)
        log_file = (args.log / f"mqtt_{now_iso()[:10]}.jsonl").open("a", encoding="utf-8")

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(f"{TOPIC_ROOT}/#", qos=1)
        print(f"감시 시작: {host}:{port or 1883} {TOPIC_ROOT}/#", flush=True)

    def on_message(client, userdata, msg):
        text = msg.payload.decode("utf-8", "replace")
        ok, detail = check(msg.topic, text)
        retained = " (retain)" if msg.retain else ""
        print(f"{'OK ' if ok else 'ERR'} {msg.topic}{retained}  {detail}", flush=True)
        if log_file:
            log_file.write(json.dumps({"ts": now_iso(), "topic": msg.topic, "ok": ok, "detail": detail, "payload": text},
                                      ensure_ascii=False) + "\n")
            log_file.flush()

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="interface-monitor")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, int(port or 1883), keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()


if __name__ == "__main__":
    main()
