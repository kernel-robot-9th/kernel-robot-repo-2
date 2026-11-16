"""Pure helpers of the real top-camera calibration (no camera, no ROS)."""
import cv2
import numpy as np
import pytest

from vla_calibration.top_camera import average_arm_points, error_mm, fit_homography, marker_centre, plane_z


def test_marker_centre_is_the_diagonal_crossing_under_perspective():
    square = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    H = np.array([[200, 30, 100], [10, 180, 50], [0.4, 0.2, 1]], np.float64)
    corners = cv2.perspectiveTransform(square.reshape(-1, 1, 2), H).reshape(-1, 2)
    true_centre = cv2.perspectiveTransform(np.float32([[[0.5, 0.5]]]), H)[0, 0]
    assert marker_centre(corners) == pytest.approx(true_centre, abs=1e-3)
    assert np.linalg.norm(corners.mean(0) - true_centre) > 1.0      # the plain corner mean is off


def test_arm_points_average_repeated_touches_and_skip_other_labels():
    rows = [{'label': 'p20', 'x_m': '0.20', 'y_m': '0.10', 'z_m': '-0.040', 'tilt_deg': '1.0'},
            {'label': 'p20', 'x_m': '0.22', 'y_m': '0.12', 'z_m': '-0.042', 'tilt_deg': '-6.0'},
            {'label': 'marker47', 'x_m': '0.3', 'y_m': '0', 'z_m': '0', 'tilt_deg': '0'}]
    arm = average_arm_points(rows)
    assert list(arm) == [20]
    x, y, z, n, tilt = arm[20]
    assert (x, y, z, n, tilt) == pytest.approx((0.21, 0.11, -0.041, 2, 6.0))


def test_homography_recovers_a_known_mapping_and_reports_mm():
    H_true = np.array([[0.0, -6e-4, 0.9], [-6e-4, 0.0, 1.1], [0.0, 0.0, 1.0]])     # pixel -> metres, axes swapped
    px = np.float32([[u, v] for v in (500, 650, 800) for u in (1200, 1400, 1600)])
    arm = cv2.perspectiveTransform(px.reshape(-1, 1, 2), H_true).reshape(-1, 2)
    H, err = fit_homography(px, arm)
    assert err.max() < 0.01
    assert error_mm(H, [[1300, 700]], cv2.perspectiveTransform(np.float32([[[1300, 700]]]), H_true).reshape(-1, 2))[0] < 0.01
    noisy = arm + np.float32([[0.002, 0]] + [[0, 0]] * 8)                             # one point 2 mm off
    _, err = fit_homography(px, noisy)
    assert 0.1 < err.max() < 2.0


def test_plane_through_touched_heights():
    pts = [(x, y, -0.044 + 0.05 * (x - 0.2)) for x in (0.15, 0.2, 0.25) for y in (-0.1, 0, 0.1)]
    coef, resid = plane_z(pts)
    assert coef == pytest.approx([-0.054, 0.05, 0.0], abs=1e-6) and abs(resid).max() < 1e-9


def test_rigid_fit_maps_board_to_arm_including_a_mirror():
    from vla_calibration.top_camera import fit_rigid_2d
    board = np.array([[0, 0], [0.184, 0], [0, 0.115], [0.184, 0.115]])
    a = np.radians(10)
    R_true = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) @ np.array([[0, -1], [-1, 0]])   # image->arm flips
    arm = board @ R_true.T + np.array([0.15, 0.05])
    R, t, resid = fit_rigid_2d(board, arm)
    assert resid.max() < 1e-9 and R == pytest.approx(R_true, abs=1e-9)
