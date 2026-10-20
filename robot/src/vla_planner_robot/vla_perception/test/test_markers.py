import cv2
import numpy as np
import pytest

from vla_perception.table_geometry import DEFAULT_ARUCO_DICT, aruco_dictionary_id, detect_markers


def marker_scene(dict_name, ids):
    d = cv2.aruco.getPredefinedDictionary(aruco_dictionary_id(dict_name))
    img = np.full((480, 640), 255, np.uint8)
    for k, i in enumerate(ids):
        m = cv2.aruco.generateImageMarker(d, i, 100)
        x = 40 + k * 150
        img[190:290, x:x + 100] = m
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def test_default_is_5x5_100():
    assert DEFAULT_ARUCO_DICT == 'DICT_5X5_100'


def test_detects_5x5_ids():
    found = detect_markers(marker_scene('DICT_5X5_100', [0, 1, 2, 3]))
    assert sorted(found) == [0, 1, 2, 3]
    assert all(c.shape == (4, 2) for c in found.values())


def test_4x4_detector_ignores_5x5_markers():
    assert detect_markers(marker_scene('DICT_5X5_100', [0, 1, 2, 3]), 'DICT_4X4_50') == {}


def test_unknown_dictionary():
    with pytest.raises(ValueError):
        aruco_dictionary_id('DICT_9X9_1')
