"""배송 실행 상태 기계 — 가짜 EMR·주행기·마커로 (ROS·네트워크 없이). 실행: PYTHONPATH=. python3 -m pytest -q test"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from delivery_executor.emr_client import EmrResponse, EmrUnavailable
from delivery_executor.logic import DeliveryWorker, WorkerSettings, compare_maps

HOME = {"id": 2, "name": "간호사스테이션", "map_id": 4, "map_x_m": -0.6, "map_y_m": -1.55, "map_yaw_rad": 0.0}
ROOM_301 = {"id": 3, "name": "301호", "map_id": 4, "map_x_m": 0.26, "map_y_m": -0.92, "map_yaw_rad": 0.0}
SUPPLY_ROOM = {"id": 1, "name": "비품실", "map_id": 4, "map_x_m": 0.44, "map_y_m": -1.55, "map_yaw_rad": 1.65}
EMR_MAP = {"id": 4, "name": "병원", "resolution_m_per_pixel": 0.02, "origin_x_m": -1.801, "origin_y_m": -6.847,
           "origin_yaw_rad": 0.0, "image_width_px": 271, "image_height_px": 359}
ROBOT_MAP = {"width": 271, "height": 359, "resolution": 0.02, "origin": {"x": -1.801, "y": -6.847, "yaw": 0.0}}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def iso(self, offset_s=0.0):
        return datetime.fromtimestamp(self.now + offset_s, tz=timezone.utc).isoformat()


def delivery(status="dispatched", destination=ROOM_301, delivery_id=12, deadline=None):
    return {"id": delivery_id, "status": status, "destination": destination, "items": [{"name": "A 약품", "quantity": 1}],
            "scheduled_at": "2026-10-20T02:59:00Z", "dispatched_at": "2026-10-20T03:00:00Z", "arrived_at": None,
            "receipt_deadline_at": deadline}


class FakeEmr:
    """실제 EMR처럼 맡은 배송(active)을 따라간다: claim·도착이면 그 배송, 수령·실패면 없음.
    button_received_after_s: 도착하고 이만큼 지나면 병상 "받았습니다" 버튼이 눌린 것으로 친다 (/robot/me의 active가 사라짐)."""

    def __init__(self, clock, claims=(), active=None, home=HOME, robot_id=1, marker=137, receipt_after_failed_code=None,
                 button_received_after_s=None):
        self.clock = clock
        self.claims = list(claims)
        self.active = active
        self.home = home
        self.robot_id = robot_id
        self.marker = marker
        self.receipt_after_failed_code = receipt_after_failed_code
        self.button_received_after_s = button_received_after_s
        self.arrived_at = None
        self.calls: list[tuple] = []

    def me(self):
        self.calls.append(("me",))
        if (self.button_received_after_s is not None and self.arrived_at is not None
                and self.clock() - self.arrived_at >= self.button_received_after_s):
            self.active = None   # 병상에서 "받았습니다"
        return EmrResponse(200, {"robot": {"id": self.robot_id, "name": "배송로봇 1호", "robot_type": "amr"},
                                 "home_location": self.home, "active_delivery": self.active, "receipt_wait_seconds": 300})

    def claim(self):
        self.calls.append(("claim",))
        if not self.claims:
            return EmrResponse(204, None)
        self.active = self.claims.pop(0)
        return EmrResponse(200, self.active)

    def progress(self, delivery_id, stage, failure_reason=None):
        self.calls.append(("progress", delivery_id, stage, failure_reason))
        if stage == "failed" and self.receipt_after_failed_code:
            return EmrResponse(409, {"code": self.receipt_after_failed_code})
        if stage == "arrived":
            self.arrived_at = self.clock()
            self.active = delivery("arrived", delivery_id=delivery_id, deadline=self.clock.iso(300))
            return EmrResponse(200, self.active)
        self.active = None
        return EmrResponse(200, delivery("failed", delivery_id=delivery_id))

    def receipt(self, delivery_id, aruco_marker_id):
        self.calls.append(("receipt", delivery_id, aruco_marker_id))
        if aruco_marker_id == self.marker:
            self.active = None
            return EmrResponse(200, delivery("received", delivery_id=delivery_id))
        return EmrResponse(403, {"code": "receipt_marker_not_for_delivery"})

    def get_map(self, map_id):
        self.calls.append(("get_map", map_id))
        return EmrResponse(200, EMR_MAP)


class FakeNavigator:
    def __init__(self, results=None, robot_map=ROBOT_MAP):
        self.results = list(results or [])
        self.goals: list[tuple] = []
        self.map = robot_map

    def navigate(self, x_m, y_m, yaw_rad, timeout_s):
        self.goals.append((x_m, y_m, yaw_rad))
        return self.results.pop(0) if self.results else "succeeded"

    def robot_map(self, wait_s):
        return self.map


class FakeMarkers:
    """wait_marker가 불릴 때마다 정해진 순서로 번호를 준다(None이면 timeout만큼 시간이 흐른다)."""

    def __init__(self, clock, sequence=()):
        self.clock = clock
        self.sequence = list(sequence)
        self.cleared = 0

    def wait_marker(self, timeout_s):
        if self.sequence:
            value = self.sequence.pop(0)
            if value is not None:
                return value
        self.clock.sleep(timeout_s)
        return None

    def clear(self):
        self.cleared += 1


def make_worker(emr, navigator, markers, clock, **settings):
    options = {"emr_robot_id": 1, "blocked_location_ids": frozenset({1})} | settings
    return DeliveryWorker("pinky_1", emr, navigator, markers, WorkerSettings(**options), sleep=clock.sleep, clock=clock)


def stages(emr):
    return [call[1:] for call in emr.calls if call[0] in ("progress", "receipt")]


# ---- 정상·실패 흐름 -------------------------------------------------------------

def test_full_delivery_received_then_home():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()])
    navigator = FakeNavigator()
    worker = make_worker(emr, navigator, FakeMarkers(clock, [None, 99, 137]), clock)
    state = worker.run(max_cycles=3)   # 준비 → 배송 1건 → 204
    assert stages(emr) == [(12, "arrived", None), (12, 99), (12, 137)]
    assert navigator.goals == [(0.26, -0.92, 0.0), (-0.6, -1.55, 0.0)]   # 301호 → 간호사스테이션
    assert state.finished == [(12, "received")] and state.phase == "stopped"


def test_bedside_button_receipt_is_noticed_through_robot_me():
    """병상 배송 (2026-10-22): 마커 없이 EMR에서 "받았습니다" → 대기 중 /robot/me에 맡은 배송이 없어지면 수령으로 보고 복귀."""
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()], button_received_after_s=10)
    navigator = FakeNavigator()
    state = make_worker(emr, navigator, FakeMarkers(clock), clock).run(max_cycles=3)
    assert stages(emr) == [(12, "arrived", None)]                      # 마커 보고도, 실패 보고도 없다
    assert state.finished == [(12, "received")]
    assert navigator.goals[-1] == (-0.6, -1.55, 0.0)                   # 복귀
    assert sum(1 for call in emr.calls if call[0] == "me") >= 2        # 대기 중 확인 (시작 1번 + 대기 중)


def test_not_received_after_deadline_fails_and_returns_home():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()])
    navigator = FakeNavigator()
    state = make_worker(emr, navigator, FakeMarkers(clock), clock).run(max_cycles=2)
    assert stages(emr) == [(12, "arrived", None), (12, "failed", "not_received")]
    assert navigator.goals[-1] == (-0.6, -1.55, 0.0)
    assert state.finished == [(12, "failed:not_received")]


def test_navigation_failure_reports_and_returns_home():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()])
    navigator = FakeNavigator(results=["aborted", "succeeded"])
    state = make_worker(emr, navigator, FakeMarkers(clock), clock).run(max_cycles=2)
    assert stages(emr) == [(12, "failed", "navigation_failed")]
    assert len(navigator.goals) == 2 and state.phase == "stopped"


def test_blocked_destination_fails_without_moving():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery(destination=SUPPLY_ROOM)])
    navigator = FakeNavigator()
    state = make_worker(emr, navigator, FakeMarkers(clock), clock).run(max_cycles=2)
    assert stages(emr) == [(12, "failed", "destination_blocked")]
    assert navigator.goals == []   # 비품실(모방학습 중)로는 한 발짝도 움직이지 않는다
    assert state.finished == [(12, "failed:destination_blocked")]


def test_failed_report_after_receipt_counts_as_received():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()], receipt_after_failed_code="delivery_already_received")
    state = make_worker(emr, FakeNavigator(), FakeMarkers(clock), clock).run(max_cycles=2)
    assert state.finished == [(12, "received")]


def test_same_marker_is_sent_at_most_once_per_debounce_window():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()], marker=137)
    # 틀린 99를 카메라가 연달아 읽어도 3초에 한 번만 보낸다
    markers = FakeMarkers(clock, [99, 99, 99, None, None, None, 99, 137])
    make_worker(emr, FakeNavigator(), markers, clock).run(max_cycles=2)
    assert [call for call in stages(emr) if call[1] == 99] == [(12, 99), (12, 99)]
    assert markers.cleared == 1   # 도착 직전에 쌓인 번호를 버렸다


def test_home_navigation_failure_halts():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery(), delivery(delivery_id=13)])
    navigator = FakeNavigator(results=["succeeded", "aborted"])   # 301호 OK, 복귀 실패
    state = make_worker(emr, navigator, FakeMarkers(clock, [137]), clock).run(max_cycles=5)
    assert state.phase == "halted" and "복귀 주행 실패" in state.halted_reason
    assert [call for call in emr.calls if call[0] == "claim"] == [("claim",)]   # 멈춘 뒤 다음 배송을 맡지 않는다


# ---- 준비·복구 ---------------------------------------------------------------

def test_resume_arrived_delivery_waits_remaining_time():
    clock = Clock()
    active = delivery("arrived", deadline=clock.iso(10))   # 남은 10초
    emr = FakeEmr(clock, active=active)
    navigator = FakeNavigator()
    state = make_worker(emr, navigator, FakeMarkers(clock), clock).run(max_cycles=1)
    assert stages(emr) == [(12, "failed", "not_received")]
    assert navigator.goals == [(-0.6, -1.55, 0.0)]   # 주행 없이 기다리다 복귀
    assert state.phase == "stopped"


def test_resume_dispatched_delivery_drives_again():
    clock = Clock()
    emr = FakeEmr(clock, active=delivery("dispatched"))
    navigator = FakeNavigator()
    make_worker(emr, navigator, FakeMarkers(clock, [137]), clock).run(max_cycles=1)
    assert navigator.goals[0] == (0.26, -0.92, 0.0) and (12, 137) in stages(emr)


def test_waits_while_home_is_not_set():
    clock = Clock()
    emr = FakeEmr(clock, home=None, claims=[delivery()])
    state = make_worker(emr, FakeNavigator(), FakeMarkers(clock), clock).run(max_cycles=3)
    assert ("claim",) not in emr.calls and state.phase == "stopped"


def test_map_mismatch_blocks_claims():
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()])
    other_map = {"width": 82, "height": 63, "resolution": 0.05, "origin": {"x": -2.05, "y": -1.62, "yaw": 0.0}}
    make_worker(emr, FakeNavigator(robot_map=other_map), FakeMarkers(clock), clock).run(max_cycles=3)
    assert ("claim",) not in emr.calls


def test_key_for_other_robot_halts():
    clock = Clock()
    state = make_worker(FakeEmr(clock, robot_id=3), FakeNavigator(), FakeMarkers(clock), clock).run(max_cycles=3)
    assert state.phase == "halted" and "다른 로봇" in state.halted_reason


def test_emr_unavailable_is_retried():
    clock = Clock()
    emr = FakeEmr(clock)
    attempts = {"count": 0}
    original_me = emr.me

    def flaky_me():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise EmrUnavailable("connection refused")
        return original_me()
    emr.me = flaky_me
    state = make_worker(emr, FakeNavigator(), FakeMarkers(clock), clock).run(max_cycles=3)
    assert attempts["count"] == 2 and state.phase == "stopped"


@pytest.mark.parametrize("robot_map, problem_count", [
    (ROBOT_MAP, 0),
    ({**ROBOT_MAP, "origin": {"x": -1.8012, "y": -6.847, "yaw": 0.0}}, 0),
    ({"width": 82, "height": 63, "resolution": 0.05, "origin": {"x": -2.05, "y": -1.62, "yaw": 0.0}}, 4),
    (None, 1),
])
def test_compare_maps(robot_map, problem_count):
    assert len(compare_maps(EMR_MAP, robot_map)) == problem_count


def test_stop_during_navigation_does_not_report_failure():
    """실행기를 멈추느라 취소된 주행은 실패로 보고하지 않는다 — 배송은 dispatched로 남아 다음 시작 때 이어서."""
    clock = Clock()
    emr = FakeEmr(clock, claims=[delivery()])
    worker = make_worker(emr, None, FakeMarkers(clock), clock)

    class StoppingNavigator(FakeNavigator):
        def navigate(self, x_m, y_m, yaw_rad, timeout_s):
            self.goals.append((x_m, y_m, yaw_rad))
            worker.stop_event.set()   # 주행 중 Ctrl+C
            return "canceled"
    navigator = StoppingNavigator()
    worker.navigator = navigator
    state = worker.run(max_cycles=5)
    assert stages(emr) == [] and len(navigator.goals) == 1 and state.phase == "stopped"
