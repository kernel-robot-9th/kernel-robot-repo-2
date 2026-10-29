"""Pure helpers of vla_teleop (no hardware, no ROS)."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser('~/dev_ws/robot/src/vla_planner_robot/vla_executor'))
from vla_teleop import dxl  # noqa: E402
from vla_teleop.cli import tool_pose  # noqa: E402


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


def test_focus_search_finds_the_sharpest_setting():
    from vla_teleop.camera_lock import search_focus
    focus, sharp = search_focus(lambda f: -abs(f - 437), 0, 1023)
    assert abs(focus - 437) <= 16
