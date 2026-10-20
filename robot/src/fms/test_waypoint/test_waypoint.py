#!/usr/bin/env python3
# =============================================================================
# 파일   : test_waypoint.py
# 역할   : EMR에 찍은 장소를 웨이포인트로 Pinky를 차례로 이동시킨다 (실물 주행 시험용)
#          EMR(GET /api/v1/locations, 로그인 불필요)에서 장소 좌표를 읽고,
#          Pinky Nav2 웹서버(pinky_navigation/scripts/nav2_web_server.py, :8080)의 HTTP API로 목표를 보낸다
# 작성일 : 2026-10-20
# 구성   :
#   - Waypoint / select_waypoints()   EMR 장소 목록 → 이름 순서대로 웨이포인트 (모르는 이름·좌표 없음·맵 섞임은 출발 전 거부)
#   - compare_maps()                  EMR 맵과 로봇 Nav2 맵(해상도·원점·크기)이 같은지 — 다르면 좌표가 엉뚱한 곳을 가리킨다
#   - distance_to_goal_m() / angle_difference_rad()   도착 판정
#   - PinkyWebClient                  /api/state · /api/nav/status · /api/goal · /api/nav/stop
#   - run_waypoints()                 목표 보내기 → 주행 끝 대기 → 위치로 도착 판정 → 머무르기, 제한 시간·Ctrl+C면 정지
#   - main()                          명령행
# 표준 라이브러리만 쓴다 — 이 PC든 로봇이든 python3만 있으면 돈다. ROS를 import하지 않는다.
#
# 웹서버 API의 한계 (그래서 이렇게 판정한다):
#   /api/goal은 목표를 보내기만 하고 성공·실패 결과를 주지 않는다. /api/nav/status는 주행 중인지(navigating)만 준다.
#   → 주행이 끝나면 /api/state의 현재 위치(map→base_link TF)가 목표에서 arrive_tolerance_m 안인지로 도착을 판정한다.
#   → Nav2가 목표를 거부하면 navigating이 꺼지지 않을 수 있다 → 웨이포인트마다 제한 시간(timeout_s) 뒤 정지.
# =============================================================================
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_EMR_URL = "http://localhost:8000/api/v1"   # 이 PC에서 돌릴 때. 로봇에서 돌리면 http://<EMR PC IP>:8000/api/v1
DEFAULT_ROBOT_URL = "http://192.168.4.1:8080"      # Pinky 기본 AP 주소 (pinky_pro README). 공유기에 붙였으면 그 IP
DEFAULT_ARRIVE_TOLERANCE_M = 0.35   # Nav2 xy_goal_tolerance 0.25 m보다 조금 넓게 (TF 갱신 지연 여유)
DEFAULT_TIMEOUT_S = 120.0           # 웨이포인트 하나당 최대 주행 시간 — 넘으면 정지하고 멈춘다
DEFAULT_WAIT_S = 3.0                # 도착 후 머무르는 시간
POLL_INTERVAL_S = 0.5               # /api/nav/status 확인 간격 (/api/state는 맵 전체가 실려 무거워 도착 판정 때만 부른다)
HTTP_TIMEOUT_S = 5.0

MAP_RESOLUTION_TOLERANCE = 1e-6     # m/px
MAP_ORIGIN_TOLERANCE_M = 0.005      # yaml 소수 자릿수 차이 정도만 허용
MAP_YAW_TOLERANCE_RAD = 0.001


class WaypointError(Exception):
    """출발 전에 막아야 하는 문제 (이름 없음, 좌표 없음, 맵 불일치 등)."""


@dataclass(frozen=True)
class Waypoint:
    name: str
    x_m: float
    y_m: float
    yaw_rad: float
    map_id: int


@dataclass
class WaypointResult:
    name: str
    arrived: bool
    distance_m: float | None      # 주행이 끝난 뒤 목표까지 남은 거리 (위치를 못 읽었으면 None)
    heading_error_rad: float | None
    elapsed_s: float
    message: str


# ---- 순수 함수 (테스트 대상) --------------------------------------------------

