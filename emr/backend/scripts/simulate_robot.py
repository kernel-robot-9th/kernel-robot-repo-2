# =============================================================================
# 파일   : scripts/simulate_robot.py
# 역할   : 로봇(관제 PC 배송 실행기) 흉내 — 실물 Pinky 없이 배송 흐름(가져가기·도착·수령·실패)과 간호사 화면·알림을 확인한다
# 작성일 : 2026-10-20
# 사용   : 키는 환경변수 EMR_ROBOT_API_KEY 또는 --api-key (셸 기록에 남기지 않으려면 환경변수)
#   python -m scripts.simulate_robot me                         로봇·복귀 장소·맡은 배송
#   python -m scripts.simulate_robot claim                      배송 하나 맡기 (없으면 "맡을 배송 없음")
#   python -m scripts.simulate_robot arrive 12                  도착 보고 → 간호사 화면에 일회용 마커
#   python -m scripts.simulate_robot receipt 12 137             읽은 마커 번호로 수령 확인
#   python -m scripts.simulate_robot fail 12 not_received       실패 보고 (재고 복구)
#   python -m scripts.simulate_robot run --travel-s 5           claim → (이동 흉내) → 도착 → 마커 번호 입력(빈 칸이면 not_received)
# 계약: docs/api_contract_delivery_2026-10-20.md
# =============================================================================
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

FAILURE_REASONS = ("navigation_failed", "not_received", "destination_blocked", "robot_error")


class RobotApi:
    """로봇 전용 API 호출."""

    def __init__(self, api_url: str, api_key: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.headers = {"X-Robot-Api-Key": api_key}

    def call(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        """[입력] method / path: /robot/... / body [출력] httpx.Response"""
        return httpx.request(method, f"{self.api_url}{path}", headers=self.headers, json=body, timeout=10)


def describe(delivery: dict) -> str:
    """로봇용 배송 한 줄 요약.
    [입력] delivery: RobotDeliveryOut JSON
    [출력] str
    """
    destination = delivery["destination"]
    items = ", ".join(f"{item['name']} {item['quantity']}개" for item in delivery["items"])
    deadline = f" · 수령 마감 {delivery['receipt_deadline_at']}" if delivery.get("receipt_deadline_at") else ""
    return (f"배송 {delivery['id']} [{delivery['status']}] → {destination['name']} "
            f"({destination['map_x_m']}, {destination['map_y_m']}) · {items}{deadline}")


def show(response: httpx.Response) -> int:
    """응답 출력.
    [입력] response
    [출력] int: 종료 코드 (2xx면 0)
    """
    if response.status_code == 204:
        print("맡을 배송 없음 (204)")
        return 0
    body = response.json() if response.content else {}
    if response.is_success:
        if "destination" in body:
            print(describe(body))
        else:
            print(json.dumps(body, ensure_ascii=False, indent=1))
        return 0
    print(f"거부됨 HTTP {response.status_code}: {json.dumps(body, ensure_ascii=False)}", file=sys.stderr)
    return 1


def run_once(api: RobotApi, travel_s: float) -> int:
    """배송 하나를 끝까지: claim → 이동 흉내 → 도착 → 마커 번호 입력(빈 칸이면 not_received 실패).
    [입력] api / travel_s: 이동했다고 칠 시간(초)
    [출력] int: 종료 코드
    """
    claimed = api.call("POST", "/robot/deliveries/claim")
    if claimed.status_code != 200:
        return show(claimed)
    delivery = claimed.json()
    print("맡음:", describe(delivery))
    if delivery["status"] == "dispatched":
        print(f"{travel_s:.0f}초 동안 이동하는 척합니다…")
        time.sleep(travel_s)
        arrived = api.call("POST", f"/robot/deliveries/{delivery['id']}/progress", {"stage": "arrived"})
        if show(arrived):
            return 1
    marker_text = input("간호사 화면의 수령 마커 번호 (빈 칸이면 미수령 실패): ").strip()
    if not marker_text:
        return show(api.call("POST", f"/robot/deliveries/{delivery['id']}/progress",
                             {"stage": "failed", "failure_reason": "not_received"}))
    return show(api.call("POST", f"/robot/deliveries/{delivery['id']}/receipt", {"aruco_marker_id": int(marker_text)}))


def main() -> int:
    """[입력] 명령줄 [출력] 종료 코드"""
    parser = argparse.ArgumentParser(description="로봇(배송 실행기) 흉내 — EMR 로봇 API 시험")
    parser.add_argument("--api-key", default=os.getenv("EMR_ROBOT_API_KEY"), help="로봇 API 키 (기본: $EMR_ROBOT_API_KEY)")
    parser.add_argument("--api-url", default=os.getenv("EMR_API_URL", "http://localhost:8000/api/v1"), help="EMR API 주소")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("me", help="로봇·복귀 장소·맡은 배송")
    commands.add_parser("claim", help="배송 하나 맡기")
    arrive = commands.add_parser("arrive", help="도착 보고")
    arrive.add_argument("delivery_id", type=int)
    receipt = commands.add_parser("receipt", help="수령 확인")
    receipt.add_argument("delivery_id", type=int)
    receipt.add_argument("marker", type=int, help="일회용 마커 번호 (50~249)")
    fail = commands.add_parser("fail", help="실패 보고")
    fail.add_argument("delivery_id", type=int)
    fail.add_argument("reason", choices=FAILURE_REASONS)
    run = commands.add_parser("run", help="배송 하나를 끝까지")
    run.add_argument("--travel-s", type=float, default=5.0, help="이동 흉내 시간 (기본 5초)")
    arguments = parser.parse_args()
    if not arguments.api_key:
        parser.error("--api-key 또는 EMR_ROBOT_API_KEY가 필요합니다")

    api = RobotApi(arguments.api_url, arguments.api_key)
    if arguments.command == "me":
        return show(api.call("GET", "/robot/me"))
    if arguments.command == "claim":
        return show(api.call("POST", "/robot/deliveries/claim"))
    if arguments.command == "arrive":
        return show(api.call("POST", f"/robot/deliveries/{arguments.delivery_id}/progress", {"stage": "arrived"}))
    if arguments.command == "receipt":
        return show(api.call("POST", f"/robot/deliveries/{arguments.delivery_id}/receipt", {"aruco_marker_id": arguments.marker}))
    if arguments.command == "fail":
        return show(api.call("POST", f"/robot/deliveries/{arguments.delivery_id}/progress",
                             {"stage": "failed", "failure_reason": arguments.reason}))
    return run_once(api, arguments.travel_s)


if __name__ == "__main__":
    sys.exit(main())
