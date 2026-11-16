"""ROS 2 (Jazzy) 노드: Pinky "안내원" 모드. RTAB-Map이 지도를 그리는 동안 새 장소를 탐색하고,
사람에게 인사하며 (Task 01), 다른 Pinky 로봇을 포함한 그 밖의 모든 것에 양보함 (Task 02).
바닥의 검은 테이프 선은 방을 막음: Pinky는 거기서 되돌아가고 선을 기억하므로
복도만 돌아다님 (robot/line_detector.py).

Pinky에서 실행, bringup, IMU, cam_pub.py, vslam.launch.py (매핑 모드) 다음에:
  python3 ~/guide_robot/robot/guide_mode.py
  python3 ~/guide_robot/robot/guide_mode.py --ros-args -p drive:=false      # 테스트: 제자리에서 보고/말하기만
  python3 ~/guide_robot/robot/guide_mode.py --ros-args -p max_linear:=0.08 -p greet_distance:=0.20

  sub  /scan                     sensor_msgs/LaserScan
  sub  <image_topic>             sensor_msgs/Image, 기본 /vslam/image_raw (이미 똑바로 회전됨, 10 Hz)
  sub  /rtabmap/map              nav_msgs/OccupancyGrid: 미탐색 경계 (프런티어)의 위치
  tf   map -> base_footprint     지도 위 로봇 위치 (RTAB-Map 제공)
  pub  /cmd_vel                  geometry_msgs/Twist (stamped:=true이면 TwistStamped)
  pub  /guide/state              std_msgs/String  EXPLORE | PATROL | LOOK | APPROACH | GREET | WAIT | YIELD | BACKUP | ESCAPE | LINE | TURN
  pub  /guide/person             std_msgs/Bool    앞에 사람이 있음
  pub  /guide/debug/compressed   sensor_msgs/CompressedImage, 사람 박스와 바닥 선이 그려진 카메라 영상 (debug_image:=true)
  LED (pinkylib, 8 px)           초록 = 앞에 사람, 빨강 = 다른 장애물 / Pinky, 노랑 = 검은 바닥 선, 꺼짐 = 비어 있음
  LCD                            인사 중에는 인사 문장, 그 외에는 "인공지능 핑키 안내원" (robot/screen.py)

동작과 임계값: robot/guide_core.py. 사용 안내: README.md.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage, Image, LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformListener

from guide_core import FrontierPlanner, GuideBrain, Params, Person, free_distance, scan_points, seg_dist, wall_points
from line_detector import CameraLine, IRLine
from person_detector import DEFAULT_MODEL, PersonDetector, draw
from melody import play as play_tune
from led import Leds
from screen import Screen

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GREETING = "안녕하세요, 인공지능 핑키 안내원입니다. 무엇을 도와 드릴까요?"
IDLE_TEXT = "인공지능 핑키 안내원"


def yaw_of(q) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class Speaker:
    """미리 녹음한 인사 음성을 재생 (robot/make_greeting.py); WAV가 없으면 espeak-ng."""

    def __init__(self, wav: str, device: str, log, melody: bool = False):
        self.wav, self.device, self.log = os.path.expanduser(wav), device, log
        self.buzzer = self.tune = None
        self.melody = melody
        if melody:
            self.open_buzzer(warn=True)
        if os.path.exists(self.wav):
            log.info(f"greeting: {self.wav}")
        elif shutil.which("espeak-ng"):
            log.warn(f"{self.wav} not found: using espeak-ng (low voice quality). Run make_greeting.py")
        else:
            log.error(f"neither {self.wav} nor espeak-ng found: Pinky cannot speak")

    def say(self):
        """부저로 멜로디, 그다음 녹음된 음성 (스피커가 동작하면). 호출한 쪽을 막지 않음."""
        if self.tune is not None and self.tune.is_alive():
            return  # 아직 인사 중
        self.tune = threading.Thread(target=self._greet, daemon=True)
        self.tune.start()

    def open_buzzer(self, warn: bool = False):
        """Pinky 자체 GPIO 부저 (pinkylib): 짧은 멜로디, 스피커 없이도 동작.
        다른 프로그램이 지금 GPIO를 잡고 있으면 다음 인사 때 다시 시도."""
        try:
            from pinkylib import Buzzer
            self.buzzer = Buzzer()
            self.buzzer.buzzer_start(1500)
        except Exception as e:
            self.buzzer = None
            if warn:
                self.log.warn(f"buzzer busy ({e}). Another program (melody.py?) may be running; "
                              "will retry at the next greeting")

    def _greet(self):
        if self.buzzer is None and self.melody:
            self.open_buzzer()
        if self.buzzer is not None:
            play_tune(self.buzzer)
        if os.path.exists(self.wav):
            cmd = ["aplay", "-q"] + (["-D", self.device] if self.device else []) + [self.wav]
        elif shutil.which("espeak-ng"):
            cmd = ["espeak-ng", "-v", "ko", "-s", "150", GREETING]
        else:
            return
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.log.error(f"no sound: {e}")


class GuideMode(Node):
    def __init__(self):
        super().__init__("pinky_guide_mode")
        p = self.declare_parameter
        image_topic = p("image_topic", "/vslam/image_raw").value
        self.rotate_180 = p("rotate_180", False).value  # 원본 /camera/image_raw를 쓸 때만 true
        calib = os.path.expanduser(p("camera_info_file", "~/pinky_camera.yaml").value)
        hfov = math.radians(p("hfov_deg", 57.6).value)
        model = p("model", DEFAULT_MODEL).value
        self.detect_hz = p("detect_hz", 3.0).value
        self.drive = p("drive", True).value
        self.stamped = p("stamped", False).value
        self.debug_image = p("debug_image", True).value
        self.base_frame = p("base_frame", "base_footprint").value
        self.map_frame = p("map_frame", "map").value
        cmd_topic = p("cmd_vel_topic", "/cmd_vel").value
        # 로봇 중심에 이만큼 가까운 LiDAR 점은 Pinky 자신 (첫 테스트: ~4 cm에 35개 점)
        self.self_radius = p("self_radius", 0.08).value

        prm = Params(
            max_lin=p("max_linear", 0.10).value,
            max_ang=p("max_angular", 0.8).value,
            half_width=p("half_width", 0.06).value,
            corridor=p("corridor", True).value,
            stop_dist=p("stop_distance", 0.11).value,
            yield_wait=p("yield_wait", 1.0).value,
            greet_dist=p("greet_distance", 0.16).value,
            look_around=p("look_around", False).value,
            greet_cooldown=p("greet_cooldown", 20.0).value,
            person_wait_max=p("person_wait_max", 12.0).value,
            line_stop=p("line_stop", 0.11).value,
        )
        self.brain = GuideBrain(prm)
        self.planner = FrontierPlanner(goal_timeout=p("goal_timeout", 40.0).value)
        self.planner.join_reach = p("tape_corner_join", 0.12).value  # > 두 테이프 박스 사이의 틈이면 그 틈을 막아 버림
        self.speaker = Speaker(p("greeting_wav", os.path.join(ROOT, "sounds", "greeting_ko.wav")).value,
                               p("audio_device", "").value, self.get_logger(), p("melody", True).value)

        self.rainbow = p("led_rainbow", True).value  # 돌아다니는 동안 무지개색: 사람들이 Pinky를 알아봄
        self.leds = Leds(p("led_brightness", 80).value, self.get_logger().warn) if p("led", True).value else None
        self.screen = None
        if p("screen", True).value:
            self.screen = Screen((p("screen_width", 320).value, p("screen_height", 240).value),
                                 p("screen_rotate", 0).value, self.get_logger().info,
                                 p("face_image", "").value)
            self.get_logger().info(f"screen: {self.screen.backend}")
            self.screen.text(IDLE_TEXT)

        self.fx, self.cx = None, None
        fy = cy = None
        if os.path.exists(calib):
            import yaml
            with open(calib) as f:
                k = yaml.safe_load(f)["camera_matrix"]["data"]
            self.fx, self.cx, fy, cy = float(k[0]), float(k[2]), float(k[4]), float(k[5])
        self.hfov = hfov

        # 검은 바닥 선: 카메라 (캘리브레이션과 카메라 위치 필요, vslam.launch.py와 같은 값)
        self.cam_line = None
        if p("line", True).value:
            if self.fx is None:
                self.get_logger().error(f"{calib} not found: black line detection off (calibrate the camera)")
            else:
                self.cam_line = CameraLine(self.fx, fy, self.cx, cy, p("cam_x", 0.03).value, p("cam_z", 0.062).value,
                                           p("cam_pitch", 0.072).value, p("line_max_distance", 0.30).value,
                                           p("line_dark_ratio", 0.55).value, p("line_dark_max", 80).value,
                                           p("line_min_length", 0.08).value)
        self.line_frames = p("line_frames", 2).value  # 연속 이만큼의 프레임에서 보이면 = 진짜
        self.ir_line = None
        if p("ir_line", True).value:  # 바닥 IR 센서, robot/line_detector.py --probe-ir 결과 기준
            try:
                self.ir_line = IRLine(p("ir_method", "read_ir").value, p("ir_margin", 500.0).value,
                                      p("ir_black_high", True).value, 2, self.get_logger().warn,
                                      p("ir_margin_avg", 300.0).value, p("ir_order", "LMR").value,
                                      white_below=p("ir_white", 2100.0).value)
            except Exception as e:
                self.get_logger().error(f"IR line sensor off: {e}")

        try:
            self.det = PersonDetector(model, conf=p("person_conf", 0.45).value)
            self.person_sure = p("person_conf_sure", 0.6).value  # 박스는 이 점수부터 사람으로 인정
            self.person_frames = p("person_frames", 3).value     # ... 연속 이만큼의 카메라 프레임에서
            self.person_streak = 0
            self.get_logger().info(f"person detector: {self.det.backend}, {model}")
        except Exception as e:  # 모델 없음: 탐색과 양보는 하지만 인사는 하지 않음
            self.det = None
            self.get_logger().error(f"person detection off: {e}")

        self.tf = Buffer()
        TransformListener(self.tf, self)
        self.lidar_tf = None
        self.pts = np.zeros((0, 2))
        self.scan_t = 0.0
        self.frame = None              # (monotonic 시간, bgr) 최신 카메라 영상
        self.people: list[Person] = []
        self.people_t = 0.0
        self.boxes = []
        self.line_events: list = []
        self.last_cmd = (0.0, 0.0)
        self.ir_t = -1e9
        self.ir_sides = None  # 각 LINE의 (t, x, y), 갇힌 상황을 알아채기 위해
        self.lock = threading.Lock()
        self.line = None               # 최신 프레임에서 본 (시간, Line) 검은 바닥 선
        self.line_hits = 0
        self.line_frame_t = 0.0
        self.line_note_t = 0.0
        self.grid = None
        self.goal = None
        self.t0 = time.monotonic()
        self.last_state = ""

        self.cmd_pub = self.create_publisher(TwistStamped if self.stamped else Twist, cmd_topic, 10)
        self.state_pub = self.create_publisher(String, "/guide/state", 10)
        self.person_pub = self.create_publisher(Bool, "/guide/person", 10)
        self.dbg_pub = self.create_publisher(CompressedImage, "/guide/debug/compressed", qos_profile_sensor_data)
        self.create_subscription(LaserScan, "/scan", self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Image, image_topic, self.on_image, qos_profile_sensor_data)
        map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, p("map_topic", "/rtabmap/map").value, self.on_map, map_qos)
        self.create_timer(0.1, self.control)
        self.create_timer(1.0, self.plan)
        self.running = True
        if self.det is not None:
            threading.Thread(target=self.detect_loop, daemon=True).start()
        self.get_logger().info(f"guide mode ready (drive={self.drive}, camera {image_topic})")

    # ---------- 입력 ----------
    def on_scan(self, m: LaserScan):
        if self.lidar_tf is None:
            try:
                t = self.tf.lookup_transform(self.base_frame, m.header.frame_id, Time())
                tr = t.transform.translation
                self.lidar_tf = (tr.x, tr.y, yaw_of(t.transform.rotation))
                self.get_logger().info("lidar on robot: x=%.3f y=%.3f yaw=%.0f°" % (
                    self.lidar_tf[0], self.lidar_tf[1], math.degrees(self.lidar_tf[2])))
            except Exception:
                if time.monotonic() - self.t0 < 5.0:
                    return
                self.lidar_tf = (0.0, 0.0, 0.0)
                self.get_logger().warn(f"TF {self.base_frame}->{m.header.frame_id} missing: assuming LiDAR 0° = front")
        self.pts = scan_points(m.ranges, m.angle_min, m.angle_increment, m.range_min, m.range_max,
                               self.lidar_tf, self.self_radius)
        self.scan_t = time.monotonic()

    def on_image(self, m: Image):
        img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)
        if m.encoding == "rgb8":
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        if self.rotate_180:
            img = cv2.rotate(img, cv2.ROTATE_180)
        with self.lock:
            self.frame = (time.monotonic(), img)

    def on_map(self, m: OccupancyGrid):
        self.grid = m

    # ---------- 사람 인식 (별도 스레드: Pi에서 프레임당 ~0.1-0.3 s) ----------
    def detect_loop(self):
        done_t = 0.0
        while self.running and rclpy.ok():
            with self.lock:
                f = self.frame
            if f is None or f[0] <= done_t:
                time.sleep(0.02)
                continue
            t_start = time.monotonic()
            done_t, img = f
            boxes = self.det.detect(img)
            h, w = img.shape[:2]
            fx = self.fx or (w / 2) / math.tan(self.hfov / 2)
            cx = self.cx if self.cx is not None else w / 2
            # YOLO가 person_frames 프레임 연속으로 확신할 때만 (person_conf_sure) 사람: 박스, 케이블,
            # 다른 Pinky 위의 약한 박스 하나에도 인사했었음 (2026-10-29)
            sure = [b for b in boxes if b[4] >= self.person_sure]
            self.person_streak = self.person_streak + 1 if sure else 0
            people = []
            for x1, y1, x2, y2, _ in (sure if self.person_streak >= self.person_frames else []):
                bearing = -math.atan2((x1 + x2) / 2 - cx, fx)
                people.append(Person(bearing, self.lidar_range(bearing), (y2 - y1) / h))
            with self.lock:
                self.people, self.people_t, self.boxes = people, done_t, boxes
            if self.debug_image:
                vis = draw(img.copy(), boxes)
                ln = self.line
                if ln is not None and done_t - ln[0] < 0.5:
                    cv2.drawContours(vis, [x.contour for x in ln[1] if x.contour is not None], -1, (0, 255, 255), 2)
                cv2.putText(vis, self.brain.state, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                msg = CompressedImage(format="jpeg")
                msg.header.stamp, msg.header.frame_id = self.get_clock().now().to_msg(), "camera_optical_frame"
                msg.data = cv2.imencode(".jpg", cv2.resize(vis, (320, 240)), [cv2.IMWRITE_JPEG_QUALITY, 60])[1].tobytes()
                self.dbg_pub.publish(msg)
            time.sleep(max(0.0, 1.0 / self.detect_hz - (time.monotonic() - t_start)))

    def lidar_range(self, bearing: float, half: float = math.radians(6)) -> float | None:
        pts = self.pts
        if len(pts) == 0:
            return None
        a = np.arctan2(pts[:, 1], pts[:, 0])
        d = np.hypot(pts[:, 0], pts[:, 1])
        sel = d[(np.abs(a - bearing) < half) & (d < 3.0)]
        return float(sel.min()) if len(sel) else None

    # ---------- 탐색 목표 ----------
    def robot_pose(self):
        try:
            t = self.tf.lookup_transform(self.map_frame, self.base_frame, Time())
        except Exception:
            return None
        return t.transform.translation.x, t.transform.translation.y, yaw_of(t.transform.rotation)

    def plan(self):
        g, pose = self.grid, self.robot_pose()
        if g is None or pose is None:
            return
        o = g.info.origin.position
        grid = np.array(g.data, dtype=np.int8).reshape(g.info.height, g.info.width)
        was_done = self.planner.done
        args = (grid, g.info.resolution, o.x, o.y, pose[0], pose[1], time.monotonic())
        goal = self.planner.update(*args)
        if time.monotonic() - self.t0 > 30.0:  # 처음 지도 업데이트는 항상 아주 작음
            self.brain.explored = self.planner.done
            if self.planner.done:
                old = self.planner.patrol
                goal = self.planner.patrol_goal(*args)
                if goal != old and self.planner.patrol_reached:
                    self.brain.look(time.monotonic())  # 도착: 주변을 둘러보며 사람 찾기
            if self.planner.done and not was_done:
                self.get_logger().info("Area explored (no new frontier). Now roaming to look for people (PATROL)")
        # 목표로 곧장 가지 않고 빈 경로를 따라 ~35 cm 앞의 점으로 조향 (좁은 복도)
        self.goal = self.planner.waypoint(grid, g.info.resolution, o.x, o.y, pose[0], pose[1], goal)

    def goal_bearing(self, pose):
        """로봇 기준 현재 경유점의 (방위, 거리), 없으면 (None, None)."""
        if self.goal is None or pose is None:
            return None, None
        dx, dy = self.goal[0] - pose[0], self.goal[1] - pose[1]
        return math.atan2(dy, dx) - pose[2], math.hypot(dx, dy)

    # ---------- 제어 루프 ----------
    def control(self):
        now = time.monotonic()
        if now - self.scan_t > 0.5:  # LiDAR 없음 = 앞을 못 봄: 절대 움직이지 않음
            self.publish(0.0, 0.0)
            return
        with self.lock:
            people = self.people if now - self.people_t < 1.0 else []
        pose = self.robot_pose()
        line = self.check_line(now, pose)
        walls = wall_points(self.planner.walls, *pose) if pose is not None and self.planner.walls else None
        bearing, dist = self.goal_bearing(pose)
        wiggles, robots = self.brain.wiggles, self.brain.robots
        cmd = self.brain.step(now, self.pts, people, bearing, line, walls, dist, pose, self.ir_sides)
        if self.brain.wiggles != wiggles:
            self.get_logger().info("turning left-right on one spot: these ways count as visited, choosing another way")
        if self.brain.robots != robots:
            d, b = self.brain.robot_seen
            self.get_logger().info(f"another Pinky ahead ({d:.2f} m, {math.degrees(b):+.0f}°): giving way, backing up, "
                                   f"choosing another way")
        if cmd.say:
            seen = ", ".join(f"{math.degrees(q.bearing):+.0f}° {q.dist:.2f} m" if q.dist is not None else
                             f"{math.degrees(q.bearing):+.0f}° no LiDAR" for q in people) or "seen a moment ago"
            self.get_logger().info(f"person: greeting (person {seen}; path free {free_distance(self.pts, 0.0, self.brain.p.half_width, 1.0):.2f} m)")
            self.speaker.say()
            if self.screen:
                self.screen.text(GREETING, None)  # 인사: 글자만, 크게
        state = self.brain.state
        if self.leds:  # 초록: 앞에 사람, 빨강: 그 밖의 장애물, 꺼짐: 길이 비어 있음
            self.leds.set("green" if state in ("GREET", "WAIT") else
                          "red" if state in ("YIELD", "BACKUP", "ESCAPE") else
                          "yellow" if state in ("LINE", "TURN") else
                          "rainbow" if self.rainbow else "off")  # EXPLORE/PATROL/LOOK/APPROACH: 사람을 찾는 중
        if state != self.last_state:
            self.get_logger().info(f"{self.last_state or '-'} -> {state}")
            if state == "YIELD":
                self.log_obstacle()
            if state == "LINE":
                self.planner.give_up()  # 목표가 선 뒤에 있었음: 다른 목표 선택
                if pose is not None:
                    self.brain.avoid_ahead(pose)  # 복도 모드: 당분간 이 길을 다시 선택하지 않음
                if now - self.ir_t > 2.0:  # IR이 테이프를 직접 감지함: 여기 저장된 선은 진짜이므로 유지
                    self.unstick(now)
            if self.screen and self.last_state in ("GREET", "WAIT") and state not in ("GREET", "WAIT"):
                self.screen.text(IDLE_TEXT)
            self.last_state = state
        self.state_pub.publish(String(data=state))
        self.person_pub.publish(Bool(data=state in ("GREET", "WAIT")))
        self.last_cmd = (cmd.lin, cmd.ang)
        if self.drive:
            self.publish(cmd.lin, cmd.ang)

    def unstick(self, now: float):
        """같은 자리에서 LINE이 반복됨 = 저장된 선에 갇힘 (TURN이 빠져나갈 길을 못 찾음):
        Pinky 바로 주변의 선을 잊음."""
        pose = self.robot_pose()
        if pose is None:
            return
        self.line_events = [(t, x, y) for t, x, y in self.line_events if now - t < 60.0] + [(now, pose[0], pose[1])]
        near = [e for e in self.line_events if math.hypot(e[1] - pose[0], e[2] - pose[1]) < 0.15]
        if len(near) >= 3:
            n = self.planner.forget_near(pose[0], pose[1], 0.20)
            self.line_events = []
            self.get_logger().warn(f"boxed in by saved lines (LINE {len(near)}x here): forgot {n} lines within "
                                   f"20 cm, the camera and IR will find the real tape again")

    def check_line(self, now: float, pose) -> float | None:
        """Pinky 경로 위 검은 바닥 선까지의 거리 (m), 없으면 None. 새 선은 지도에 저장됨."""
        found: list = []
        if self.cam_line is not None:
            with self.lock:
                f = self.frame
            if f is not None and f[0] > self.line_frame_t and now - f[0] < 0.5:
                self.line_frame_t = f[0]
                with self.lock:
                    boxes = list(self.boxes) if now - self.people_t < 1.0 else []
                if self.brain.state in ("GREET", "WAIT"):
                    lines = []  # 카메라가 사람을 보고 있음: 그 사람의 신발은 테이프가 아님
                else:
                    lines = [ln for ln in self.cam_line.detect_all(f[1], exclude=boxes) if not self.lidar_on(ln, now)]
                self.line_hits = self.line_hits + 1 if lines else 0
                self.line = (f[0], lines) if lines else None
            if self.line is not None and now - self.line[0] < 0.5 and self.line_hits >= self.line_frames:
                found = self.line[1]
        segs = [(ln.p1, ln.p2, ln.dist) for ln in found]
        # IR은 전진 중에만: 테이프 위에서 제자리 회전하면 각도마다 다시 저장되어
        # Pinky가 갇힘 (2026-10-28 테스트); 복도 회전은 EXPLORE/PATROL에서도 일어나므로 명령을 확인
        self.ir_sides = None
        if self.ir_line is not None and self.brain.p.corridor:
            # 복도 모드: 브레인이 측면 테이프에서 멀어지도록 조향하고, 길을 가로지르는 테이프에서만 되돌아감
            self.ir_line.black()
            if self.brain.state in ("EXPLORE", "PATROL") and any(self.ir_line.sides.values()):
                self.ir_sides = dict(self.ir_line.sides)
                if now - self.ir_t > 2.0:
                    self.get_logger().info(f"IR: tape under {''.join(k for k, v in self.ir_sides.items() if v)}")
                self.ir_t = now
                if self.ir_sides["L"] and self.ir_sides["R"] and pose is not None and abs(self.last_cmd[1]) < 0.3:
                    # 직진 중 앞 양쪽 모서리가 모두 검은 테이프 위: 테이프가 길을 가로지름.
                    # Pinky 앞코를 가로질러 10 cm를 저장해서, 복도 선택이 다시 그쪽으로 가지 않게 함
                    # (2026-10-29: "tape under LMR" -> LINE -> TURN -> 같은 테이프로 복귀, 4 s마다 반복)
                    segs_ir = [((0.05, 0.05), (0.05, -0.05), 0.05)]
                    self.save_lines(segs_ir, pose, "IR")
        elif self.ir_line is not None and self.brain.state in ("EXPLORE", "PATROL") \
                and self.last_cmd[0] > 0.005 and abs(self.last_cmd[1]) < 0.3 and self.ir_line.black():
            # 앞 가장자리의 IR 센서 3개, 바퀴 축보다 ~4 cm 앞: 정지하고 후진하지만 지도에는 저장하지 않음:
            # IR 감지 하나로는 테이프 방향을 알 수 없고, 18 cm 복도를 가로질러 추측한 12 cm 선은
            # 복도를 막아 버림 (시뮬레이션 2026-10-28)
            self.get_logger().info("IR: black tape under Pinky's nose")
            self.ir_t = now
            return 0.04
        if not segs:
            return None
        dist = min(d for _, _, d in segs)
        # 회전 중에는 SLAM 자세가 카메라 프레임보다 늦으므로 (0.6 rad/s에서 10-20도), 같은 테이프가
        # 프레임마다 지도의 새 위치에 저장됨 (2026-10-29: ESCAPE 4 s 동안 "저장된" 선 8개). 정지만 하고 저장은 나중에.
        if pose is not None and abs(self.last_cmd[1]) < 0.3:
            self.save_lines(segs, pose, "camera")
        return dist if math.isfinite(dist) else None

    def save_lines(self, segs, pose, src: str):
        c, s = math.cos(pose[2]), math.sin(pose[2])
        for (ax, ay), (bx, by), d in segs:
            if self.planner.add_line(pose[0] + c * ax - s * ay, pose[1] + s * ax + c * ay,
                                     pose[0] + c * bx - s * by, pose[1] + s * bx + c * by):
                where = f"{d:.2f} m ahead" if math.isfinite(d) else f"beside the path ({(ax + bx) / 2:.2f} m ahead, {(ay + by) / 2:+.2f} m left)"
                self.get_logger().info(f"black line {where} ({src}): closed-off room, saved as line "
                                       f"{len(self.planner.lines)}, never crossing it")

    def lidar_on(self, ln, now: float) -> bool:
        """어두운 줄무늬 바로 위에 LiDAR가 보는 무언가 (신발, 검은 Pinky, 어두운 박스)가 있으면 테이프가 아님.
        물체는 줄무늬를 길이 방향으로 덮음. 문간을 가로지르는 테이프는 양 끝에서만 벽에 닿고, 좁은
        복도의 테이프는 옆에 벽이 있으므로, 줄무늬 근처의 LiDAR 점 몇 개로는 충분하지 않음."""
        pts = self.pts
        if len(pts) == 0:
            return False
        (ax, ay), (bx, by) = ln.p1, ln.p2
        vx, vy = bx - ax, by - ay
        n = math.hypot(vx, vy)
        if n < 1e-6:
            return False
        near = pts[np.hypot(pts[:, 0], pts[:, 1]) < 0.6]
        t = ((near[:, 0] - ax) * vx + (near[:, 1] - ay) * vy) / (n * n)
        off = np.abs((near[:, 0] - ax) * vy - (near[:, 1] - ay) * vx) / n
        inner = (t > 0.15) & (t < 0.85) & (off < 0.04)   # 양 끝은 건너뜀: 문틀, 복도 벽
        bins = np.unique(np.floor(t[inner] * n / 0.02))   # LiDAR 점이 있는 줄무늬의 2 cm 조각들
        cover = min(1.0, len(bins) * 0.02 / (0.7 * n))
        if cover > 0.5:
            if now - self.line_note_t > 3.0:
                self.line_note_t = now
                self.get_logger().info(f"dark stripe at ({(ax + bx) / 2:.2f}, {(ay + by) / 2:+.2f}) m, but the LiDAR "
                                       f"sees something along {cover * 100:.0f}% of it: an object, not tape")
            return True
        return False

    def log_obstacle(self):
        """우리를 멈추게 한 물체의 위치 (로봇 중심 기준 x 앞, y 왼쪽): 진짜 박스와 자기 몸 감지를 구별."""
        pts, hw = self.pts, self.brain.p.half_width
        sel = pts[(pts[:, 0] > 0) & (np.abs(pts[:, 1]) < hw)] if len(pts) else pts
        if len(sel):
            x, y = sel[np.argmin(sel[:, 0])]
            self.get_logger().info(f"  obstacle ahead: {x:.2f} m ahead, {y:+.2f} m left ({math.degrees(math.atan2(y, x)):+.0f}°); "
                                   f"{len(sel)} points in the corridor")

    def publish(self, lin: float, ang: float):
        if self.stamped:
            m = TwistStamped()
            m.header.stamp = self.get_clock().now().to_msg()
            m.header.frame_id = self.base_frame
            t = m.twist
        else:
            m = t = Twist()
        t.linear.x, t.angular.z = float(lin), float(ang)
        self.cmd_pub.publish(m)


def others_running() -> list[str]:
    """다른 guide/melody/led 프로그램이 부저, LED, LCD GPIO를 잡고 있음 ("busy" 오류)."""
    try:
        out = subprocess.run(["pgrep", "-af", r"guide_mode\.py|melody\.py|led\.py|screen\.py"],
                             capture_output=True, text=True).stdout
    except OSError:
        return []
    return [ln for ln in out.splitlines() if ln and int(ln.split()[0]) != os.getpid()]


def main():
    busy = others_running()
    if busy:
        print("WARNING: these programs are holding the buzzer/LED/screen, stop them first "
              "(pkill -f guide_mode.py):\n  " + "\n  ".join(busy))
    # Ctrl+C에서도 컨텍스트를 유지해서 아래 정지 명령을 보낼 수 있게 함
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    n = GuideMode()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.running = False
        try:
            for _ in range(3):  # Twist는 래치되지 않음: 정지 명령을 몇 번 보냄
                n.publish(0.0, 0.0)
                time.sleep(0.05)
        except Exception as e:
            print(f"stop not sent: {e}")
        if n.screen:
            n.screen.close()
        if n.leds:
            n.leds.close()
        n.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
