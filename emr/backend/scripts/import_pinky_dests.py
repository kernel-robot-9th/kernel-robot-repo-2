# =============================================================================
# 파일   : scripts/import_pinky_dests.py
# 역할   : 팀원 Pinky API의 목적지(GET /dests)를 EMR 맵·장소로 가져온다 — 다시 돌리면 갱신 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - fetch_pinky()      /dests + 목적지 쌍마다 /plan(경로 계산만, 로봇은 움직이지 않음) → 주행 경로 선분
#   - render_map()       경로를 흰 선으로 그린 PGM(1 cm/px) + map_server yaml — EMR 맵 화면용 개략도
#   - sync_emr()         관리자 로그인 → 맵 "Pinky 아레나" 등록/교체 → 장소 등록/수정(robot_dest 기준) → (선택) 로봇 복귀 장소
# 좌표: Pinky 그림 cm(아레나 왼쪽 아래 원점, heading deg) → EMR 미터·라디안 그대로 환산(x/100, y/100, deg→rad). ROS map 프레임이 아니다
# 표준 라이브러리만 — 호스트에서 바로 돌린다:
#   EMR_PASSWORD=... python3 backend/scripts/import_pinky_dests.py --pinky http://192.168.129.122:8080 --home START_A --robot-id 1
# 계약: docs/api_contract_delivery_2026-10-20.md 4장 · 분석: docs/pinky_fms_api_review_2026-10-22.md
# =============================================================================
from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

MAP_NAME = "Pinky 아레나"
RESOLUTION_M_PER_PIXEL = 0.01      # 1 cm/px — Pinky 그림 단위와 같다
MARGIN_CM = 20
LANE_HALF_WIDTH_PX = 6             # 경로 선 반폭 (로봇 폭 약 12 cm)
FREE, UNKNOWN = 254, 205           # map_server trinary: 흰색 = 빈 곳, 회색 = 모름


