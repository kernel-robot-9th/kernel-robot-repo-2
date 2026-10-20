#!/usr/bin/env python3
"""Camera intrinsic calibration from a checkerboard.

Move a checkerboard around under the top camera (tilt it, cover the corners of the
image, vary the distance). Frames are captured automatically when the board is found
in a pose different from the ones already collected; after --samples frames the
camera matrix and distortion are solved and written as a ROS camera_info YAML that
usb_cam can load (camera_info_url: file://<out>).

  ros2 run vla_calibration intrinsics --board 9x6 --square 0.03
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

from vla_calibration.common import DEFAULT_CALIB_DIR, spin_in_background, to_list
from vla_perception.table_geometry import image_to_numpy


def board_features(corners, shape):
    """(cx, cy, size, skew) normalized: used to decide if a pose is new."""
    pts = corners.reshape(-1, 2)
    h, w = shape[:2]
    cx, cy = pts[:, 0].mean() / w, pts[:, 1].mean() / h
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    size = np.sqrt((x1 - x0) * (y1 - y0) / (w * h))
    hull = cv2.convexHull(pts.astype(np.float32))
    skew = 1.0 - cv2.contourArea(hull) / max((x1 - x0) * (y1 - y0), 1.0)   # 0 = fronto-parallel
    return np.array([cx, cy, size, skew])


def write_camera_info_yaml(path, name, width, height, K, D, R=None, P=None):
    R = np.eye(3) if R is None else R
    if P is None:
        P = np.zeros((3, 4))
        P[:3, :3] = K
    txt = f"""image_width: {width}
image_height: {height}
camera_name: {name}
camera_matrix:
  rows: 3
  cols: 3
  data: {to_list(K, 6)}
distortion_model: plumb_bob
distortion_coefficients:
  rows: 1
  cols: {len(np.ravel(D))}
  data: {to_list(D, 6)}
rectification_matrix:
  rows: 3
  cols: 3
  data: {to_list(R, 6)}
projection_matrix:
  rows: 3
  cols: 4
  data: {to_list(P, 6)}
"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w') as f:
        f.write(txt)


def calibrate(obj_pts, img_pts, image_size):
    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts, image_size, None, None)
    per_view = []
    for o, i, r, t in zip(obj_pts, img_pts, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, r, t, K, D)
        per_view.append(float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - i.reshape(-1, 2)) ** 2, axis=1)))))
    return rms, K, D, per_view


class IntrinsicsCollector(Node):

    def __init__(self, args):
        super().__init__('vla_calib_intrinsics')
        self.args = args
        cols, rows = (int(v) for v in args.board.lower().split('x'))
        self.pattern = (cols, rows)
        self.objp = np.zeros((cols * rows, 3), np.float32)
        self.objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * args.square
        self.obj_pts, self.img_pts, self.features = [], [], []
        self.size = None
        self.reference_info = None
        self.last_try = 0.0
        self.create_subscription(Image, args.image_topic, self._on_image, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, args.info_topic, self._on_info, qos_profile_sensor_data)

    def _on_info(self, msg):
        self.reference_info = msg

    def _on_image(self, msg):
        if len(self.img_pts) >= self.args.samples or time.monotonic() - self.last_try < 0.2:
            return
        self.last_try = time.monotonic()
        gray = cv2.cvtColor(image_to_numpy(msg), cv2.COLOR_BGR2GRAY)
        self.size = (gray.shape[1], gray.shape[0])
        found, corners = cv2.findChessboardCorners(
            gray, self.pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not found:
            return
        corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                   (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-3))
        f = board_features(corners, gray.shape)
        if self.features and min(np.linalg.norm(f - g) for g in self.features) < self.args.min_change:
            return
        self.features.append(f)
        self.obj_pts.append(self.objp.copy())
        self.img_pts.append(corners)
        self.get_logger().info(
            f'sample {len(self.img_pts)}/{self.args.samples}: center ({f[0]:.2f},{f[1]:.2f}) '
            f'size {f[2]:.2f} skew {f[3]:.2f}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image-topic', default='/camera/image_raw')
    ap.add_argument('--info-topic', default='/camera/camera_info',
                    help='only used to print a comparison (e.g. the simulator\'s true intrinsics)')
    ap.add_argument('--board', default='9x6', help='inner corners, cols x rows')
    ap.add_argument('--square', type=float, default=0.03, help='square size [m]')
    ap.add_argument('--samples', type=int, default=20)
    ap.add_argument('--min-change', type=float, default=0.06, help='pose novelty threshold')
    ap.add_argument('--timeout', type=float, default=600.0)
    ap.add_argument('--camera-name', default='top_camera')
    ap.add_argument('--out', default=os.path.join(DEFAULT_CALIB_DIR, 'camera_info.yaml'))
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])

    rclpy.init(args=argv)
    node = IntrinsicsCollector(args)
    spin_in_background(node)
    node.get_logger().info(f'move a {args.board} checkerboard ({args.square * 1000:.0f} mm squares) '
                           f'under the camera; collecting {args.samples} views')
    deadline = time.monotonic() + args.timeout
    while len(node.img_pts) < args.samples and time.monotonic() < deadline:
        time.sleep(0.2)
    if len(node.img_pts) < 6:
        node.get_logger().error(f'only {len(node.img_pts)} views collected, need at least 6')
        rclpy.shutdown()
        return 1

    rms, K, D, per_view = calibrate(node.obj_pts, node.img_pts, node.size)
    write_camera_info_yaml(args.out, args.camera_name, node.size[0], node.size[1], K, D)
    print(f'\nviews: {len(per_view)}   RMS reprojection error: {rms:.3f} px '
          f'(worst view {max(per_view):.3f} px)')
    print(f'fx {K[0, 0]:.2f}  fy {K[1, 1]:.2f}  cx {K[0, 2]:.2f}  cy {K[1, 2]:.2f}')
    print(f'distortion {np.round(np.ravel(D), 5).tolist()}')
    ref = node.reference_info
    if ref is not None and any(ref.k):
        Kr = np.array(ref.k).reshape(3, 3)
        print(f'camera_info on {args.info_topic}: fx {Kr[0, 0]:.2f} fy {Kr[1, 1]:.2f} '
              f'cx {Kr[0, 2]:.2f} cy {Kr[1, 2]:.2f}  -> fx error {100 * (K[0, 0] / Kr[0, 0] - 1):+.2f} %')
    print(f'written: {args.out}')
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
