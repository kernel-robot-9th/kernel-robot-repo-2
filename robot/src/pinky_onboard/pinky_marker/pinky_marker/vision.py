# =============================================================================
# 파일   : pinky_marker/vision.py
# 역할   : 영상·마커 계산 (ROS를 모른다 — 단위 테스트 대상). 팀원 marker_follower_2.py(2026-10-13)에서 옮김
# 작성일 : 2026-10-20
# 구성   :
#   - make_detector()      gray → (corners, ids). OpenCV 4.7 전후 API 모두
#   - image_to_gray()      sensor_msgs/Image(필드만 씀) → 흑백 numpy (cv_bridge 없이)
#   - marker_geometry()    꼭짓점 → (중심 x, 평균 한 변 px)
# 사전: 간호사 신분증 마커는 DICT_4X4_50(0~49)이고, 배송 일회용 수령 마커는 DICT_4X4_250(50~249).
#       DICT_4X4_50 = DICT_4X4_250 앞 50개라 4x4_250 하나로 둘 다 읽는다 (DICT_4X4_1000은 오류 보정 0비트라 쓰지 않음)
# =============================================================================
from __future__ import annotations

from typing import Any, Callable

import cv2
import numpy as np

DICTIONARIES = {
    '4x4_50': cv2.aruco.DICT_4X4_50,
    '4x4_250': cv2.aruco.DICT_4X4_250,
    '5x5_50': cv2.aruco.DICT_5X5_50,
    '6x6_50': cv2.aruco.DICT_6X6_50,
}
NURSE_MARKER_ID_MAX = 49   # 간호사 신분증 마커 (EMR nurses.aruco_marker_id 0~49)


def make_detector(dictionary_name: str) -> Callable[[np.ndarray], tuple[Any, Any]]:
    """[입력] dictionary_name: DICTIONARIES 키 [출력] gray → (corners, ids) 함수"""
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARIES[dictionary_name])
    if hasattr(cv2.aruco, 'ArucoDetector'):   # OpenCV 4.7 이상
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        return lambda gray: detector.detectMarkers(gray)[:2]
    parameters = cv2.aruco.DetectorParameters_create()   # 옛 OpenCV (Pinky 기본 패키지일 수 있음)
    return lambda gray: cv2.aruco.detectMarkers(gray, dictionary, parameters=parameters)[:2]


def image_to_gray(encoding: str, height: int, width: int, step: int, data: bytes) -> np.ndarray:
    """sensor_msgs/Image 필드 → 흑백 영상.
    [입력] encoding·height·width·step·data [출력] np.ndarray (height, width) uint8
    """
    encoding = encoding.lower()
    buffer = np.frombuffer(data, dtype=np.uint8).reshape(height, step)
    if encoding in ('mono8', '8uc1'):
        return buffer[:, :width]
    channels = 4 if encoding in ('bgra8', 'rgba8', '8uc4') else 3
    image = buffer[:, :width * channels].reshape(height, width, channels)
    conversion = {
        'rgb8': cv2.COLOR_RGB2GRAY, 'bgr8': cv2.COLOR_BGR2GRAY, '8uc3': cv2.COLOR_BGR2GRAY,
        'rgba8': cv2.COLOR_RGBA2GRAY, 'bgra8': cv2.COLOR_BGRA2GRAY, '8uc4': cv2.COLOR_BGRA2GRAY,
    }.get(encoding, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(image, conversion)


def marker_geometry(corner: np.ndarray) -> tuple[float, float]:
    """[입력] corner: (1,4,2) 꼭짓점 [출력] (중심 x px, 평균 한 변 px)"""
    points = corner.reshape(4, 2)
    sides = [np.linalg.norm(points[index] - points[(index + 1) % 4]) for index in range(4)]
    return float(points[:, 0].mean()), float(np.mean(sides))
