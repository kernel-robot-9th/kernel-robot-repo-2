"""Pinky API 주행기 — 가짜 Pinky API(HTTP 서버, 같은 프로세스)로. 실제 로봇은 부르지 않는다 (2026-10-22).
실행: PYTHONPATH=. python3 -m pytest -q test
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from delivery_executor.pinky_api import PinkyApiClient, PinkyApiNavigator, parse_dests

ROOM_301 = {"id": 3, "name": "301호"}
PHARMACY = {"id": 1, "name": "비품실"}
UNKNOWN = {"id": 99, "name": "없는 곳"}
DESTS = parse_dests({3: "ROOM1_CUL", 1: {"dest": "PHARMACY", "dock": True}})


class FakePinky:
    """GET /status · POST /goto · GET /jobs/{id} · POST /cancel 흉내. job은 polls_to_finish번 조회하면 끝 상태가 된다."""

    def __init__(self):
        self.localized = True
        self.busy_goto_count = 0          # 처음 이만큼 goto는 409
        self.unknown_dests = {"NOPE"}
        self.final_state = "succeeded"
        self.here = "START_A"             # 지금 서 있는 목적지 — /plan 구간 0개
        self.polls_to_finish = 2
        self.gotos: list[dict] = []
        self.cancels = 0
        self.jobs: dict[str, dict] = {}

    def handle(self, method: str, path: str, body: dict | None) -> tuple[int, dict]:
        if method == "GET" and path == "/status":
            running = any(job["state"] == "running" for job in self.jobs.values())
            return 200, {"localized": self.localized, "nav2_ready": True, "state": "running" if running else "idle", "job": None}
        if method == "GET" and path.startswith("/plan?"):
            dest = path.split("dest=", 1)[1].split("&", 1)[0]
            if dest in self.unknown_dests:
                return 400, {"error": "없음"}
            return 200, {"length_cm": 0.0 if dest == self.here else 100.0,
                         "segments": [] if dest == self.here else [{"mode": "nav"}]}
        if method == "POST" and path == "/goto":
            self.gotos.append(body)
            if body.get("dest") in self.unknown_dests:
                return 400, {"error": f"그래프에 \"{body['dest']}\" 없음"}
            if self.busy_goto_count > 0:
                self.busy_goto_count -= 1
                return 409, {"error": "다른 작업 중"}
            job_id = f"job{len(self.gotos)}"
            self.jobs[job_id] = {"id": job_id, "state": "running", "polls": 0}
            return 202, {"job": {"id": job_id, "state": "running"}, "plan": {}}
        if method == "GET" and path.startswith("/jobs/"):
            job = self.jobs.get(path.rsplit("/", 1)[-1])
            if job is None:
                return 404, {"error": "없음"}
            job["polls"] += 1
            if job["state"] == "running" and job["polls"] >= self.polls_to_finish:
                job["state"] = self.final_state
            results = [{"segment": 1, "status": "ok" if job["state"] != "failed" else "blocked", "why": "장애물"}]
            return 200, {**job, "results": results, "end_error_cm": 2.1}
        if method == "POST" and path == "/cancel":
            self.cancels += 1
            for job in self.jobs.values():
                if job["state"] == "running":
                    job["state"] = "canceled"
            return 200, {"canceled": None, "state": "idle"}
        return 404, {"error": "no route"}


@pytest.fixture
def pinky():
    fake = FakePinky()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, payload = fake.handle(method, self.path, body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield fake
    server.shutdown()


def navigator_for(pinky, **options):
    return PinkyApiNavigator(PinkyApiClient(pinky.url), DESTS, **options)


def drive(navigator, place, max_polls=2000):
    """start → 끝날 때까지 poll (실행기 반복 흉내). [출력] 결과 | None(max_polls까지 안 끝남)"""
    handle = navigator.start(place)
    for _ in range(max_polls):
        result = navigator.poll(handle)
        if result is not None:
            return result
        time.sleep(0.002)
    return None


def test_parse_dests():
    assert DESTS == {3: {"dest": "ROOM1_CUL", "dock": False}, 1: {"dest": "PHARMACY", "dock": True}}


def test_goto_dest_and_wait_until_succeeded(pinky):
    assert drive(navigator_for(pinky), ROOM_301) == "succeeded"
    assert pinky.gotos == [{"dest": "ROOM1_CUL", "dock": False}]   # 좌표가 아니라 목적지 이름만 보낸다


def test_dock_option_is_sent(pinky):
    drive(navigator_for(pinky), PHARMACY)
    assert pinky.gotos[-1] == {"dest": "PHARMACY", "dock": True}


def test_unmapped_place_does_not_call_goto(pinky):
    assert drive(navigator_for(pinky), UNKNOWN) == "no_route" and pinky.gotos == []


def test_pinky_refuses_destination(pinky):
    navigator = PinkyApiNavigator(PinkyApiClient(pinky.url), parse_dests({3: "NOPE"}))
    assert drive(navigator, ROOM_301) == "no_route"


def test_job_failed_is_aborted(pinky):
    pinky.final_state = "failed"
    assert drive(navigator_for(pinky), ROOM_301) == "aborted"


def test_busy_waits_then_starts(pinky):
    pinky.busy_goto_count = 2
    assert drive(navigator_for(pinky), ROOM_301) == "succeeded" and len(pinky.gotos) == 3


def test_busy_too_long(pinky):
    pinky.busy_goto_count = 1000
    assert drive(navigator_for(pinky, busy_wait_s=0.05), ROOM_301) == "busy"


def test_start_does_not_wait_and_cancel_stops_job(pinky):
    """비동기: start()는 goto만 보내고 바로 돌아온다. cancel()은 그 작업만 멈춘다."""
    pinky.polls_to_finish = 10_000
    navigator = navigator_for(pinky)
    navigator.cancel_current()
    assert pinky.cancels == 0                       # 실행기가 시작한 작업이 없으면 /cancel을 부르지 않는다
    handle = navigator.start(ROOM_301)
    assert handle.job_id is not None and navigator.poll(handle) is None   # 가는 중
    navigator.cancel_current()                      # 실행기 종료
    assert pinky.cancels == 1 and navigator.poll(handle) == "canceled"


def test_not_ready_reason(pinky):
    navigator = navigator_for(pinky)
    assert navigator.not_ready_reason() is None
    pinky.localized = False
    assert "위치 모름" in navigator.not_ready_reason()
    assert "연결 실패" in PinkyApiNavigator(PinkyApiClient("http://127.0.0.1:9"), DESTS).not_ready_reason()


def test_long_job_keeps_polling_without_time_limit(pinky):
    """제한 시간은 실행기 반복(logic)이 본다 — 주행기는 끝날 때까지 None을 주며 취소하지 않는다."""
    pinky.polls_to_finish = 30
    assert drive(navigator_for(pinky), ROOM_301) == "succeeded" and pinky.cancels == 0


def test_already_at_destination_skips_goto(pinky):
    """이미 그 목적지에 있으면(/plan 구간 0개) goto 없이 도착 — 복귀 장소에서 다시 복귀할 때 멈추지 않게."""
    navigator = PinkyApiNavigator(PinkyApiClient(pinky.url), parse_dests({2: "START_A"}))
    assert drive(navigator, {"id": 2, "name": "간호사스테이션"}) == "succeeded" and pinky.gotos == []


def test_robot_dest_from_emr_place(pinky):
    """EMR 장소의 robot_dest(2026-10-22, 0011)로 간다 — 설정 dests 표가 없어도. 표가 있으면 표가 먼저(정밀 주차 덮어쓰기)."""
    navigator = PinkyApiNavigator(PinkyApiClient(pinky.url), {})
    assert drive(navigator, {"id": 20, "name": "수술실", "robot_dest": "SURGERY"}) == "succeeded"
    assert pinky.gotos[-1] == {"dest": "SURGERY", "dock": False}
    assert drive(navigator_for(pinky), {"id": 1, "name": "약제실 OMX", "robot_dest": "PHARMACY"}) == "succeeded"
    assert pinky.gotos[-1] == {"dest": "PHARMACY", "dock": True}