def select_waypoints(locations: list[dict[str, Any]], names: list[str]) -> list[Waypoint]:
    """EMR 장소 목록에서 이름 순서대로 웨이포인트를 고른다. 같은 이름을 여러 번 적어도 된다(왕복).
    [입력] locations: GET /locations 응답 / names: 갈 순서대로 장소 이름
    [출력] list[Waypoint] (모르는 이름·좌표 없는 장소·서로 다른 맵이면 WaypointError)
    """
    if not names:
        raise WaypointError("갈 장소 이름을 하나 이상 적어 주세요.")
    by_name = {location["name"]: location for location in locations}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        available = ", ".join(sorted(by_name)) or "(없음)"
        raise WaypointError(f"EMR에 없는 장소: {', '.join(unknown)} — 있는 장소: {available}")

    waypoints = []
    for name in names:
        location = by_name[name]
        if location.get("map_id") is None or location.get("map_x_m") is None:
            raise WaypointError(f"'{name}'은(는) 맵 좌표가 없습니다. EMR 맵 화면에서 위치를 먼저 찍어 주세요.")
        waypoints.append(Waypoint(
            name=name, x_m=float(location["map_x_m"]), y_m=float(location["map_y_m"]),
            yaw_rad=float(location["map_yaw_rad"]), map_id=int(location["map_id"]),
        ))
    map_ids = {waypoint.map_id for waypoint in waypoints}
    if len(map_ids) > 1:
        raise WaypointError(f"장소들이 서로 다른 맵에 있습니다(map_id {sorted(map_ids)}). 한 맵의 장소만 고르세요.")
    return waypoints


def compare_maps(emr_map: dict[str, Any], robot_map: dict[str, Any] | None) -> list[str]:
    """EMR 맵과 로봇 Nav2 맵이 같은 파일에서 나왔는지 해상도·원점·크기로 비교한다.
    [입력] emr_map: EMR 맵(GET /maps/{id}) / robot_map: /api/state의 map ({width,height,resolution,origin{x,y,yaw}}) 또는 None
    [출력] list[str]: 다른 점 (빈 목록이면 같음)
    """
    if robot_map is None:
        return ["로봇이 아직 맵을 받지 못했습니다(Nav2 map_server가 떠 있는지 확인)."]
    problems = []
    if abs(float(robot_map["resolution"]) - float(emr_map["resolution_m_per_pixel"])) > MAP_RESOLUTION_TOLERANCE:
        problems.append(f"해상도 EMR {emr_map['resolution_m_per_pixel']} / 로봇 {robot_map['resolution']} m/px")
    origin = robot_map["origin"]
    for axis, emr_key in (("x", "origin_x_m"), ("y", "origin_y_m")):
        if abs(float(origin[axis]) - float(emr_map[emr_key])) > MAP_ORIGIN_TOLERANCE_M:
            problems.append(f"원점 {axis} EMR {emr_map[emr_key]} / 로봇 {origin[axis]:.3f} m")
    if abs(angle_difference_rad(float(origin["yaw"]), float(emr_map["origin_yaw_rad"]))) > MAP_YAW_TOLERANCE_RAD:
        problems.append(f"원점 방향 EMR {emr_map['origin_yaw_rad']} / 로봇 {origin['yaw']:.3f} rad")
    if emr_map.get("image_width_px") is not None:
        emr_size = (int(emr_map["image_width_px"]), int(emr_map["image_height_px"]))
        robot_size = (int(robot_map["width"]), int(robot_map["height"]))
        if emr_size != robot_size:
            problems.append(f"크기 EMR {emr_size[0]}x{emr_size[1]} / 로봇 {robot_size[0]}x{robot_size[1]} px")
    return problems


def angle_difference_rad(first_rad: float, second_rad: float) -> float:
    """두 각의 차이를 -π~π로.
    [입력] first_rad, second_rad
    [출력] float: first - second (라디안, 가장 짧은 쪽)
    """
    return math.atan2(math.sin(first_rad - second_rad), math.cos(first_rad - second_rad))


