# =============================================================================
# 파일   : scripts/confirm_receipt.py
# 역할   : 수령 확인 API 시험 호출 — 로봇 카메라 대신 마커 번호를 보내 본다 (배송 전체 흐름은 scripts/simulate_robot.py)
# 작성일 : 2026-10-19
# 사용   : python -m scripts.confirm_receipt --delivery-id 3 --marker 137 --api-key emr_rk_...
#          마커는 도착 알림에 뜬 일회용 번호(50~249). 배송이 arrived이고 이 키의 로봇이 맡은 것이어야 한다 (2026-10-20)
#          (키는 환경변수 EMR_ROBOT_API_KEY로도 줄 수 있다 — 셸 기록에 남기지 않으려면 이쪽)
# =============================================================================
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    """인자를 받아 POST /robot/deliveries/{id}/receipt를 부르고 결과를 출력한다.
    [입력] 명령줄 인자
    [출력] int: 종료 코드 (성공 0, 거부·오류 1)
    """
    parser = argparse.ArgumentParser(description="배송 수령 확인 API 시험 호출 (로봇 대신)")
    parser.add_argument("--delivery-id", type=int, required=True, help="배송 예약 id")
    parser.add_argument("--marker", type=int, required=True, help="읽은 ArUco DICT_4X4_250 일회용 마커 번호 (50~249)")
    parser.add_argument("--api-key", default=os.getenv("EMR_ROBOT_API_KEY"), help="로봇 API 키 (기본: $EMR_ROBOT_API_KEY)")
    parser.add_argument("--api-url", default=os.getenv("EMR_API_URL", "http://localhost:8000/api/v1"), help="EMR API 주소")
    arguments = parser.parse_args()
    if not arguments.api_key:
        parser.error("--api-key 또는 EMR_ROBOT_API_KEY가 필요합니다")

    response = httpx.post(
        f"{arguments.api_url}/robot/deliveries/{arguments.delivery_id}/receipt",
        headers={"X-Robot-Api-Key": arguments.api_key},
        json={"aruco_marker_id": arguments.marker},
        timeout=10,
    )
    body = response.json() if response.content else {}
    if response.is_success:
        print(f"수령 확인됨: 배송 {body['id']} · {body['destination']['name']} · 상태 {body['status']}")
        return 0
    print(f"거부됨 HTTP {response.status_code}: {json.dumps(body, ensure_ascii=False)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
