"""데모 촬영 전 점검 (2026-11-02) — 읽기만 한다. 로봇·로봇팔·EMR 데이터를 바꾸지 않는다.

EMR(:8000)·EMR 설정·팀원 FMS(:8770)·팀원 OMX가 데모(시나리오 ① 여러 병동 신청 → 묶음 배송)를 찍을 수 있는 상태인지 본다.
python3 tools/demo/preflight.py [--wards 12:3:1,20:5:1]   → 문제가 없으면 종료 코드 0
env FMS (기본 http://127.0.0.1:8770), OMX (기본 http://10.42.0.147:8000), EMR (기본 http://127.0.0.1:8000)
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

EMR = os.environ.get("EMR", "http://127.0.0.1:8000")
FMS = os.environ.get("FMS", "http://127.0.0.1:8770")
OMX = os.environ.get("OMX", "http://10.42.0.147:8000")
ACTIVE = ("reserved", "preparing", "dispatched", "arrived")
EXPECTED_ENV = {"FMS_OMX_ENABLED": "1", "OMX_COMMAND_FORMAT": "fixed", "FMS_PHARMACY_SIGNAL": "fms"}

results = []


def check(ok, label, detail=""):
    results.append(ok)
    print(f"{'✔' if ok else '✘'} {label}" + (f" — {detail}" if detail else ""))


def get(url):
    with urllib.request.urlopen(url, timeout=4) as response:
        return json.loads(response.read() or b"null")


def sql(query):
    out = subprocess.run(["docker", "exec", "emr-db-1", "psql", "-U", "emr", "-d", "emr", "-Atc", query],
                         capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return out.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wards", default="12:3:1,20:5:1", help="장소id:비품id:개수, … (기본 105호 C 약품 1 · 103호 이불 1)")
    wards = [tuple(int(v) for v in w.split(":")) for w in parser.parse_args().wards.split(",")]

    print("== EMR")
    try:
        get(f"{EMR}/api/v1/robots")
        check(True, "EMR api 응답", EMR)
    except Exception as error:
        check(False, "EMR api 응답", str(error)[:120])
    try:
        env = subprocess.run(["docker", "exec", "emr-api-1", "printenv", *EXPECTED_ENV], capture_output=True, text=True, timeout=10).stdout.split()
        actual = dict(zip(EXPECTED_ENV, env))
        check(actual == EXPECTED_ENV, "EMR 설정 (실물 OMX · 시연 명령 blue 1·green 1)", ", ".join(f"{k}={v}" for k, v in actual.items()))
    except Exception as error:
        check(False, "EMR 설정 읽기", str(error)[:120])
    try:
        active = sql(f"select count(*) from deliveries where status in ({','.join(repr(s) for s in ACTIVE)})")
        check(active == "0", "진행 중인 신청 없음", f"{active}건")
        for location_id, supply_id, quantity in wards:
            row = sql(f"select l.name, l.robot_dest, s.name, s.category, s.stock_qty from locations l, supplies s where l.id={location_id} and s.id={supply_id}")
            name, room, supply, category, stock = row.split("|")
            check(int(stock) >= quantity and bool(room), f"신청 {name}({room}) · {supply} ×{quantity}", f"{category}, 재고 {stock}")
        categories = {sql(f"select category from supplies where id={w[1]}") for w in wards}
        check(categories == {"medication", "supply"}, "약품 1종 + 비품 1종", "OMX 시연 명령이 늘 blue 1·green 1이라 맞춰 두면 화면과 실제가 같다")
    except Exception as error:
        check(False, "EMR DB 읽기", str(error)[:120])

    print("== FMS (실물 Pinky)")
    try:
        state = get(f"{FMS}/api/v1/state")
        control = get(f"{FMS}/api/state")
        check(not control.get("paused"), "FMS 멈춤 아님", f"paused={control.get('paused')}")
        check(not state["orders"] and not state["batches"], "FMS 주문·묶음 비어 있음", f"주문 {len(state['orders'])} · 묶음 {len(state['batches'])}")
        for robot in state["robots"]:
            fault = robot.get("fault")
            ready = robot["online"] and not fault and robot["state"] == "idle"
            detail = f"{robot['state']} · {robot.get('task')} · {robot.get('place')}"
            if fault:
                detail += f" · 오류 {fault.get('code')} {fault.get('edge') or fault.get('node') or ''}"
            check(ready, f"로봇 {robot['robot']} {robot['name']}", detail)
    except Exception as error:
        check(False, "FMS 응답", str(error)[:120])

    print("== OMX (실물 로봇팔)")
    try:
        status = get(f"{OMX}/status")
        safety = status.get("safety") or {}
        check(status.get("state") == "idle" and not status.get("pinky"), "OMX 대기", f"state={status.get('state')} pinky={status.get('pinky')}")
        check(not safety.get("paused"), "OMX 안전 정지 아님", f"reason={safety.get('reason')} person={safety.get('person_exist')}")
    except Exception as error:
        check(False, "OMX 응답", str(error)[:120])
    print("  · 파란 거즈 1개·녹색 거즈 1개가 왼팔 카메라 작업 영역에 있는지는 눈으로 확인한다(/detection은 명령 뒤에만 채워진다)")

    bad = results.count(False)
    print(f"\n{'준비됨' if bad == 0 else f'고칠 것 {bad}개'}")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
