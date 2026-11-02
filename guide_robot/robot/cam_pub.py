#!/usr/bin/env python3
# Pinky에서 실행. CSI 카메라를 ROS 2 토픽으로 발행: /camera/image_raw (bgr8, 640x480, 30 fps).
# 카메라는 한 프로그램만 쓸 수 있음: 먼저 play_cam.py / rtsp_server_pinky.py를 종료하세요.
#   python3 ~/guide_robot/robot/cam_pub.py
# 확인:  ros2 topic hz /camera/image_raw   (약 30 Hz)
# 여기서는 영상을 회전하지 않음; 카메라가 180° 거꾸로 달린 것은 vslam_camera.py가 처리함.
import os, sys

# Pinky의 Raspberry Pi용 libcamera는 /usr/local에 있음 (Ubuntu 기본 버전은 Pi 5 카메라를 못 봄).
# 경로를 교체하지 않고 앞에 추가해서 ROS 2 라이브러리 경로는 그대로 유지.
LIB = "/usr/local/lib/aarch64-linux-gnu"
if os.path.isdir(LIB) and not os.environ.get("LD_LIBRARY_PATH", "").startswith(LIB):
    os.environ["LD_LIBRARY_PATH"] = LIB + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["GST_PLUGIN_PATH"] = LIB + "/gstreamer-1.0"
    os.execv(sys.executable, [sys.executable] + sys.argv)   # 새 경로로 다시 시작

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

WIDTH, HEIGHT, FPS = 640, 480, 30


def open_gstreamer():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    pipe = Gst.parse_launch(
        f"libcamerasrc ! video/x-raw,format=NV12,width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
        "! videoconvert ! video/x-raw,format=BGR ! appsink name=sink drop=true max-buffers=1 sync=false")
    sink = pipe.get_by_name("sink")
    if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("libcamerasrc did not start")

    def read():
        sample = sink.emit("try-pull-sample", Gst.SECOND)
        if sample is None:
            return None
        s = sample.get_caps().get_structure(0)
        w, h = s.get_value("width"), s.get_value("height")
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        frame = np.ndarray((h, w, 3), np.uint8, info.data).copy()
        buf.unmap(info)
        return frame

    if read() is None:                                  # 1 s 안에 첫 프레임이 없음
        pipe.set_state(Gst.State.NULL)
        raise RuntimeError("no frame from libcamerasrc")
    return read, lambda: pipe.set_state(Gst.State.NULL)


def open_picamera2():
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "RGB888"},   # picamera2의 RGB888 = BGR 바이트 순서
        controls={"FrameRate": FPS}))
    cam.start()
    return cam.capture_array, cam.stop


def open_camera():
    for name, opener in (("GStreamer libcamerasrc", open_gstreamer), ("picamera2", open_picamera2)):
        try:
            read, close = opener()
            print(f"Camera opened with {name}")
            return read, close
        except Exception as e:                          # 다음 방법 시도
            print(f"{name} failed: {e}")
    raise SystemExit("Camera not found. Is play_cam.py or another camera program still running?")


class CamPub(Node):
    def __init__(self):
        super().__init__("cam_pub")
        self.pub = self.create_publisher(Image, "/camera/image_raw", 1)
        self.read, self.close = open_camera()

    def spin_camera(self):
        while rclpy.ok():
            frame = self.read()
            if frame is None:
                self.get_logger().warn("No camera frame")
                continue
            msg = Image()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera"
            msg.height, msg.width = frame.shape[:2]
            msg.encoding = "bgr8"
            msg.step = msg.width * 3
            msg.data = frame.tobytes()
            self.pub.publish(msg)


def main():
    rclpy.init()
    node = CamPub()
    print("Publishing /camera/image_raw  (Ctrl+C to stop)")
    try:
        node.spin_camera()
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
