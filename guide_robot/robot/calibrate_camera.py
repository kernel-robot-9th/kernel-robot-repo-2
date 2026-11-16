"""인쇄한 ChArUco 보드 (docs/charuco_board_9x7_25mm_5x5_A4.pdf)로 Pinky 카메라를 캘리브레이션.

Pinky에서 실행, 화면 불필요: 카메라를 구독하다가 보드가 새 위치에서 선명하게 보일 때마다
프레임을 저장하고, 프레임이 충분하면 ROS camera_info YAML을 씀.

  python3 robot/calibrate_camera.py                       # /camera/image_raw에서 25프레임
  python3 robot/calibrate_camera.py --square 0.0245       # 인쇄된 한 칸이 24.5 mm일 때
  python3 robot/calibrate_camera.py --images ~/calib_imgs # 오프라인: 저장된 영상으로 캘리브레이션

보드를 천천히 움직이세요: 가까이와 멀리 (20-60 cm), 화면의 왼쪽/오른쪽/위/아래, 기울여서.
결과: ~/pinky_camera.yaml  (guide_mode.py, vslam_camera.py, line_detector.py가 사용)

실행 중에는 작은 주석 JPEG (찾은 코너, 프레임 수)도 발행하므로 노트북에서 볼 수 있음:
  ros2 run rqt_image_view rqt_image_view /calib/preview/compressed

영상은 먼저 180° 회전됨 (Pinky 카메라는 거꾸로 달려 있음). vslam_camera.py와 똑같이 하므로
캘리브레이션이 실제 사용하는 영상과 일치함. --no-rotate로 끌 수 있음.
"""
from __future__ import annotations

import argparse
import glob
import os
import time

import cv2
import numpy as np

COLS, ROWS = 9, 7                 # 인쇄한 보드의 칸 수
DICT = cv2.aruco.DICT_5X5_100     # 다른 마커용 4x4 계열이 아니므로 추종 노드가 이 보드를 보지 않음


def make_board(square: float, marker: float):
    d = cv2.aruco.getPredefinedDictionary(DICT)
    if hasattr(cv2.aruco, "CharucoBoard") and hasattr(cv2.aruco, "CharucoDetector"):  # OpenCV >= 4.7
        board = cv2.aruco.CharucoBoard((COLS, ROWS), square, marker, d)
        det = cv2.aruco.CharucoDetector(board)

        def detect(gray):
            cc, ci, _, _ = det.detectBoard(gray)
            return cc, ci
    else:                                                                        # OpenCV 4.6 (Ubuntu 24.04)
        board = cv2.aruco.CharucoBoard_create(COLS, ROWS, square, marker, d)
        params = cv2.aruco.DetectorParameters_create()

        def detect(gray):
            mc, mi, _ = cv2.aruco.detectMarkers(gray, d, parameters=params)
            if mi is None or len(mi) < 4:
                return None, None
            n, cc, ci = cv2.aruco.interpolateCornersCharuco(mc, mi, gray, board)
            return (cc, ci) if n else (None, None)
    return board, detect


def object_points(board, ids):
    pts = board.getChessboardCorners() if hasattr(board, "getChessboardCorners") else board.chessboardCorners
    return np.asarray(pts, dtype=np.float32)[ids.flatten()]


class Collector:
    """코너가 충분히 보이고 마지막 저장 프레임 이후 보드가 움직인 프레임을 저장."""

    def __init__(self, detect, need: int, min_corners: int = 12):
        self.detect, self.need, self.min_corners = detect, need, min_corners
        self.frames, self.size, self.last_center, self.last_t = [], None, None, 0.0
        self.last_cc = None   # 마지막으로 들어온 프레임의 코너, 미리보기용

    def offer(self, gray) -> str:
        self.size = gray.shape[::-1]
        cc, ci = self.detect(gray)
        n = 0 if ci is None else len(ci)
        self.last_cc = cc if n else None
        if n < self.min_corners:
            return f"board not visible ({n} corners)"
        center = cc.reshape(-1, 2).mean(axis=0)
        spread = np.ptp(cc.reshape(-1, 2), axis=0).mean()
        if self.last_center is not None and np.linalg.norm(center - self.last_center) < 0.08 * gray.shape[1] \
                and time.time() - self.last_t < 3.0:
            return f"{n} corners: move the board somewhere else"
        self.frames.append((cc, ci))
        self.last_center, self.last_t = center, time.time()
        return f"TAKEN {len(self.frames)}/{self.need}  ({n} corners, size {spread:.0f}px)"

    @property
    def done(self) -> bool:
        return len(self.frames) >= self.need


def calibrate(board, frames, size):
    obj = [object_points(board, ci) for _, ci in frames]
    img = [cc.reshape(-1, 2).astype(np.float32) for cc, _ in frames]
    rms, K, D, _, _ = cv2.calibrateCamera(obj, img, size, None, None)
    return rms, K, D


