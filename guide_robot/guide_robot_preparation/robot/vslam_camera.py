"""비주얼 SLAM (RTAB-Map)용 카메라 영상: 똑바로 돌린 영상 + camera_info, Pi가 감당할 수 있는 속도로.

cam_pub.py는 원본 영상을 거꾸로, 30 Hz로, camera_info와 TF 프레임 없이 발행함.
RTAB-Map에는 이 세 가지가 모두 필요하므로, 이 노드가 (Pinky에서 cam_pub.py와 함께):
  * 영상을 180° 회전 (캘리브레이션도 회전한 영상으로 했으므로 일치함),
  * --hz (기본 10)로 낮추고,
  * camera_optical_frame 프레임을 붙여 ~/pinky_camera.yaml (robot/calibrate_camera.py)에서
    읽은 camera_info와 함께 발행.

  python3 robot/vslam_camera.py                     # -> /vslam/image_raw, /vslam/camera_info
  python3 robot/vslam_camera.py --hz 5 --calib ~/pinky_camera.yaml
"""
from __future__ import annotations

import argparse
import os
import time

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image


def load_info(path: str, frame: str) -> CameraInfo:
    with open(os.path.expanduser(path)) as f:
        c = yaml.safe_load(f)
    m = CameraInfo()
    m.header.frame_id = frame
    m.width, m.height = c["image_width"], c["image_height"]
    m.distortion_model = c.get("distortion_model", "plumb_bob")
    m.k = [float(x) for x in c["camera_matrix"]["data"]]
    m.d = [float(x) for x in c["distortion_coefficients"]["data"]]
    m.r = [float(x) for x in c["rectification_matrix"]["data"]]
    m.p = [float(x) for x in c["projection_matrix"]["data"]]
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/camera/image_raw")
    ap.add_argument("--out", default="/vslam")
    ap.add_argument("--calib", default="~/pinky_camera.yaml")
    ap.add_argument("--frame", default="camera_optical_frame")
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--no-rotate", action="store_true", help="카메라가 거꾸로 달려 있지 않음")
    args = ap.parse_args()

    if not os.path.exists(os.path.expanduser(args.calib)):
        raise SystemExit(f"{args.calib} not found: calibrate the camera first with python3 calibrate_camera.py.")
    info = load_info(args.calib, args.frame)

    rclpy.init()
    node = Node("pinky_vslam_camera")
    img_pub = node.create_publisher(Image, args.out + "/image_raw", qos_profile_sensor_data)
    info_pub = node.create_publisher(CameraInfo, args.out + "/camera_info", qos_profile_sensor_data)
    last = [0.0]
    warned = [False]

    def cb(m: Image):
        now = time.monotonic()
        if now - last[0] < 1.0 / args.hz:
            return
        last[0] = now
        if (m.width, m.height) != (info.width, info.height) and not warned[0]:
            warned[0] = True
            node.get_logger().error(f"camera {m.width}x{m.height}, calibration {info.width}x{info.height}: mismatch!")
        img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)
        if not args.no_rotate:
            img = np.ascontiguousarray(cv2.rotate(img, cv2.ROTATE_180))
        out = Image()
        out.header.stamp, out.header.frame_id = m.header.stamp, args.frame
        out.height, out.width, out.encoding = m.height, m.width, m.encoding
        out.is_bigendian, out.step, out.data = m.is_bigendian, m.step, img.tobytes()
        info.header.stamp = m.header.stamp
        img_pub.publish(out)
        info_pub.publish(info)

    node.create_subscription(Image, args.topic, cb, qos_profile_sensor_data)
    print(f"{args.topic} -> {args.out}/image_raw + camera_info ({args.hz} Hz, frame {args.frame})")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
