"""캘리브레이션 보드로 Pinky 카메라가 아래로 얼마나 기울었는지 측정.

인쇄한 ChArUco 보드를 Pinky를 향해 똑바로 세우고 (수직, 예: 박스나 벽에 붙임),
20-40 cm 앞에 보드 전체가 보이게 둠. 카메라는 바닥에서 6 cm뿐이라서, 바닥에 눕힌
보드는 너무 비스듬히 보여 검출되지 않음. 그다음 Pinky에서:

  python3 robot/camera_tilt.py                       # ~/pinky_camera.yaml과 실행 중인 cam_pub.py 필요
  python3 robot/camera_tilt.py --image frame.png     # 오프라인, 저장한 카메라 프레임으로

vslam.launch.py에 바로 쓸 수 있는 pitch를 출력:  cam_pitch:=<rad>
보드는 정말 수직이어야 함 (직각자나 벽으로 확인); N도 뒤로 기운 보드는
기울기가 N도 작게 측정됨.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrate_camera import make_board, object_points  # noqa: E402


def load_calib(path):
    import yaml
    with open(os.path.expanduser(path)) as f:
        c = yaml.safe_load(f)
    K = np.array(c["camera_matrix"]["data"], dtype=np.float64).reshape(3, 3)
    D = np.array(c["distortion_coefficients"]["data"], dtype=np.float64)
    return K, D


def tilt_from_gray(gray, board, detect, K, D):
    """세워 둔 보드에 대해 (pitch_down_rad, roll_rad, distance_m, n_corners) 반환, 없으면 None."""
    cc, ci = detect(gray)
    if ci is None or len(ci) < 12:
        return None
    obj = object_points(board, ci).astype(np.float64)
    ok, rvec, t = cv2.solvePnP(obj, cc.reshape(-1, 2).astype(np.float64), K, D)
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    down = R[:, 1]                     # 카메라 좌표계에서 보드의 세로축
    if down[1] < 0:                    # 아래를 향하게 함 (카메라 y는 아래 방향)
        down = -down
    pitch_down = math.asin(max(-1.0, min(1.0, down[2])))  # 광축 (0,0,1)과 수평의 비교
    roll = math.atan2(down[0], down[1])                   # 카메라가 수평으로 달려 있으면 ~0
    return pitch_down, roll, float(np.linalg.norm(t)), len(ci)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", default="~/pinky_camera.yaml")
    ap.add_argument("--square", type=float, default=0.025)
    ap.add_argument("--marker", type=float, default=0.018)
    ap.add_argument("--topic", default="/camera/image_raw")
    ap.add_argument("--image", help="ROS 대신 저장한 프레임 사용")
    ap.add_argument("--no-rotate", action="store_true")
    ap.add_argument("--samples", type=int, default=20)
    args = ap.parse_args()

    K, D = load_calib(args.calib)
    board, detect = make_board(args.square, args.marker)

    def prep(img):
        g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return g if args.no_rotate else cv2.rotate(g, cv2.ROTATE_180)

    results = []
    if args.image:
        r = tilt_from_gray(prep(cv2.imread(args.image)), board, detect, K, D)
        results = [r] if r else []
    else:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image
        rclpy.init()
        node = Node("pinky_camera_tilt")
        latest = {}
        node.create_subscription(Image, args.topic, lambda m: latest.__setitem__("m", m), qos_profile_sensor_data)
        print("Stand the board upright (vertical) in front of Pinky (20-40 cm)...")
        tries = 0
        while len(results) < args.samples and tries < 600:
            rclpy.spin_once(node, timeout_sec=0.1)
            if "m" not in latest:
                continue
            m = latest.pop("m")
            tries += 1
            img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)
            r = tilt_from_gray(prep(img), board, detect, K, D)
            if r:
                results.append(r)
                print(f"  {len(results)}/{args.samples}: tilt {math.degrees(r[0]):.1f}°, distance {r[2]*100:.0f} cm")
            elif tries % 30 == 0:
                print("  board not visible (keep the whole board in the frame)")
        node.destroy_node()
        rclpy.try_shutdown()

    if not results:
        raise SystemExit("Board not found.")
    p, roll, _, _ = np.median(np.array(results), axis=0)
    print(f"\nTilt down:      {math.degrees(p):.1f}°  ({p:.3f} rad)")
    print(f"Sideways roll:  {math.degrees(roll):.1f}°  (should be close to 0)")
    print(f"\nFor vslam.launch.py:  cam_pitch:={p:.3f}")


if __name__ == "__main__":
    main()
