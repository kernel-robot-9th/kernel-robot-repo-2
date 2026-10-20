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
