#!/usr/bin/env python3
# =============================================================================
# 파일   : tools/ws_interface_test/client.py
# 역할   : WebSocket 인터페이스 시험 클라이언트 (터미널) — GUI 또는 로봇 역할로 접속해 규격 메시지를 보내고 받은 것을 찍는다
# 작성일 : 2026-10-22
# 구성   :
#   - 한 번 보내기   --send robot_status [--to '*'] [--payload '{"...": ...}']  → ack/error를 받으면 끝
#   - 대화형         명령: send <type> [to] [json] · types · quit
#   - 로봇 흉내      --role robot --auto : task_assign을 받으면 accepted → 이동 상태 보고 → arrived → done 을 차례로 보냄
# 예: python3 client.py --role robot --name pinky_1 --auto
#     python3 client.py --role gui --name nurse-ui --send task_assign --to pinky_1
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from urllib.parse import quote

from websockets.asyncio.client import ClientConnection, connect

from messages import BROADCAST, MESSAGE_SPECS, ROLES, SAMPLES, make_message


def show(direction: str, message: dict[str, Any]) -> None:
    """받거나 보낸 메시지를 한 줄로 찍는다."""
    print(f"{direction} {message.get('type'):<14} from={message.get('from')} to={message.get('to')} "
          f"{json.dumps(message.get('payload'), ensure_ascii=False)}", flush=True)


async def send(connection: ClientConnection, name: str, message_type: str, to: str = BROADCAST,
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """규격 메시지 보내기 (payload가 없으면 SAMPLES 예시).
    [입력] connection / name: 내 이름 / message_type / to / payload
    [출력] dict: 보낸 메시지
    """
    message = make_message(message_type, payload if payload is not None else dict(SAMPLES.get(message_type, {})), name, to)
    await connection.send(json.dumps(message, ensure_ascii=False))
    show(">>", message)
    return message


async def play_robot_task(connection: ClientConnection, name: str, assign: dict[str, Any]) -> None:
    """로봇 흉내: 작업을 받으면 단계 보고를 차례로 보낸다 (GUI 쪽 화면·알림 시험용).
    [입력] connection / name / assign: 받은 task_assign
    [출력] 없음
    """
    task_id = assign["payload"]["task_id"]
    destination = assign["payload"]["destination"]
    reply_to = assign.get("from") or BROADCAST
    await send(connection, name, "task_progress", reply_to, {"task_id": task_id, "stage": "accepted"})
    for step in range(1, 4):
        await asyncio.sleep(1.0)
        await send(connection, name, "robot_status", BROADCAST, {
            "mode": "moving", "battery_percent": 80 - step,
            "x_m": round(destination["x_m"] * step / 3, 3), "y_m": round(destination["y_m"] * step / 3, 3),
            "yaw_rad": destination["yaw_rad"],
        })
    await send(connection, name, "task_progress", reply_to, {"task_id": task_id, "stage": "arrived"})
    await asyncio.sleep(1.0)
    await send(connection, name, "task_progress", reply_to, {"task_id": task_id, "stage": "done"})
    await send(connection, name, "robot_status", BROADCAST, {
        "mode": "idle", "battery_percent": 77, "x_m": destination["x_m"], "y_m": destination["y_m"],
        "yaw_rad": destination["yaw_rad"]})


async def receive_loop(connection: ClientConnection, name: str, auto_robot: bool, done: asyncio.Event | None,
                       waiting_id: str | None) -> None:
    """받은 메시지를 찍는다. 한 번 보내기면 그 메시지의 ack/error를 받으면 done을 켠다."""
    async for text in connection:
        message = json.loads(text)
        show("<<", message)
        payload = message.get("payload") or {}
        if auto_robot and message.get("type") == "task_assign":
            asyncio.create_task(play_robot_task(connection, name, message))
        answered = (message.get("type") in ("ack", "error") and payload.get("message_id") == waiting_id) or \
            (message.get("type") == "pong" and message.get("id") == waiting_id)   # ping은 ack 대신 같은 id의 pong
        if done is not None and answered:
            done.set()


async def interactive(connection: ClientConnection, name: str) -> None:
    """표준 입력 명령: send <type> [to] [json] · types · quit"""
    loop = asyncio.get_running_loop()
    print("명령: send <type> [to] [json payload] · types · quit", flush=True)
    while True:
        line = (await loop.run_in_executor(None, sys.stdin.readline))
        if not line or line.strip() in ("quit", "exit"):
            return
        words = line.strip().split(maxsplit=3)
        if not words:
            continue
        if words[0] == "types":
            for message_type, spec in MESSAGE_SPECS.items():
                print(f"  {message_type:<14} {'/'.join(spec.senders)} → {'/'.join(spec.receivers)}  {spec.description}")
            continue
        if words[0] == "send" and len(words) >= 2:
            to = words[2] if len(words) >= 3 else BROADCAST
            try:
                payload = json.loads(words[3]) if len(words) == 4 else None
            except json.JSONDecodeError as error:
                print(f"payload JSON 오류: {error}")
                continue
            await send(connection, name, words[1], to, payload)
            continue
        print("알 수 없는 명령")


async def run(args: argparse.Namespace) -> int:
    url = f"{args.url}/?role={quote(args.role)}&name={quote(args.name)}"
    async with connect(url) as connection:
        if args.send:
            payload = json.loads(args.payload) if args.payload else None
            done = asyncio.Event()
            sent = make_message(args.send, payload if payload is not None else dict(SAMPLES.get(args.send, {})),
                                args.name, args.to)
            receiver = asyncio.create_task(receive_loop(connection, args.name, False, done, sent["id"]))
            await connection.send(json.dumps(sent, ensure_ascii=False))
            show(">>", sent)
            try:
                await asyncio.wait_for(done.wait(), timeout=5)
            except TimeoutError:
                print("5초 안에 ack/error가 오지 않았습니다", file=sys.stderr)
                return 1
            finally:
                receiver.cancel()
            return 0
        receiver = asyncio.create_task(receive_loop(connection, args.name, args.auto, None, None))
        if args.auto:
            await receiver   # 로봇 흉내는 끊길 때까지 받기만
        else:
            await interactive(connection, args.name)
            receiver.cancel()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="WebSocket 인터페이스 시험 클라이언트")
    parser.add_argument("--url", default="ws://localhost:8765")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--name", required=True, help="접속 이름 (서버 안에서 유일)")
    parser.add_argument("--send", choices=sorted(MESSAGE_SPECS), help="이 메시지를 한 번 보내고 ack/error를 받으면 끝")
    parser.add_argument("--to", default=BROADCAST, help="받는 클라이언트 이름 (기본 '*' = 받는 역할 전체)")
    parser.add_argument("--payload", help="payload JSON (없으면 예시 값)")
    parser.add_argument("--auto", action="store_true", help="로봇 흉내: task_assign을 받으면 단계 보고를 자동으로")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
