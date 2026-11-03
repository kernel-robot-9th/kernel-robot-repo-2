import numpy as np
import pytest

from vla_executor.grasp_check import grasp_fill
from vla_perception.table_geometry import DEFAULT_HSV

ROI = [0.40, 0.40, 0.65, 0.58]


def frame(box=None, bgr=(0, 0, 255)):
    img = np.full((240, 320, 3), 225, np.uint8)
    if box:
        x0, y0, x1, y1 = box
        img[y0:y1, x0:x1] = bgr
    return img


def test_held_block_fills_roi():
    fill, c = grasp_fill(frame((120, 90, 215, 190)), DEFAULT_HSV, 'red', ROI)
    assert fill > 0.95 and c == 'red'


def test_block_left_on_table_is_small():
    fill, _ = grasp_fill(frame((140, 140, 185, 195)), DEFAULT_HSV, 'red', ROI)
    assert fill < 0.3


def test_wrong_color_does_not_count():
    fill, _ = grasp_fill(frame((120, 90, 215, 190), bgr=(255, 0, 0)), DEFAULT_HSV, 'red', ROI)
    assert fill == 0.0


def test_any_color_picks_best():
    fill, c = grasp_fill(frame((120, 90, 215, 190), bgr=(255, 0, 0)), DEFAULT_HSV, '', ROI)
    assert c == 'blue' and fill > 0.95


def test_unknown_color():
    with pytest.raises(ValueError):
        grasp_fill(frame(), DEFAULT_HSV, 'magenta', ROI)


def test_centering_step_recovers_the_offset_with_an_unknown_camera_rotation():
    import math
    import numpy as np
    from vla_executor.grasp_check import centering_step
    a = math.radians(130)                                     # camera mounted at an unknown angle, 6000 px/m
    J = 6000 * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]) @ np.diag([1, -1])
    ref = np.array([295.0, 190.0])
    true_shift = np.array([0.022, -0.009])                    # the arm must still move this far
    c0 = ref - J @ true_shift                                 # where the block shows up now
    d, J_est = centering_step(c0, c0 + J[:, 0] * 0.01, c0 + J[:, 1] * 0.01, 0.01, ref, 0.04)
    assert np.allclose(d, true_shift, atol=1e-6) and np.allclose(J_est, J)
    d, _ = centering_step(c0, c0 + J[:, 0] * 0.01, c0 + J[:, 1] * 0.01, 0.01, ref, 0.01)
    assert abs(math.hypot(*d) - 0.01) < 1e-9                  # clamped to max_shift
    assert centering_step(c0, c0, c0 + [1, 0], 0.01, ref, 0.04)[0] is None   # probes did not move the image


def test_blob_centre_picks_the_blob_nearest_the_reference():
    import numpy as np
    import cv2
    from vla_executor.grasp_check import blob_centre
    img = np.zeros((480, 640, 3), np.uint8)
    cv2.rectangle(img, (100, 100), (160, 160), (0, 200, 0), -1)      # green far from ref
    cv2.rectangle(img, (280, 170), (320, 210), (0, 200, 0), -1)      # green near ref
    c = blob_centre(img, [40, 100, 60, 85, 255, 255], near=(295, 190))
    assert abs(c[0] - 300) < 1.5 and abs(c[1] - 190) < 1.5
