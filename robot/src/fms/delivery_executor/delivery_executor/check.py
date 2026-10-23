# =============================================================================
# 파일   : delivery_executor/check.py
# 역할   : 연결 점검 (ros2 run delivery_executor executor --check) — 로봇을 움직이지 않고 EMR·Pinky API 연결과 설정을 확인 (2026-10-22)
# 작성일 : 2026-10-22
# 구성   :
#   - check_robot()   로봇 한 대: EMR 키·로봇 id·복귀 장소 / Pinky /status·/dests / dests 표 ↔ EMR 장소 / 목적지별 경로(/plan, 계산만)
# GET만 부른다(EMR /robot/me·/locations, Pinky /status·/dests·/plan). POST /goto·/cancel은 부르지 않는다
# =============================================================================
from __future__ import annotations

from typing import Any, Callable

from delivery_executor.emr_client import EmrUnavailable, RobotEmrClient
from delivery_executor.pinky_api import PinkyApiClient, PinkyUnavailable, parse_dests


def check_robot(name: str, robot: dict[str, Any], emr: RobotEmrClient, say: Callable[[str], None] = print) -> int:
    """[입력] name / robot: 설정의 로봇 한 대 / emr / say: 한 줄 출력 [출력] int: 문제 수 (0이면 배송을 맡을 수 있음)"""
    problems = 0

    def bad(message: str) -> None:
        nonlocal problems
        problems += 1
        say(f"  ✗ {message}")

    say(f"[{name}]")
    # ---- EMR ----
    try:
        me = emr.me()
    except EmrUnavailable as error:
        bad(f"EMR 연결 실패: {error}")
        return problems
    if me.status != 200:
        bad(f"EMR /robot/me HTTP {me.status} {me.code} — 키 파일 확인")
        return problems
    body = me.body
    if body["robot"]["id"] != int(robot["emr_robot_id"]):
        bad(f"키가 다른 로봇 것: EMR {body['robot']['id']}({body['robot']['name']}), 설정 {robot['emr_robot_id']}")
    else:
        say(f"  ✓ EMR 키: {body['robot']['name']} (id {body['robot']['id']})")
    home = body.get("home_location")
    if home is None:
        bad("EMR 복귀 장소 없음 — 장소·맵·로봇 화면 → 로봇 탭에서 지정")
    else:
        say(f"  ✓ 복귀 장소: {home['name']} (id {home['id']})")
    active = body.get("active_delivery")
    say(f"  · 맡고 있는 배송: {active['id']} {active['status']} → {active['destination']['name']}" if active else "  · 맡고 있는 배송: 없음")

    if robot.get("navigation", "ros") != "pinky_api":
        say("  · navigation: ros — Pinky API 점검은 건너뜀")
        return problems

    # ---- Pinky API ----
    client = PinkyApiClient(robot["pinky_api"])
    try:
        status = client.status()
        dest_list = client.request("GET", "/dests")
    except PinkyUnavailable as error:
        bad(f"Pinky API 연결 실패: {error}")
        return problems
    if status.status != 200:
        bad(f"Pinky /status HTTP {status.status} {status.error}")
        return problems
    state = status.body
    pose = state.get("pose") or {}
    say(f"  · Pinky {robot['pinky_api']}: 위치 ({pose.get('x')}, {pose.get('y')}) cm, heading {pose.get('heading')}°, {state.get('state')}")
    if not state.get("localized"):
        bad("로봇 위치 모름 — Pinky /set_pose")
    if not state.get("nav2_ready"):
        bad("Pinky Nav2 준비 안 됨")
    if state.get("state") != "idle":
        say(f"  · 지금 다른 작업 중({(state.get('job') or {}).get('id')}) — 끝나야 배송을 맡는다")
    names = set(dest_list.body or {}) if dest_list.status == 200 else set()
    if dest_list.status != 200:
        bad(f"Pinky /dests HTTP {dest_list.status}")

    # ---- EMR 장소의 robot_dest(+ 설정 dests 덮어쓰기) ↔ Pinky 목적지 ----
    locations = emr.request("GET", "/locations?limit=500", authenticated=False)
    by_id = {location["id"]: location for location in (locations.body or [])} if locations.status == 200 else {}
    dests = {location_id: {"dest": location["robot_dest"], "dock": False}
             for location_id, location in by_id.items() if location.get("robot_dest")}
    dests.update(parse_dests(robot.get("dests")))   # 설정 표가 먼저
    blocked = {int(location_id) for location_id in robot.get("blocked_location_ids") or []}
    for location_id, target in sorted(dests.items()):
        label = by_id.get(location_id, {}).get("name", f"EMR에 없는 장소 {location_id}")
        if names and target["dest"] not in names:
            bad(f"{label} → {target['dest']}: Pinky 목적지에 없음 (GET /dests: {', '.join(sorted(names))})")
            continue
        try:
            plan = client.plan(target)
        except PinkyUnavailable as error:
            bad(f"{label} → {target['dest']}: 경로 계산 실패 {error}")
            continue
        if plan.status != 200:
            bad(f"{label} → {target['dest']}: 경로 없음 HTTP {plan.status} {plan.error}")
            continue
        modes = "·".join(segment["mode"] for segment in plan.body.get("segments") or [])
        say(f"  ✓ {label}(id {location_id}) → {target['dest']}{' (정밀 주차)' if target['dock'] else ''}: 지금 위치에서 {plan.body.get('length_cm')} cm [{modes}]")
    if home is not None and home["id"] not in dests:
        bad(f"복귀 장소 {home['name']}(id {home['id']})에 로봇 목적지가 없음 — 배송 뒤 복귀하지 못하고 멈춘다")
    home_map = home["map_id"] if home else None
    for location in by_id.values():
        if location["id"] in dests or location["id"] in blocked or location.get("map_x_m") is None:
            continue
        if location.get("map_id") == home_map:
            say(f"  · {location['name']}(id {location['id']})에 로봇 목적지 없음 — 이리로 오는 배송은 움직이지 않고 destination_blocked")
    say(f"  {'→ 배송을 맡을 수 있습니다' if problems == 0 else f'→ 문제 {problems}개'}")
    return problems