def write_yaml(path, K, D, size, name="pinky_camera"):
    w, h = size
    d = D.flatten().tolist()[:5] + [0.0] * max(0, 5 - D.size)
    P = [K[0, 0], 0, K[0, 2], 0, 0, K[1, 1], K[1, 2], 0, 0, 0, 1, 0]
    fmt = lambda xs: "[" + ", ".join(f"{float(x):.6f}" for x in xs) + "]"
    text = f"""image_width: {w}
image_height: {h}
camera_name: {name}
camera_matrix:
  rows: 3
  cols: 3
  data: {fmt(K.flatten())}
distortion_model: plumb_bob
distortion_coefficients:
  rows: 1
  cols: 5
  data: {fmt(d)}
rectification_matrix:
  rows: 3
  cols: 3
  data: {fmt([1, 0, 0, 0, 1, 0, 0, 0, 1])}
projection_matrix:
  rows: 3
  cols: 4
  data: {fmt(P)}
"""
    with open(os.path.expanduser(path), "w") as f:
        f.write(text)


def report(rms, K, D, size, out):
    w, h = size
    hfov = 2 * np.degrees(np.arctan(w / (2 * K[0, 0])))
    grade = "excellent" if rms < 0.5 else "good" if rms < 1.0 else "bad: redo it, keep the board flat and sharp"
    print(f"\nResult: reprojection error {rms:.3f} px "
          f"({grade})")
    print(f"  fx={K[0, 0]:.1f} fy={K[1, 1]:.1f} cx={K[0, 2]:.1f} cy={K[1, 2]:.1f}  (horizontal field of view {hfov:.1f}°)")
    print(f"  distortion: {np.round(D.flatten()[:5], 4).tolist()}")
    print(f"Saved: {out}")
    print(f"Use: guide_mode.py / vslam_camera.py read {out}")


def preview_msg(gray, col, text):
    from sensor_msgs.msg import CompressedImage
    k = 320 / gray.shape[1]
    vis = cv2.cvtColor(cv2.resize(gray, (320, int(gray.shape[0] * k))), cv2.COLOR_GRAY2BGR)
    if col.last_cc is not None:
        for x, y in col.last_cc.reshape(-1, 2):
            cv2.circle(vis, (int(x * k), int(y * k)), 3, (0, 255, 0), -1)
    color = (0, 200, 0) if text.startswith("OLINDI") else (0, 0, 255)
    cv2.putText(vis, f"{len(col.frames)}/{col.need}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    m = CompressedImage()
    m.format, m.data = "jpeg", cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--square", type=float, default=0.025, help="인쇄된 칸의 한 변, m")
    ap.add_argument("--marker", type=float, default=0.018, help="인쇄된 마커의 한 변, m")
    ap.add_argument("--frames", type=int, default=25)
    ap.add_argument("--topic", default="/camera/image_raw")
    ap.add_argument("--out", default="~/pinky_camera.yaml")
    ap.add_argument("--no-rotate", action="store_true", help="카메라가 거꾸로 달려 있지 않음")
    ap.add_argument("--images", help="ROS 대신 이 폴더의 영상 파일로 캘리브레이션")
    ap.add_argument("--save-frames", help="저장한 프레임을 여기에도 저장 (오프라인 재실행용)")
    args = ap.parse_args()
    out = os.path.expanduser(args.out)

    board, detect = make_board(args.square, args.marker)
    col = Collector(detect, args.frames)

    def prep(img):
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return gray if args.no_rotate else cv2.rotate(gray, cv2.ROTATE_180)

    if args.images:
        files = sorted(glob.glob(os.path.join(os.path.expanduser(args.images), "*.png")) +
                       glob.glob(os.path.join(os.path.expanduser(args.images), "*.jpg")))
        col.need = len(files)
        for f in files:
            col.last_center = None  # 저장한 프레임은 이미 서로 다름
            print(os.path.basename(f), col.offer(prep(cv2.imread(f))))
    else:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import CompressedImage, Image

        rclpy.init()
        node = Node("pinky_camera_calibration")
        preview = node.create_publisher(CompressedImage, "/calib/preview/compressed", qos_profile_sensor_data)
        last_preview = 0.0
        latest = {}

        def cb(m):
            latest["img"] = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)

        node.create_subscription(Image, args.topic, cb, qos_profile_sensor_data)
        print(f"Listening on {args.topic}. Move the board slowly in front of the camera "
              f"(20-60 cm, left/right/top/bottom, tilted)...")
        last_msg, saved = "", 0
        if args.save_frames:
            os.makedirs(os.path.expanduser(args.save_frames), exist_ok=True)
        while not col.done:
            rclpy.spin_once(node, timeout_sec=0.1)
            if "img" not in latest:
                continue
            img = latest.pop("img")
            n_before = len(col.frames)
            gray = prep(img)
            msg = col.offer(gray)
            if time.time() - last_preview > 0.2:   # ~5 Hz, 작은 JPEG: Wi-Fi로도 충분
                last_preview = time.time()
                preview.publish(preview_msg(gray, col, msg))
            if len(col.frames) > n_before and args.save_frames:
                cv2.imwrite(os.path.join(os.path.expanduser(args.save_frames), f"f{saved:02d}.png"), img)
                saved += 1
            if msg != last_msg:
                print(msg)
                last_msg = msg
        node.destroy_node()
        rclpy.try_shutdown()

    if len(col.frames) < 8:
        raise SystemExit(f"Only {len(col.frames)} usable frames: at least 8 are needed.")
    rms, K, D = calibrate(board, col.frames, col.size)
    write_yaml(out, K, D, col.size)
    report(rms, K, D, col.size, out)


if __name__ == "__main__":
    main()
