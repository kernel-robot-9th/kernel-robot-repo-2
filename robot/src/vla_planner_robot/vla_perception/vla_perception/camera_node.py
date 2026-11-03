"""USB camera -> sensor_msgs/Image (bgr8) + CameraInfo, for the real top and wrist cameras (no cv_bridge).

A reader thread keeps only the newest frame, so subscribers never get a stale buffered image; frames are
published at `rate`. Reliable QoS depth 1: large best-effort frames get dropped on this PC.
  ros2 run vla_perception camera_node --ros-args -p device:=/dev/v4l/by-id/...-video-index0 -p topic:=/camera/image_raw
"""
import glob
import os
import threading

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image


class CameraNode(Node):

    def __init__(self):
        super().__init__('camera')
        p = self.declare_parameter
        p('device', '/dev/video0')        # a path or a glob (by-path hub ports move between PC ports)
        p('width', 1920)
        p('height', 1080)
        p('fourcc', 'MJPG')
        p('rate', 5.0)                    # published frames per second
        p('topic', '/camera/image_raw')
        p('frame_id', 'top_camera')
        p('intrinsics_file', '')          # top_intrinsics.yaml -> CameraInfo (K, D)
        spec = self.get_parameter('device').value
        matches = sorted(glob.glob(spec))
        device = matches[0] if matches else spec
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        fourcc = self.get_parameter('fourcc').value
        if fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.get_parameter('width').value)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.get_parameter('height').value)
        if not self.cap.isOpened():
            raise RuntimeError(f'cannot open camera {device}')
        topic = self.get_parameter('topic').value
        self.pub = self.create_publisher(Image, topic, 1)
        self.info_pub = self.create_publisher(CameraInfo, os.path.join(os.path.dirname(topic), 'camera_info'), 1)
        self.info = self._load_info(self.get_parameter('intrinsics_file').value)
        self.frame, self.lock, self.running = None, threading.Lock(), True
        threading.Thread(target=self._reader, daemon=True).start()
        self.create_timer(1.0 / self.get_parameter('rate').value, self._publish)
        self.get_logger().info(f'{device} -> {topic} at {self.get_parameter("rate").value} Hz')

    def _load_info(self, path):
        if not path:
            return None
        with open(os.path.expanduser(path)) as handle:
            intr = yaml.safe_load(handle)
        info = CameraInfo()
        info.width, info.height = intr['size']
        info.k = [float(v) for v in np.array(intr['K']).ravel()]
        info.d = [float(v) for v in intr['dist']]
        info.distortion_model = 'plumb_bob'
        return info

    def _reader(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame

    def _publish(self):
        with self.lock:
            frame = self.frame
        if frame is None:
            return
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.get_parameter('frame_id').value
        msg.height, msg.width = frame.shape[:2]
        msg.encoding = 'bgr8'
        msg.step = msg.width * 3
        msg.data = frame.tobytes()
        self.pub.publish(msg)
        if self.info is not None:
            self.info.header = msg.header
            self.info_pub.publish(self.info)

    def destroy_node(self):
        self.running = False
        self.cap.release()
        super().destroy_node()


def main():
    rclpy.init()
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
