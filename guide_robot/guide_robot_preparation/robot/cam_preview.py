"""노트북용 가벼운 카메라 미리보기: Pinky의 원본 카메라는 ~27 MB/s라 Wi-Fi에는 너무 무거움.

Pinky에서 cam_pub.py와 함께 실행, 회전한 작은 JPEG를 초당 몇 번 발행:

  python3 robot/cam_preview.py                      # 320x240, 5 Hz -> /camera/preview/compressed
  python3 robot/cam_preview.py --width 640 --hz 10

노트북:  ros2 run rqt_image_view rqt_image_view /camera/preview/compressed
"""
from __future__ import annotations

import argparse
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image


def to_jpeg(img, width: int, quality: int, stamp, frame_id: str) -> CompressedImage:
    h = int(img.shape[0] * width / img.shape[1])
    ok, buf = cv2.imencode(".jpg", cv2.resize(img, (width, h)), [cv2.IMWRITE_JPEG_QUALITY, quality])
    m = CompressedImage()
    m.header.stamp, m.header.frame_id = stamp, frame_id
    m.format, m.data = "jpeg", buf.tobytes()
    return m


def raw_to_bgr(m: Image):
    img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if m.encoding == "rgb8" else img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="/camera/image_raw")
    ap.add_argument("--out", default="/camera/preview/compressed")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--no-rotate", action="store_true", help="카메라가 거꾸로 달려 있지 않음")
    args = ap.parse_args()

    rclpy.init()
    node = Node("pinky_cam_preview")
    pub = node.create_publisher(CompressedImage, args.out, qos_profile_sensor_data)
    last = [0.0]

    def cb(m: Image):
        now = time.monotonic()
        if now - last[0] < 1.0 / args.hz:
            return
        last[0] = now
        img = raw_to_bgr(m)
        if not args.no_rotate:
            img = cv2.rotate(img, cv2.ROTATE_180)
        pub.publish(to_jpeg(img, args.width, args.quality, m.header.stamp, m.header.frame_id))

    node.create_subscription(Image, args.topic, cb, qos_profile_sensor_data)
    print(f"{args.topic} -> {args.out} ({args.width}px, {args.hz} Hz)")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
