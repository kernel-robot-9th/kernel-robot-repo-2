"""Rules of RobotState.to_dict (no ROS)."""
from robot_monitor.state import (STATUS_ABORTED, STATUS_EXECUTING, STATUS_SUCCEEDED, RobotState,
                                 yaw_from_quaternion)


def test_offline_until_a_message_arrives():
    state = RobotState('pinky_1')
    assert state.to_dict(now=10.0)['state'] == 'offline'
    state.seen(10.0)
    assert state.to_dict(now=11.0)['state'] == 'idle'
    assert state.to_dict(now=14.5, offline_after_s=3.0)['online'] is False


def test_navigation_active_and_last_result():
    state = RobotState('pinky_1')
    state.seen(0.0)
    state.update_nav([(b'a', STATUS_EXECUTING)], now=1.0)
    out = state.to_dict(now=1.0)
    assert out['state'] == 'navigating' and out['navigation']['last_result'] is None
    state.update_nav([(b'a', STATUS_SUCCEEDED)], now=2.0)
    out = state.to_dict(now=2.5)
    assert out['state'] == 'idle' and out['navigation']['last_result'] == 'succeeded'
    # the same finished goal repeated in later status messages keeps its first result time
    state.update_nav([(b'a', STATUS_SUCCEEDED), (b'b', STATUS_ABORTED)], now=5.0)
    assert state.nav_last_result == 'aborted' and state.nav_result_time == 5.0
    state.update_nav([(b'a', STATUS_SUCCEEDED), (b'b', STATUS_ABORTED)], now=9.0)
    assert state.nav_result_time == 5.0


def test_battery_and_pose_fields():
    state = RobotState('pinky_1', emr_robot_id=1)
    state.seen(0.0)
    state.battery_percent, state.battery_time = 15.0, 0.0
    state.pose, state.pose_time = (1.23456, -0.5, 0.7), 0.0
    out = state.to_dict(now=1.0, battery_low_percent=20.0)
    assert out['battery'] == {'percent': 15.0, 'voltage_v': None, 'low': True, 'age_s': 1.0}
    assert out['pose'] == {'x_m': 1.235, 'y_m': -0.5, 'yaw_rad': 0.7, 'age_s': 1.0}
    assert out['emr_robot_id'] == 1 and out['namespace'] == '/'


def test_yaw():
    assert abs(yaw_from_quaternion(0, 0, 0.7071068, 0.7071068) - 1.5707963) < 1e-6
