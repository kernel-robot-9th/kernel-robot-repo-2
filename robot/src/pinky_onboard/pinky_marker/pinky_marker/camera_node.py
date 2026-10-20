# =============================================================================
# 파일   : pinky_marker/camera_node.py
# 역할   : Pinky Pi 카메라 → /camera/image_raw (bgr8, 기본 640x480 30fps). 팀원 cam_pub.py(2026-10-12) 그대로 정리
# 작성일 : 2026-10-20
# 구성   :
#   - CameraPublisher  picamera2로 찍어 sensor_msgs/Image 발행 (cv_bridge 없이)
# Pinky에서만 돈다(picamera2). 카메라는 한 프로그램만 쓸 수 있다 — LCD 영상(play_cam.py)을 끄고 실행.
# 영상은 Pinky 안에서 따라가기·마커 노드가 쓴다. 원본 30fps는 와이파이로 약 27 MB/s라 PC로 보내 쓰지 않는다
# =============================================================================
from __future__ import annotations

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


class CameraPublisher(Node):
    def __init__(self) -> None:
        super().__init__('pinky_camera')
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30.0)
        self.declare_parameter('rotate180', False)
        self.declare_parameter('frame_id', 'camera_link')
        width = int(self.get_parameter('width').value)
        height = int(self.get_parameter('height').value)
        fps = float(self.get_parameter('fps').value)
        self.rotate180 = bool(self.get_parameter('rotate180').value)
        self.frame_id = str(self.get_parameter('frame_id').value)

        from picamera2 import Picamera2   # Pinky에만 있다 — PC에서 패키지 빌드·테스트는 되게 늦게 불러온다
        self.camera = Picamera2()
        # picamera2의 'RGB888'은 numpy 배열에서 BGR 순서다 (팀원 확인, play_cam.py와 같음)
        self.camera.configure(self.camera.create_preview_configuration(main={'format': 'RGB888', 'size': (width, height)}))
        self.camera.start()
        self.publisher = self.create_publisher(Image, 'camera/image_raw', 10)
        self.create_timer(1.0 / fps, self.capture)
        self.get_logger().info(f'/camera/image_raw {width}x{height} @ {fps:.0f} fps 발행')

    def capture(self) -> None:
        frame = self.camera.capture_array()   # H x W x 3, BGR
        if self.rotate180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        message = Image()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = self.frame_id
        message.height, message.width = frame.shape[:2]
        message.encoding = 'bgr8'
        message.is_bigendian = 0
        message.step = message.width * 3
        message.data = frame.tobytes()
        self.publisher.publish(message)

    def close(self) -> None:
        self.camera.stop()
        self.camera.close()


def main() -> None:
    rclpy.init()
    node = CameraPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
