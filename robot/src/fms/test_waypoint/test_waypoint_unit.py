"""test_waypoint 단위 테스트 — 네트워크·로봇 없이 돈다. 실행: python3 -m pytest -q test_waypoint_unit.py"""
from __future__ import annotations

import math

import pytest

from test_waypoint import (Waypoint, WaypointError, angle_difference_rad, compare_maps, distance_to_goal_m,
                           run_waypoints, select_waypoints)

EMR_MAP = {"id": 4, "name": "병원", "file_name": "map_rev2.yaml", "resolution_m_per_pixel": 0.02,
           "origin_x_m": -1.801, "origin_y_m": -6.847, "origin_yaw_rad": 0.0, "image_width_px": 271, "image_height_px": 359}
LOCATIONS = [
    {"id": 1, "name": "비품실", "map_x_m": 0.44, "map_y_m": -1.55, "map_yaw_rad": 1.65, "map_id": 4},
    {"id": 3, "name": "301호", "map_x_m": 0.26, "map_y_m": -0.92, "map_yaw_rad": 0.0, "map_id": 4},
    {"id": 5, "name": "좌표없음", "map_x_m": None, "map_y_m": None, "map_yaw_rad": None, "map_id": None},
    {"id": 6, "name": "다른맵", "map_x_m": 1.0, "map_y_m": 1.0, "map_yaw_rad": 0.0, "map_id": 2},
]


def robot_map(**overrides):
    base = {"width": 271, "height": 359, "resolution": 0.02, "origin": {"x": -1.801, "y": -6.847, "yaw": 0.0}}
    base.update(overrides)
    return base


def test_select_keeps_order_and_repeats():
    waypoints = select_waypoints(LOCATIONS, ["301호", "비품실", "301호"])
    assert [waypoint.name for waypoint in waypoints] == ["301호", "비품실", "301호"]
    assert waypoints[1] == Waypoint("비품실", 0.44, -1.55, 1.65, 4)


@pytest.mark.parametrize("names, fragment", [
    ([], "하나 이상"),
    (["없는방"], "EMR에 없는 장소"),
    (["좌표없음"], "맵 좌표가 없습니다"),
    (["비품실", "다른맵"], "서로 다른 맵"),
])
def test_select_rejects_before_moving(names, fragment):
    with pytest.raises(WaypointError, match=fragment):
        select_waypoints(LOCATIONS, names)


def test_compare_maps_same_and_different():
    assert compare_maps(EMR_MAP, robot_map()) == []
    assert compare_maps(EMR_MAP, robot_map(origin={"x": -1.8012, "y": -6.847, "yaw": 0.0})) == []  # yaml 반올림 정도는 허용
    problems = compare_maps(EMR_MAP, robot_map(resolution=0.05, width=82, origin={"x": -2.05, "y": -1.62, "yaw": 0.0}))
    assert len(problems) == 4 and any("해상도" in problem for problem in problems)
    assert compare_maps(EMR_MAP, None) and "맵을 받지" in compare_maps(EMR_MAP, None)[0]


def test_angle_and_distance():
    assert angle_difference_rad(math.radians(179), math.radians(-179)) == pytest.approx(math.radians(-2))
    assert distance_to_goal_m({"x": 0.44, "y": -1.25, "yaw": 0.0}, Waypoint("비품실", 0.44, -1.55, 0.0, 4)) == pytest.approx(0.30)


class FakeRobot:
    """웹서버 흉내. navigating_plans: 웨이포인트마다 is_navigating이 돌려줄 값 순서. poses: 주행 끝 위치."""

    def __init__(self, navigating_plans, poses, send_ok=True):
        self.navigating_plans = [list(plan) for plan in navigating_plans]
        self.poses = list(poses)
        self.send_ok = send_ok
        self.goals: list[Waypoint] = []
        self.stop_calls = 0

    def send_goal(self, waypoint):
        self.goals.append(waypoint)
        return self.send_ok

    def is_navigating(self):
        plan = self.navigating_plans[len(self.goals) - 1]
        return plan.pop(0) if len(plan) > 1 else plan[0]

    def state(self):
        return {"pose": self.poses[len(self.goals) - 1]}

    def stop(self):
        self.stop_calls += 1
        return True


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run(robot, waypoints, **options):
    clock = FakeClock()
    settings = {"arrive_tolerance_m": 0.35, "timeout_s": 10.0, "wait_s": 1.0}
    settings.update(options)
    return run_waypoints(robot, waypoints, log=lambda message: None, sleep=clock.sleep, clock=clock, **settings)


WAYPOINTS = select_waypoints(LOCATIONS, ["비품실", "301호"])


def test_run_all_arrive():
    robot = FakeRobot([[True, True, False], [True, False]],
                      [{"x": 0.40, "y": -1.50, "yaw": 1.6}, {"x": 0.30, "y": -0.90, "yaw": 0.1}])
    results = run(robot, WAYPOINTS)
    assert [result.arrived for result in results] == [True, True]
    assert [goal.name for goal in robot.goals] == ["비품실", "301호"] and robot.stop_calls == 0


def test_run_stops_when_far_from_goal():
    robot = FakeRobot([[False], [False]], [{"x": 2.0, "y": -1.55, "yaw": 0.0}, {"x": 0.26, "y": -0.92, "yaw": 0.0}])
    results = run(robot, WAYPOINTS)
    assert len(results) == 1 and not results[0].arrived and "떨어진 곳" in results[0].message
    assert len(robot.goals) == 1  # 다음 장소로 가지 않는다


def test_run_continue_on_miss():
    robot = FakeRobot([[False], [False]], [{"x": 2.0, "y": -1.55, "yaw": 0.0}, {"x": 0.26, "y": -0.92, "yaw": 0.0}])
    results = run(robot, WAYPOINTS, stop_on_miss=False)
    assert [result.arrived for result in results] == [False, True]


def test_run_timeout_sends_stop():
    robot = FakeRobot([[True], [False]], [None, None])
    results = run(robot, WAYPOINTS, timeout_s=5.0)
    assert len(results) == 1 and "정지시킴" in results[0].message and robot.stop_calls == 1


def test_run_goal_not_sent():
    robot = FakeRobot([[False]], [None], send_ok=False)
    results = run(robot, WAYPOINTS)
    assert len(results) == 1 and "액션 서버 없음" in results[0].message
