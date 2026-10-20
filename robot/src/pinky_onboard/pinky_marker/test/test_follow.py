"""간호사 따라가기 계산·상태·검출 (ROS·카메라 없이). 실행: PYTHONPATH=. python3 -m pytest -q test"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from pinky_marker.follow_logic import (
    DISABLED, FOLLOWING, NAV_BUSY, SHORT_LOSS, TARGET_LOST, WAITING,
    FollowParams, compute_command, decide_state, is_valid_target, publishes_velocity,
)
from pinky_marker.vision import image_to_gray, make_detector, marker_geometry

PARAMS = FollowParams(invert_x=False)


def test_far_marker_drives_forward_and_near_backs_off():
    far_linear, _, far_distance, _ = compute_command(320, 50, 640, PARAMS)    # 500*0.05/50 = 0.5 m
    near_linear, _, near_distance, _ = compute_command(320, 125, 640, PARAMS)  # 0.2 m
    assert far_distance == pytest.approx(0.5) and far_linear == pytest.approx(0.10)   # 최대 전진으로 잘림
    assert near_distance == pytest.approx(0.2) and near_linear == pytest.approx(-0.05)  # 최대 후진으로 잘림
    assert compute_command(320, 500 * 0.05 / 0.31, 640, PARAMS)[0] == 0.0   # 1 cm 차이는 데드밴드


def test_turns_toward_marker_and_slows_while_turning():
    _, angular_right, _, x_error = compute_command(560, 50, 640, PARAMS)   # 화면 오른쪽
    assert x_error == pytest.approx(0.75) and angular_right < 0            # 오른쪽으로 돈다(시계)
    assert compute_command(80, 50, 640, PARAMS)[1] > 0
    inverted = compute_command(560, 50, 640, FollowParams(invert_x=True))
    assert inverted[1] > 0                                                  # 카메라가 뒤집혀 달렸을 때
    assert compute_command(560, 50, 640, PARAMS)[0] < compute_command(320, 50, 640, PARAMS)[0]


@pytest.mark.parametrize("enabled, navigating, last_seen, expected", [
    (False, False, 10.0, DISABLED),
    (True, True, 10.0, NAV_BUSY),        # Nav2 주행 중이면 따라가지 않는다
    (True, False, None, WAITING),
    (True, False, 9.8, FOLLOWING),
    (True, False, 8.0, SHORT_LOSS),
    (True, False, 5.0, TARGET_LOST),
])
def test_decide_state(enabled, navigating, last_seen, expected):
    assert decide_state(enabled, navigating, last_seen, 10.0, PARAMS) == expected


def test_only_following_publishes_velocity():
    assert publishes_velocity(FOLLOWING)
    for state in (DISABLED, NAV_BUSY, WAITING, SHORT_LOSS, TARGET_LOST):
        assert not publishes_velocity(state)   # 팀원 원본은 늘 정지 명령을 내서 Nav2를 막았다


def test_targets_are_nurse_markers_only():
    assert is_valid_target(0) and is_valid_target(49)
    assert not is_valid_target(50) and not is_valid_target(137) and not is_valid_target(-1)


def _scene(marker_ids: list[int], dictionary=cv2.aruco.DICT_4X4_250) -> np.ndarray:
    """흰 배경에 마커들을 나란히 그린 BGR 영상."""
    canvas = np.full((300, 200 * len(marker_ids) + 100, 3), 255, np.uint8)
    for index, marker_id in enumerate(marker_ids):
        marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(dictionary), marker_id, 120)
        x = 60 + index * 200
        canvas[90:210, x:x + 120] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return canvas


def test_detects_nurse_and_one_time_markers_with_one_dictionary():
    bgr = _scene([2, 137])
    gray = image_to_gray('bgr8', bgr.shape[0], bgr.shape[1], bgr.shape[1] * 3, bgr.tobytes())
    corners, ids = make_detector('4x4_250')(gray)
    assert sorted(np.asarray(ids).flatten().tolist()) == [2, 137]
    center_x_px, width_px = marker_geometry(corners[list(np.asarray(ids).flatten()).index(2)])
    assert center_x_px == pytest.approx(120, abs=2) and width_px == pytest.approx(120, abs=3)


def test_teammate_printed_marker_from_4x4_50_is_read_by_4x4_250():
    bgr = _scene([3], dictionary=cv2.aruco.DICT_4X4_50)   # EMR 인쇄 카드와 같은 사전
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    assert np.asarray(make_detector('4x4_250')(gray)[1]).flatten().tolist() == [3]


def test_image_to_gray_handles_padded_rows_and_rgb():
    rgb = np.zeros((4, 3, 3), np.uint8); rgb[..., 0] = 255   # 빨강
    padded = np.zeros((4, 12), np.uint8); padded[:, :9] = rgb.reshape(4, 9)   # step 12 (행마다 3바이트 여분)
    gray = image_to_gray('rgb8', 4, 3, 12, padded.tobytes())
    assert gray.shape == (4, 3) and int(gray[0, 0]) == int(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)[0, 0])