def distance_to_goal_m(pose: dict[str, float], waypoint: Waypoint) -> float:
    """현재 위치와 목표 사이 평면 거리.
    [입력] pose: {x, y, yaw} (map 프레임) / waypoint
    [출력] float: 미터
    """
    return math.hypot(float(pose["x"]) - waypoint.x_m, float(pose["y"]) - waypoint.y_m)


# ---- HTTP --------------------------------------------------------------------

def request_json(method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = HTTP_TIMEOUT_S) -> Any:
    """JSON HTTP 요청.
    [입력] method / url / body: 보낼 JSON (없으면 None) / timeout_s
    [출력] 응답 JSON (연결 실패·HTTP 오류는 urllib 예외 그대로)
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        text = response.read().decode("utf-8")
    return json.loads(text) if text else None


class PinkyWebClient:
    """Pinky Nav2 웹서버(nav2_web_server.py) HTTP API."""

    def __init__(self, robot_url: str) -> None:
        self.robot_url = robot_url.rstrip("/")

    def state(self) -> dict[str, Any]:
        """[출력] {map, pose{x,y,yaw}|None, path, ..., is_navigating} — map.data가 실려 무겁다"""
        return request_json("GET", f"{self.robot_url}/api/state", timeout_s=15.0)

    def is_navigating(self) -> bool:
        """[출력] Nav2 navigate_to_pose 목표가 수락·실행 중인가"""
        return bool(request_json("GET", f"{self.robot_url}/api/nav/status")["navigating"])

    def send_goal(self, waypoint: Waypoint) -> bool:
        """[입력] waypoint [출력] 웹서버가 Nav2 액션 서버에 목표를 보냈는가 (Nav2의 수락 여부는 아님)"""
        response = request_json("POST", f"{self.robot_url}/api/goal",
                                {"x": waypoint.x_m, "y": waypoint.y_m, "yaw": waypoint.yaw_rad})
        return bool(response.get("success"))

    def stop(self) -> bool:
        """[출력] 모든 주행 목표 취소 요청이 나갔는가"""
        return bool(request_json("POST", f"{self.robot_url}/api/nav/stop", {}).get("success"))


# ---- 실행 --------------------------------------------------------------------

def wait_until_stopped(robot: PinkyWebClient, timeout_s: float,
                       sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> bool:
    """주행이 끝날(navigating=False) 때까지 기다린다.
    [입력] robot / timeout_s / sleep·clock: 테스트에서 바꿔 끼움
    [출력] bool: 제한 시간 안에 끝났으면 True
    """
    deadline = clock() + timeout_s
    while clock() < deadline:
        if not robot.is_navigating():
            return True
        sleep(POLL_INTERVAL_S)
    return False


def run_waypoints(robot: PinkyWebClient, waypoints: list[Waypoint], arrive_tolerance_m: float, timeout_s: float,
                  wait_s: float, stop_on_miss: bool = True, log: Callable[[str], None] = print,
                  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> list[WaypointResult]:
    """웨이포인트를 차례로 간다. 제한 시간을 넘기면 정지하고 끝낸다. 도착 못 하면 stop_on_miss면 끝낸다.
    [입력] robot / waypoints / arrive_tolerance_m / timeout_s / wait_s / stop_on_miss / log·sleep·clock
    [출력] list[WaypointResult]: 시도한 웨이포인트까지
    """
    results: list[WaypointResult] = []
    for index, waypoint in enumerate(waypoints, start=1):
        log(f"[{index}/{len(waypoints)}] {waypoint.name} → x={waypoint.x_m:+.2f} y={waypoint.y_m:+.2f} m, "
            f"yaw={math.degrees(waypoint.yaw_rad):+.0f}°")
        started_at = clock()
        if not robot.send_goal(waypoint):
            results.append(WaypointResult(waypoint.name, False, None, None, 0.0,
                                          "웹서버가 목표를 보내지 못함 (Nav2 navigate_to_pose 액션 서버 없음)"))
            log(f"   실패: {results[-1].message}")
            break
        sleep(POLL_INTERVAL_S)   # 웹서버가 navigating=True로 바꾼 뒤 Nav2 상태 토픽이 따라오게 잠깐 둔다
        if not wait_until_stopped(robot, timeout_s, sleep=sleep, clock=clock):
            robot.stop()
            results.append(WaypointResult(waypoint.name, False, None, None, clock() - started_at,
                                          f"{timeout_s:.0f}초 안에 주행이 끝나지 않아 정지시킴 (목표 거부·막힘 의심)"))
            log(f"   실패: {results[-1].message}")
            break

        elapsed_s = clock() - started_at
        pose = robot.state().get("pose")
        if pose is None:
            result = WaypointResult(waypoint.name, False, None, None, elapsed_s, "주행은 끝났지만 로봇 위치를 읽지 못함 (TF map→base_link)")
        else:
            distance_m = distance_to_goal_m(pose, waypoint)
            heading_error_rad = angle_difference_rad(float(pose["yaw"]), waypoint.yaw_rad)
            arrived = distance_m <= arrive_tolerance_m
            message = "도착" if arrived else f"목표에서 {distance_m:.2f} m 떨어진 곳에서 멈춤 (Nav2 실패·취소 의심)"
            result = WaypointResult(waypoint.name, arrived, distance_m, heading_error_rad, elapsed_s, message)
        results.append(result)
        detail = (f"남은 거리 {result.distance_m:.2f} m, 방향 오차 {math.degrees(result.heading_error_rad):+.0f}°, "
                  if result.distance_m is not None and result.heading_error_rad is not None else "")
        log(f"   {result.message} ({detail}{result.elapsed_s:.0f}초)")
        if not result.arrived and stop_on_miss:
            break
        if index < len(waypoints) and wait_s > 0:
            sleep(wait_s)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EMR 장소를 웨이포인트로 Pinky를 이동합니다 (Pinky Nav2 웹서버 HTTP).",
        epilog="예) python3 test_waypoint.py 비품실 301호 302호 간호사스테이션 --robot http://192.168.4.1:8080",
    )
    parser.add_argument("names", nargs="*", help="갈 장소 이름(EMR), 적은 순서대로. 같은 이름 반복 가능")
    parser.add_argument("--emr", default=DEFAULT_EMR_URL, help=f"EMR API 주소 (기본 {DEFAULT_EMR_URL})")
    parser.add_argument("--robot", default=DEFAULT_ROBOT_URL, help=f"Pinky 웹서버 주소 (기본 {DEFAULT_ROBOT_URL})")
    parser.add_argument("--list", action="store_true", help="EMR 장소 목록만 보고 끝")
    parser.add_argument("--dry-run", action="store_true", help="검사와 이동 계획만 보여 주고 움직이지 않음")
    parser.add_argument("--yes", action="store_true", help="출발 확인(y/N)을 묻지 않음")
    parser.add_argument("--skip-map-check", action="store_true", help="EMR 맵과 로봇 맵 비교를 건너뜀 (위험)")
    parser.add_argument("--continue-on-miss", action="store_true", help="한 곳에 도착 못 해도 다음 장소로 계속")
    parser.add_argument("--arrive-tolerance-m", type=float, default=DEFAULT_ARRIVE_TOLERANCE_M,
                        help=f"도착으로 볼 거리 (기본 {DEFAULT_ARRIVE_TOLERANCE_M} m)")
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S, help=f"장소 하나당 최대 주행 시간 (기본 {DEFAULT_TIMEOUT_S:.0f}초)")
    parser.add_argument("--wait-s", type=float, default=DEFAULT_WAIT_S, help=f"도착 후 머무는 시간 (기본 {DEFAULT_WAIT_S:.0f}초)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """[입력] argv [출력] 종료 코드: 0 모두 도착 · 1 도착 못 함/중단 · 2 출발 전 거부"""
    args = build_parser().parse_args(argv)
    emr_url = args.emr.rstrip("/")

    try:
        locations = request_json("GET", f"{emr_url}/locations")
    except (urllib.error.URLError, OSError) as error:
        print(f"EMR에 연결하지 못했습니다 ({emr_url}): {error}", file=sys.stderr)
        return 2
    if args.list or not args.names:
        print("EMR 장소 (이름 · 맵 · x, y m · yaw°):")
        for location in sorted(locations, key=lambda item: (item.get("map_id") or 0, item["id"])):
            if location.get("map_x_m") is None:
                print(f"  {location['name']} · 좌표 없음")
            else:
                print(f"  {location['name']} · 맵 {location['map_id']} · {location['map_x_m']:+.2f}, {location['map_y_m']:+.2f}"
                      f" · {math.degrees(location['map_yaw_rad']):+.0f}°")
        return 0 if args.list else 2

    try:
        waypoints = select_waypoints(locations, args.names)
        emr_map = request_json("GET", f"{emr_url}/maps/{waypoints[0].map_id}")
    except WaypointError as error:
        print(f"출발하지 않음: {error}", file=sys.stderr)
        return 2
    print(f"EMR 맵: {emr_map['name']} ({emr_map['file_name']}, {emr_map['resolution_m_per_pixel']} m/px, "
          f"원점 {emr_map['origin_x_m']}, {emr_map['origin_y_m']})")

    robot = PinkyWebClient(args.robot)
    try:
        robot_state = robot.state()
    except (urllib.error.URLError, OSError) as error:
        print(f"Pinky 웹서버에 연결하지 못했습니다 ({args.robot}): {error}", file=sys.stderr)
        print("  로봇에서: ros2 launch pinky_navigation web_nav2.launch.xml map:=<map_rev2.yaml 경로>", file=sys.stderr)
        if not args.dry_run:
            return 2
        robot_state = None

    if robot_state is not None:
        problems = [] if args.skip_map_check else compare_maps(emr_map, robot_state.get("map"))
        if problems:
            print("출발하지 않음: 로봇이 쓰는 맵이 EMR 맵과 다릅니다 → 장소 좌표가 엉뚱한 곳을 가리킵니다.", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 2
        pose = robot_state.get("pose")
        if pose is None:
            print("출발하지 않음: 로봇 위치가 없습니다(map→base_link TF). AMCL 초기 위치를 먼저 잡아 주세요.", file=sys.stderr)
            return 2
        print(f"로봇 위치: x={pose['x']:+.2f} y={pose['y']:+.2f} m, yaw={math.degrees(pose['yaw']):+.0f}° · "
              f"맵 {'비교 건너뜀' if args.skip_map_check else '일치'}")

    print("이동 계획:")
    for index, waypoint in enumerate(waypoints, start=1):
        print(f"  {index}. {waypoint.name}: x={waypoint.x_m:+.2f} y={waypoint.y_m:+.2f} m, yaw={math.degrees(waypoint.yaw_rad):+.0f}°")
    if args.dry_run:
        print("--dry-run: 움직이지 않고 끝냅니다.")
        return 0
    if not args.yes and input("로봇이 실제로 움직입니다. 주변을 비웠으면 y: ").strip().lower() != "y":
        print("취소했습니다.")
        return 1

    try:
        results = run_waypoints(robot, waypoints, args.arrive_tolerance_m, args.timeout_s, args.wait_s,
                                stop_on_miss=not args.continue_on_miss)
    except KeyboardInterrupt:
        print("\nCtrl+C — 정지 명령을 보냅니다.")
        robot.stop()
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"주행 중 로봇 연결이 끊겼습니다: {error} — 정지 명령을 시도합니다.", file=sys.stderr)
        try:
            robot.stop()
        except (urllib.error.URLError, OSError):
            print("정지 명령도 보내지 못했습니다. 로봇을 직접 멈춰 주세요.", file=sys.stderr)
        return 1

    arrived_count = sum(result.arrived for result in results)
    print(f"결과: {arrived_count}/{len(waypoints)}곳 도착")
    return 0 if arrived_count == len(waypoints) else 1


if __name__ == "__main__":
    sys.exit(main())
