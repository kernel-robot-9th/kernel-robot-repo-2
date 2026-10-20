"""Pure helpers of vla_teleop (no hardware, no ROS)."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser('~/dev_ws/robot/src/vla_planner_robot/vla_executor'))
from vla_teleop import dxl  # noqa: E402
from vla_teleop.cli import plan_pick, plan_tap, tool_pose  # noqa: E402


def test_raw_to_rad_matches_ros2_control():
    # the follower read 2068/732/3157/3101/2021 while ros2_control reported 0.031/-2.019/1.702/1.616/-0.041 rad
    got = [dxl.raw_to_rad(v) for v in (2068, 732, 3157, 3101, 2021)]
    assert got == pytest.approx([0.031, -2.019, 1.702, 1.616, -0.041], abs=0.001)


def test_error_names():
    assert dxl.error_names(32) == ['overload']
    assert dxl.error_names(0) == []
    assert dxl.error_names(36) == ['overheating', 'overload']


def test_tool_pose_tilt_and_folded_pose():
    x, y, z, tilt = tool_pose([0.0, -1.57, 1.57, 1.57, 0.0])     # observe pose: gripper straight down
    assert abs(tilt) < 0.5
    q = [0.031, -2.019, 1.702, 1.616, -0.041]                     # folded pose seen on the real arm
    x, y, z, _ = tool_pose(q)
    assert (round(x, 3), round(z, 3)) == (0.055, 0.020)          # what the viewer showed at 19:51


def test_config_has_both_arms():
    import yaml
    path = os.path.join(os.path.dirname(__file__), '..', 'config', 'arms.yaml')
    cfg = yaml.safe_load(open(path))
    assert set(cfg['arms']) == {'left', 'right'}
    assert cfg['safe_z_min_m'] == -0.04 and math.isclose(cfg['align_duration_s'], 10.0)


FOLDED = [0.031, -2.019, 1.702, 1.616, -0.041]


def test_tap_plan_reaches_the_point_pointing_down():
    plan = plan_tap(FOLDED, 0.19, -0.08, -0.04, 0.05, -0.04)
    assert [name for name, _ in plan] == ['hover', 'touch', 'lift', 'home']
    x, y, z, tilt = tool_pose(dict(plan)['touch'])
    assert (x, y, z) == pytest.approx((0.19, -0.08, -0.04), abs=0.002) and abs(tilt) < 0.5
    assert dict(plan)['home'] == FOLDED


def test_tap_refuses_below_safe_height_and_out_of_reach():
    with pytest.raises(ValueError, match='safe height'):
        plan_tap(FOLDED, 0.19, -0.08, -0.06, 0.05, -0.04)
    assert plan_tap(FOLDED, 0.19, -0.08, -0.06, 0.05, -0.04, allow_below_safe=True)
    with pytest.raises(ValueError, match='out of reach'):
        plan_tap(FOLDED, 0.40, 0.0, -0.04, 0.05, -0.04)


def test_pick_plan_opens_closes_and_returns_home():
    plan = plan_pick(FOLDED, (0.244, 0.004, -0.038), (0.200, 0.097, -0.028), 0.05, -0.04, 0.68, -0.15)
    names = [p[0] for p in plan]
    assert names == ['open', 'above pick', 'down', 'close', 'up', 'above place', 'down', 'release', 'up', 'home']
    by_step = plan
    assert tool_pose(by_step[2][1])[:3] == pytest.approx((0.244, 0.004, -0.038), abs=0.002)   # down at the pick
    assert by_step[3][2] == -0.15 and by_step[7][2] == 0.68                                   # close, release
    assert by_step[-1][1] == FOLDED
    with pytest.raises(ValueError, match='out of reach'):
        plan_pick(FOLDED, (0.244, 0.004, -0.038), (0.279, 0.104, -0.025), 0.05, -0.04, 0.68, -0.15)


def test_rect_yaw_turns_the_wrist_without_square_folding():
    from vla_teleop.cli import ik_rect
    q0 = ik_rect(0.2, 0.0, -0.03, math.pi / 2)        # closing across the arm: joint5 0
    assert q0[4] == pytest.approx(0.0, abs=1e-6)
    q = ik_rect(0.2, 0.0, -0.03, 0.0)                 # closing along the arm: a quarter turn, not folded back to 0
    assert abs(q[4]) == pytest.approx(math.pi / 2, abs=1e-6)


def test_camera_ctrl_parsing_and_exposure_search():
    from vla_teleop.camera_lock import parse_ctrls, search_exposure
    text = ('         exposure_time_absolute 0x009a0902 (int)    : min=48 max=10000 step=1 default=400 value=400 flags=inactive\n'
            '                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)\n'
            '        white_balance_automatic 0x0098090c (bool)   : default=1 value=1\n')
    ctrls = parse_ctrls(text)
    assert ctrls['exposure_time_absolute'] == {'min': 48, 'max': 10000, 'default': 400, 'value': 400}
    assert ctrls['auto_exposure']['value'] == 3 and ctrls['white_balance_automatic']['value'] == 1
    exposure, v = search_exposure(lambda e: min(255, e * 0.1), 48, 10000, target=230)   # clips above 2300
    assert 2250 <= exposure <= 2300 and v <= 230