def http(method: str, url: str, body: Any = None, headers: dict[str, str] | None = None,
         raw: bytes | None = None) -> tuple[int, Any]:
    """[입력] method / url / body: JSON / headers / raw: 그대로 보낼 바이트 [출력] (상태, JSON 또는 None)"""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={**({"Content-Type": "application/json"} if raw is None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"detail": text[:200]}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        sys.exit(f"연결 실패 {method} {url}: {error} — Pinky를 읽는 단계였다면 EMR은 바뀌지 않았다")


def fetch_pinky(pinky: str) -> tuple[dict[str, Any], list[list[tuple[float, float]]]]:
    """[입력] pinky: API 주소 [출력] (목적지 {이름: {xy, heading, name, dock}}, 경로 선분 목록)"""
    status, dests = http("GET", f"{pinky}/dests")
    if status != 200:
        sys.exit(f"Pinky /dests HTTP {status} {dests}")
    paths: list[list[tuple[float, float]]] = []
    for start_name, start in dests.items():
        start_from = f"{start['xy'][0]},{start['xy'][1]},{start['heading']}"
        for goal_name in dests:
            if goal_name == start_name:
                continue
            query = urllib.parse.urlencode({"dest": goal_name, "from": start_from})
            status, plan = http("GET", f"{pinky}/plan?{query}")
            if status == 200 and plan.get("points"):
                paths.append([tuple(point) for point in plan["points"]])
    return dests, paths


def render_map(dests: dict[str, Any], paths: list[list[tuple[float, float]]]) -> tuple[bytes, dict[str, float], int, int]:
    """경로 선을 흰색으로 그린 PGM. [출력] (PGM 바이트, 원점 {x_m, y_m}, 가로 px, 세로 px)"""
    xs = [x for path in paths for x, _ in path] + [d["xy"][0] for d in dests.values()]
    ys = [y for path in paths for _, y in path] + [d["xy"][1] for d in dests.values()]
    min_x, min_y = min(0.0, min(xs) - MARGIN_CM), min(0.0, min(ys) - MARGIN_CM)
    width, height = int(math.ceil(max(xs) + MARGIN_CM - min_x)), int(math.ceil(max(ys) + MARGIN_CM - min_y))
    pixels = bytearray([UNKNOWN]) * (width * height)

    def stamp(x_cm: float, y_cm: float) -> None:
        column, row = int(round(x_cm - min_x)), height - 1 - int(round(y_cm - min_y))   # 이미지는 y가 아래로
        for d_row in range(-LANE_HALF_WIDTH_PX, LANE_HALF_WIDTH_PX + 1):
            for d_column in range(-LANE_HALF_WIDTH_PX, LANE_HALF_WIDTH_PX + 1):
                if d_row * d_row + d_column * d_column <= LANE_HALF_WIDTH_PX ** 2:
                    r, c = row + d_row, column + d_column
                    if 0 <= r < height and 0 <= c < width:
                        pixels[r * width + c] = FREE

    for path in paths:
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            steps = max(1, int(math.hypot(x1 - x0, y1 - y0)))
            for step in range(steps + 1):
                stamp(x0 + (x1 - x0) * step / steps, y0 + (y1 - y0) * step / steps)
    header = f"P5\n# Pinky arena lanes from /plan (generated)\n{width} {height}\n255\n".encode()
    return header + bytes(pixels), {"x_m": min_x / 100.0, "y_m": min_y / 100.0}, width, height


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """[출력] (본문, Content-Type)"""
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, content, content_type) in files.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                      f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def sync_emr(emr: str, token: str, dests: dict[str, Any], pgm: bytes, origin: dict[str, float],
             home: str | None, robot_id: int | None) -> None:
    """맵·장소·(선택) 복귀 장소를 EMR에 맞춘다."""
    auth = {"Authorization": f"Bearer {token}"}
    yaml = (f"image: pinky_arena.pgm\nresolution: {RESOLUTION_M_PER_PIXEL}\norigin: [{origin['x_m']}, {origin['y_m']}, 0.0]\n"
            "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n").encode()
    files = {"map_yaml": ("pinky_arena.yaml", yaml, "application/x-yaml"), "map_image": ("pinky_arena.pgm", pgm, "image/x-portable-graymap")}
    status, maps = http("GET", f"{emr}/maps", headers=auth)
    existing = next((m for m in maps or [] if m["name"] == MAP_NAME), None)
    if existing:
        body, content_type = multipart({}, files)
        status, saved = http("PUT", f"{emr}/maps/{existing['id']}/files", headers={**auth, "Content-Type": content_type}, raw=body)
        action = "교체"
    else:
        body, content_type = multipart({"name": MAP_NAME}, files)
        status, saved = http("POST", f"{emr}/maps/upload", headers={**auth, "Content-Type": content_type}, raw=body)
        action = "등록"
    if status not in (200, 201):
        sys.exit(f"맵 {action} 실패 HTTP {status} {saved}")
    map_id = saved["id"]
    print(f"맵 {action}: {MAP_NAME} (id {map_id}), {saved.get('image_width_px')}x{saved.get('image_height_px')} px, 1 cm/px")

    status, locations = http("GET", f"{emr}/locations?limit=500", headers=auth)
    by_dest = {l["robot_dest"]: l for l in locations if l.get("robot_dest")}
    by_name = {l["name"]: l for l in locations}
    dest_location_ids: dict[str, int] = {}
    for dest_name, dest in dests.items():
        place = {"name": dest["name"], "map_id": map_id, "map_x_m": round(dest["xy"][0] / 100.0, 4),
                 "map_y_m": round(dest["xy"][1] / 100.0, 4), "map_yaw_rad": round(math.radians(dest["heading"]), 4),
                 "robot_dest": dest_name}
        current = by_dest.get(dest_name) or by_name.get(dest["name"])
        if current:
            status, result = http("PATCH", f"{emr}/locations/{current['id']}", place, auth)
            verb = "수정"
        else:
            status, result = http("POST", f"{emr}/locations", place, auth)
            verb = "등록"
        if status not in (200, 201):
            print(f"  ✗ {dest_name} {verb} 실패 HTTP {status} {result}")
            continue
        dest_location_ids[dest_name] = result["id"]
        print(f"  ✓ 장소 {verb}: {result['name']} (id {result['id']}) ← {dest_name} ({dest['xy'][0]}, {dest['xy'][1]}) cm {dest['heading']}°")
    for location in locations:
        if location.get("robot_dest") and location["robot_dest"] not in dests:
            print(f"  · {location['name']}(id {location['id']})의 robot_dest {location['robot_dest']}는 Pinky에 더는 없음 — 직접 확인")

    if home and robot_id:
        if home not in dest_location_ids:
            sys.exit(f"복귀 목적지 {home}가 Pinky 목적지에 없음")
        status, robot = http("PATCH", f"{emr}/robots/{robot_id}", {"home_location_id": dest_location_ids[home]}, auth)
        print(f"로봇 {robot_id} 복귀 장소 → {home}: HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pinky /dests → EMR 맵·장소 (다시 돌리면 갱신)")
    parser.add_argument("--pinky", default="http://192.168.129.122:8080")
    parser.add_argument("--emr", default="http://localhost:8000/api/v1")
    parser.add_argument("--employee-no", default="N001", help="관리자 사번")
    parser.add_argument("--home", help="로봇 복귀 장소로 쓸 Pinky 목적지 (예: START_A)")
    parser.add_argument("--robot-id", type=int, help="복귀 장소를 바꿀 EMR 로봇 id")
    arguments = parser.parse_args()
    password = os.getenv("EMR_PASSWORD") or getpass.getpass(f"{arguments.employee_no} 비밀번호: ")
    status, login = http("POST", f"{arguments.emr}/auth/login", {"employee_no": arguments.employee_no, "password": password})
    if status != 200:
        sys.exit(f"EMR 로그인 실패 HTTP {status}")
    dests, paths = fetch_pinky(arguments.pinky)
    print(f"Pinky 목적지 {len(dests)}곳, 경로 {len(paths)}개 (/plan 계산만)")
    pgm, origin, width, height = render_map(dests, paths)
    sync_emr(arguments.emr, login["access_token"], dests, pgm, origin, arguments.home, arguments.robot_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
