"""데모 자막·기록 (2026-11-02) — 1초마다 EMR 신청(DB 읽기)·FMS 로봇·OMX 상태를 읽어 자막 파일을 쓴다. 읽기만 한다.

시나리오 ① 여러 병동 신청 → 묶음 배송. 시작할 때 가장 큰 신청 번호보다 큰 신청을 이번 데모로 본다.
자막이 바뀔 때 timeline.log에 한 줄, 상태가 바뀔 때 state.jsonl에 한 줄. 끝나면 summary.md(신청별 단계 시각).
python3 caption.py <caption_file> <stop_file> <out_dir> --wards 12:3:1,20:5:1 [--timeout-min 30]
끝: 이번 신청이 모두 수령·실패·취소 → 마지막 자막을 10초 보이고 종료 0. STOP 파일 → 1, 시간 초과 → 2.
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime

FMS = os.environ.get("FMS", "http://127.0.0.1:8770")
OMX = os.environ.get("OMX", "http://10.42.0.147:8000")
STAGE = {"reserved": "신청", "preparing": "준비", "dispatched": "출발", "arrived": "도착", "received": "받음",
         "failed": "실패", "cancelled": "취소"}
ORDER = ["reserved", "preparing", "dispatched", "arrived", "received"]
DONE = {"received", "failed", "cancelled"}


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read() or b"null")
    except Exception as error:   # 끊겨도 자막·기록은 이어 간다
        return {"_error": str(error)[:100]}


def sql(query):
    out = subprocess.run(["docker", "exec", "emr-db-1", "psql", "-U", "emr", "-d", "emr", "-Atc", query],
                         capture_output=True, text=True, timeout=10)
    return out.stdout.strip()


def deliveries_after(baseline):
    query = f"""select coalesce(json_agg(x order by x.id), '[]') from (
      select d.id, d.status, d.failure_reason, l.name as room, r.name as robot,
             (select string_agg(s.name || ' ' || i.quantity || '개', ', ') from delivery_items i join supplies s on s.id = i.supply_id
              where i.delivery_id = d.id) as items
      from deliveries d join locations l on l.id = d.destination_location_id left join robots r on r.id = d.assigned_robot_id
      where d.id > {baseline}) x"""
    try:
        return json.loads(sql(query) or "[]")
    except ValueError:
        return []


def headline(deliveries, robots, omx, wards_text, expected):
    """지금 가장 앞선 단계의 자막 첫 줄."""
    if len(deliveries) < expected:
        return f"간호사가 물품을 신청합니다 — {wards_text} (한 번에 두 병동)" if expected == 2 else f"간호사가 물품을 신청합니다 — {wards_text}"
    statuses = {d["status"] for d in deliveries}
    if statuses <= DONE:
        failed = [d for d in deliveries if d["status"] == "failed"]
        if failed:
            return "끝 — " + ", ".join(f"{d['room']} 실패({d['failure_reason']})" for d in failed)
        return f"끝 — {len(deliveries)}개 병동 모두 받았습니다"
    arrived = [d for d in deliveries if d["status"] == "arrived"]
    if arrived:
        return f"⑦ {', '.join(d['room'] for d in arrived)} 도착 — 간호사 화면에 '받아 주세요' → '받았습니다'를 누르면 끝"
    if "dispatched" in statuses or "received" in statuses:
        return "⑥ 출발 — 탑재가 끝나 로봇이 병실을 차례로 돕니다 (병실에서 한 바퀴 = 배송 완료)"
    busy = next((r for r in robots if r.get("batch_id")), None)
    robot_text = f"로봇 {busy['robot']}호({busy['name']})" if busy else "로봇"
    pinky = omx.get("pinky")
    if busy and busy.get("state") == "loading" or pinky in ("releasing", "returning"):
        return f"⑤ 탑재 — OMX가 {robot_text} 위에 물품을 내려놓습니다"
    if busy and busy.get("state") == "docking":
        return f"④ {robot_text} 약제실 정밀 주차"
    if pinky in ("grabbing", "holding") or (busy and busy.get("state") in ("moving", "waiting")):
        return f"③ 적재 끝 → {robot_text} 호출 — 약제실로 갑니다 (OMX는 물품을 들고 기다림)"
    if "preparing" in statuses:
        return f"② 준비 — FMS가 두 병동을 {robot_text}에 한 묶음으로 배차 · OMX가 카메라(YOLO)로 거즈를 찾아 집습니다"
    return f"① 신청 접수 — EMR이 FMS에 주문을 보냅니다 (물품 1개 = 주문 1건)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("caption_file")
    parser.add_argument("stop_file")
    parser.add_argument("out_dir")
    parser.add_argument("--wards", required=True)
    parser.add_argument("--timeout-min", type=float, default=30)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    wards = [tuple(int(v) for v in w.split(":")) for w in args.wards.split(",")]
    names = []
    for location_id, supply_id, quantity in wards:
        names.append(sql(f"select l.name || ' ' || s.name || ' ' || {quantity} || '개' from locations l, supplies s where l.id={location_id} and s.id={supply_id}"))
    wards_text = ", ".join(names)
    baseline = int(sql("select coalesce(max(id), 0) from deliveries") or 0)

    timeline = open(os.path.join(args.out_dir, "timeline.log"), "a", encoding="utf-8")
    state_log = open(os.path.join(args.out_dir, "state.jsonl"), "a", encoding="utf-8")
    start = time.time()
    first_seen = {}       # (신청, 단계) → 처음 본 시각
    last_caption, last_state, done_since = None, None, None
    exit_code = 2
    while time.time() - start < args.timeout_min * 60:
        if os.path.exists(args.stop_file):
            exit_code = 1
            break
        now = datetime.now().strftime("%H:%M:%S")
        deliveries = deliveries_after(baseline)
        fms = get(f"{FMS}/api/v1/state")
        robots = fms.get("robots", []) if isinstance(fms, dict) else []
        omx = get(f"{OMX}/status")
        for d in deliveries:
            first_seen.setdefault((d["id"], d["status"]), now)
        line1 = headline(deliveries, robots, omx, wards_text, len(wards))
        line2 = "  |  ".join(f"NO {d['id']} {d['room']} {d['items']} — {STAGE.get(d['status'], d['status'])}" for d in deliveries)
        faults = [f"로봇 {r['robot']}호 멈춤: {r['fault'].get('code')}" for r in robots if r.get("fault")]
        caption = "\n".join(x for x in (line1, line2, "  ".join(faults)) if x)
        if caption != last_caption:
            with open(args.caption_file, "w", encoding="utf-8") as f:
                f.write(caption)
            timeline.write(f"{now} {caption.replace(chr(10), ' / ')}\n")
            timeline.flush()
            last_caption = caption
        state = {"deliveries": [(d["id"], d["status"], d["robot"]) for d in deliveries],
                 "robots": [(r.get("robot"), r.get("state"), r.get("task"), r.get("place"), r.get("batch_id"), (r.get("fault") or {}).get("code")) for r in robots],
                 "omx": (omx.get("state"), omx.get("phase"), omx.get("request_id"), omx.get("pinky"), (omx.get("safety") or {}).get("reason"))}
        if state != last_state:
            state_log.write(json.dumps({"t": now, **state}, ensure_ascii=False) + "\n")
            state_log.flush()
            last_state = state
        if len(deliveries) >= len(wards) and {d["status"] for d in deliveries} <= DONE:
            done_since = done_since or time.time()
            if time.time() - done_since >= 10:
                exit_code = 0
                break
        time.sleep(1)

    deliveries = deliveries_after(baseline)
    rows = ["| NO | 병실 | 물품 | 로봇 | " + " | ".join(STAGE[s] for s in ORDER) + " | 결과 |", "|---" * (len(ORDER) + 5) + "|"]
    for d in deliveries:
        times = " | ".join(first_seen.get((d["id"], s), "") for s in ORDER)
        rows.append(f"| {d['id']} | {d['room']} | {d['items']} | {d['robot'] or ''} | {times} | {STAGE.get(d['status'], d['status'])} |")
    with open(os.path.join(args.out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# 데모 녹화 기록 — {datetime.now():%Y-%m-%d} (시나리오 ① 여러 병동 신청 → 묶음 배송)\n\n")
        f.write(f"- 신청: {wards_text}\n- 끝난 이유: {['모두 끝남', 'STOP 파일', '시간 초과'][exit_code]}\n")
        f.write(f"- 걸린 시간: {int(time.time() - start) // 60}분 {int(time.time() - start) % 60}초 (녹화 시작부터)\n\n")
        f.write("## 신청별 단계를 처음 본 시각 (1초마다 읽음)\n\n" + "\n".join(rows) + "\n\n")
        f.write("자막 순서는 `timeline.log`, 상태 변화는 `state.jsonl`, 화면 조작은 `ui_actions.log`.\n")
    print(json.dumps({"exit": exit_code, "ids": [d["id"] for d in deliveries]}))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
