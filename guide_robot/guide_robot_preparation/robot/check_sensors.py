"""SLAM / Nav2 전에 Pinky가 발행하는 모든 센서를 찾아서 확인.

  python3 robot/check_sensors.py                 # 5 s 동안 수신, 로봇은 움직이지 않음
  python3 robot/check_sensors.py --seconds 10
  python3 robot/check_sensors.py --motion        # 제자리에서 ~3 s 회전도 함: 오도메트리 vs IMU vs LiDAR
  python3 robot/check_sensors.py --motion --stamped   # 베이스가 /cmd_vel에서 TwistStamped를 기대할 때
  python3 robot/check_sensors.py --gyro-deg      # 이 Pinky: /imu_raw 자이로는 deg/s
  python3 robot/check_sensors.py --skip-camera   # 노트북에서: 원본 카메라 영상을 Wi-Fi로 받지 않음

토픽은 메시지 타입으로 찾으므로 토픽 이름을 가정하지 않음. 토픽마다 주기 (Hz), 메시지 사이의
가장 긴 공백 (Wi-Fi 끊김이 여기에 나타남), 데이터 타당성 검사를 출력하고, 그다음 SLAM에
필요한 TF 트리를 확인함.
Pinky에서도 노트북에서도 실행 가능 (같은 ROS_DOMAIN_ID / ROS_STATIC_PEERS).
"""
from __future__ import annotations

import argparse
import math
import socket
import time

import numpy as np

# 메시지 타입 -> (라벨, 정상 최소 주기 Hz; 0 = 주기 검사 안 함)
KNOWN = {
    "sensor_msgs/msg/LaserScan": ("LiDAR", 4),
    "sensor_msgs/msg/PointCloud2": ("3D points", 1),
    "sensor_msgs/msg/Image": ("Camera", 5),
    "sensor_msgs/msg/CompressedImage": ("Camera (compressed)", 5),
    "sensor_msgs/msg/CameraInfo": ("Camera calibration", 0),
    "sensor_msgs/msg/Imu": ("IMU", 30),
    "sensor_msgs/msg/MagneticField": ("Magnetometer", 0),
    "sensor_msgs/msg/Range": ("Range sensor", 2),
    "sensor_msgs/msg/BatteryState": ("Battery", 0),
    "sensor_msgs/msg/JointState": ("Wheels/joints", 5),
    "sensor_msgs/msg/Temperature": ("Temperature", 0),
    "nav_msgs/msg/Odometry": ("Odometry", 10),
    "std_msgs/msg/Float32": ("Battery", 0),  # Pinky: /battery/percent, /battery/voltage
}


GYRO_SCALE = 1.0  # --gyro-deg이면 pi/180


def yaw_of(q) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


# ---------- 타입별 검사: msg -> (요약, [경고]) ----------

def check_scan(m):
    r = np.asarray(m.ranges, dtype=np.float32)
    ok = np.isfinite(r) & (r >= m.range_min) & (r <= m.range_max)
    w = []
    if r.size == 0:
        return "empty scan", ["LiDAR gives no points"]
    frac = ok.mean()
    if frac < 0.5:
        w.append(f"only {frac:.0%} of points are valid: is the lens clean and unobstructed?")
    near = r[ok].min() if ok.any() else float("nan")
    far = r[ok].max() if ok.any() else float("nan")
    if ok.any() and near < 0.05:
        w.append(f"{near:.2f} m: LiDAR sees its own body (needs range_min or a filter)")
    fov = math.degrees(m.angle_max - m.angle_min)
    return (f"{r.size} points, {fov:.0f}°, valid {frac:.0%}, {near:.2f}–{far:.2f} m, frame={m.header.frame_id}", w)


def _brightness(w):
    def judge(mean):
        if mean < 15:
            w.append("image too dark: lens cap or lighting?")
        elif mean > 240:
            w.append("image too bright (white)")
        return f"brightness {mean:.0f}/255"
    return judge


def check_image(m):
    w = []
    if m.width == 0 or not m.data:
        return "empty image", ["camera gives no image"]
    s = f"{m.width}x{m.height} {m.encoding}, frame={m.header.frame_id}"
    if m.encoding in ("mono8", "bgr8", "rgb8", "bgra8", "rgba8", "yuv422", "yuv422_yuy2"):
        s += ", " + _brightness(w)(np.frombuffer(bytes(m.data), np.uint8).mean())
    return s, w


def check_compressed(m):
    w = []
    s = f"{m.format}, {len(m.data) // 1024} KB, frame={m.header.frame_id}"
    try:
        import cv2
        img = cv2.imdecode(np.frombuffer(bytes(m.data), np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            w.append("could not decode the image")
        else:
            s = f"{img.shape[1]}x{img.shape[0]} " + s + ", " + _brightness(w)(img.mean())
    except ImportError:
        pass
    return s, w


def check_info(m):
    calibrated = m.k[0] > 0 and any(abs(d) > 0 for d in m.d)
    return (f"{m.width}x{m.height}, fx={m.k[0]:.0f}, model={m.distortion_model or '-'}",
            [] if calibrated else ["camera not calibrated (visual SLAM will not work)"])


def check_imu(m):
    w = []
    a = m.linear_acceleration
    g = math.sqrt(a.x ** 2 + a.y ** 2 + a.z ** 2)
    gyro = GYRO_SCALE * math.sqrt(m.angular_velocity.x ** 2 + m.angular_velocity.y ** 2 + m.angular_velocity.z ** 2)
    if 0.8 < g < 1.2:
        w.append(f"|a|={g:.2f}: acceleration is in g, ROS expects m/s²")
    elif not 8.8 < g < 10.8:
        w.append(f"|a|={g:.2f} m/s², should be about 9.8 (robot standing still)")
    if gyro > 0.05:
        w.append(f"gyro {gyro:.3f} rad/s: if the robot is still, there is drift (bias)"
                 + ("" if GYRO_SCALE != 1.0 else ", or the gyro is in deg/s (check with --motion, then --gyro-deg)"))
    q = "yes" if m.orientation_covariance[0] != -1 else "no"
    return (f"|a|={g:.2f} m/s², gyro={gyro:.3f} rad/s, orientation {q}, "
            f"frame={m.header.frame_id}", w)


def check_odom(m):
    p, t = m.pose.pose.position, m.twist.twist
    return (f"x={p.x:.2f} y={p.y:.2f} yaw={math.degrees(yaw_of(m.pose.pose.orientation)):.0f}°, "
            f"v={t.linear.x:.2f} w={t.angular.z:.2f}, {m.header.frame_id}→{m.child_frame_id}", [])


def check_range(m):
    w = []
    if not (m.min_range <= m.range <= m.max_range):
        w.append(f"value {m.range:.2f} out of range ({m.min_range}–{m.max_range}); nothing in front?")
    kind = {0: "ultrasound", 1: "infrared"}.get(m.radiation_type, "?")
    return f"{m.range:.2f} m ({kind}), frame={m.header.frame_id}", w


def check_battery(m):
    pct = m.percentage * 100 if m.percentage <= 1.0 else m.percentage
    w = ["battery low, charge it"] if not math.isnan(pct) and pct < 20 else []
    return f"{m.voltage:.2f} V, {pct:.0f}%", w


def check_joints(m):
    return f"{len(m.name)}: {', '.join(m.name[:4])}", []


def check_cloud(m):
    return f"{m.width * m.height} points, frame={m.header.frame_id}", []


def check_float_battery(name, m):
    if name.endswith("percent"):
        pct = m.data * 100 if m.data <= 1.0 else m.data
        return f"{pct:.0f}%", (["battery low, charge it"] if pct < 20 else [])
    if name.endswith("voltage"):
        return f"{m.data:.2f} V", []
    return f"{m.data:.2f}", []


def check_generic(m):
    return "", []


CHECKS = {
    "sensor_msgs/msg/LaserScan": check_scan,
    "sensor_msgs/msg/Image": check_image,
    "sensor_msgs/msg/CompressedImage": check_compressed,
    "sensor_msgs/msg/CameraInfo": check_info,
    "sensor_msgs/msg/Imu": check_imu,
    "sensor_msgs/msg/Range": check_range,
    "sensor_msgs/msg/BatteryState": check_battery,
    "sensor_msgs/msg/JointState": check_joints,
    "sensor_msgs/msg/PointCloud2": check_cloud,
    "nav_msgs/msg/Odometry": check_odom,
    "std_msgs/msg/Float32": None,  # Pinky의 /battery/* 토픽, check_float_battery가 처리
}


# ---------- ROS 부분 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--motion", action="store_true", help="제자리에서 ~3 s 회전해 오도메트리 / IMU / LiDAR 비교")
    ap.add_argument("--cmd-vel", default="/cmd_vel")
    ap.add_argument("--stamped", action="store_true")
    ap.add_argument("--gyro-deg", action="store_true", help="IMU 자이로가 deg/s로 발행됨 (이 Pinky)")
    ap.add_argument("--skip-camera", action="store_true", help="카메라 영상을 구독하지 않음 (노트북에서 사용)")
    args = ap.parse_args()
    global GYRO_SCALE
    if args.gyro_deg:
        GYRO_SCALE = math.pi / 180

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.time import Time
    from rosidl_runtime_py.utilities import get_message
    import tf2_ros

    rclpy.init()
    node = Node("pinky_sensor_check")
    tf_buf = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buf, node)

    # Wi-Fi / static peers로 찾는 데 몇 초 걸릴 수 있음; 목록이 안정될 때까지 기다림
    print("Discovering topics...")
    found, stable_since, end = {}, time.time(), time.time() + 10.0
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
        now = {n: t[0] for n, t in node.get_topic_names_and_types() if t}
        if now.keys() != found.keys():
            found, stable_since = now, time.time()
        elif found and time.time() - stable_since > 2.0:
            break
    topics = {n: t for n, t in found.items()
              if (t in KNOWN and t != "std_msgs/msg/Float32") or (n.startswith("/battery") and t == "std_msgs/msg/Float32")}
    cams = ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")
    skipped = sorted(n for n, t in topics.items() if args.skip_camera and t in cams)
    for n in skipped:
        del topics[n]
    if not topics:
        other = sorted(n for n in found if n not in ("/rosout", "/parameter_events"))
        print("No sensor topics found.")
        if other:
            print("Visible topics (not sensor types):")
            for n in other:
                print(f"  {n}  [{found[n]}]")
        else:
            print("No topics visible at all: is Pinky bringup running? Are ROS_DOMAIN_ID and "
                  "ROS_STATIC_PEERS set in the bringup terminal?")
        return

    stats = {n: {"n": 0, "t0": None, "t1": None, "last": None, "first": None, "gap": 0.0} for n in topics}

    def make_cb(name):
        def cb(msg):
            s = stats[name]
            now = time.monotonic()
            s["n"] += 1
            if s["t1"] is not None:
                s["gap"] = max(s["gap"], now - s["t1"])
            s["t0"] = s["t0"] or now
            s["t1"] = now
            s["first"] = s["first"] or msg
            s["last"] = msg
        return cb

    for name, typ in topics.items():
        node.create_subscription(get_message(typ), name, make_cb(name), qos_profile_sensor_data)

    print(f"Found {len(topics)} sensor topics, listening for {args.seconds:.0f} s (keep the robot still)...\n")
    end = time.time() + args.seconds
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)

    problems = 0
    for name in sorted(topics, key=lambda n: list(KNOWN).index(topics[n])):
        typ, s = topics[name], stats[name]
        label, min_hz = KNOWN[typ]
        hz = (s["n"] - 1) / (s["t1"] - s["t0"]) if s["n"] > 1 and s["t1"] > s["t0"] else 0.0
        warns = []
        if s["n"] == 0:
            pubs = node.count_publishers(name)
            warns.append(f"no data received ({pubs} publishers). Could be a QoS or network problem" if pubs
                         else "no publisher")
            summary = ""
        else:
            if typ == "std_msgs/msg/Float32":
                summary, w = check_float_battery(name, s["last"])
            else:
                summary, w = (CHECKS.get(typ) or check_generic)(s["last"])
            warns += w
            if min_hz and hz < min_hz:
                warns.append(f"rate too low: {hz:.1f} Hz (needs at least {min_hz} Hz)")
            if min_hz and s["gap"] > max(0.5, 3.0 / min_hz):
                warns.append(f"{s['gap']:.1f} s gap: if this is over Wi-Fi, run SLAM/Nav2 on Pinky itself")
        problems += bool(warns)
        mark = "OK  " if not warns else "WARN"
        gap = f"  (max gap {s['gap']:.2f} s)" if s["n"] > 1 and min_hz else ""
        rate = f"{hz:5.1f} Hz" if s["n"] > 1 else ("  slow" if s["n"] == 1 else "  0 Hz")
        print(f"[{mark}] {label:<20} {name}  {rate}{gap}")
        if summary:
            print(f"         {summary}")
        for w in warns:
            print(f"         ! {w}")

    for n in skipped:
        print(f"[----] {'Camera':<20} {n}  skipped (--skip-camera); on Pinky: ros2 topic hz {n}")

    # ---------- TF: SLAM에 필요한 것 ----------
    print("\nTF tree:")
    odom_frame, base_frame = "odom", None
    for name, typ in topics.items():
        if typ == "nav_msgs/msg/Odometry" and stats[name]["last"]:
            odom_frame = stats[name]["last"].header.frame_id or "odom"
            base_frame = stats[name]["last"].child_frame_id or None
    candidates = [base_frame] if base_frame else ["base_footprint", "base_link"]
    cam_types = ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage", "sensor_msgs/msg/CameraInfo")
    cam_frames = {stats[n]["last"].header.frame_id for n, t in topics.items()
                  if t in cam_types and stats[n]["last"] is not None}
    sensor_frames = {stats[n]["last"].header.frame_id for n, t in topics.items()
                     if stats[n]["last"] is not None and hasattr(stats[n]["last"], "header")
                     and t not in ("nav_msgs/msg/Odometry", "sensor_msgs/msg/BatteryState", "sensor_msgs/msg/JointState")}
    sensor_frames.discard("")
    base = next((f for f in candidates if tf_buf.can_transform(odom_frame, f, Time())), None)
    if base:
        print(f"[OK  ] {odom_frame} → {base}")
    else:
        problems += 1
        print(f"[WARN] {odom_frame} → {candidates[0]} no transform: odometry publishes no TF, SLAM will not work")
        base = candidates[0]
    for f in sorted(sensor_frames):
        if f == base:
            continue
        if tf_buf.can_transform(base, f, Time()):
            t = tf_buf.lookup_transform(base, f, Time()).transform.translation
            print(f"[OK  ] {base} → {f}  ({t.x:+.3f}, {t.y:+.3f}, {t.z:+.3f}) m")
        elif f in cam_frames:
            # SLAM은 이 카메라 프레임의 TF가 필요 없음 (vslam.launch.py가 자체 TF를 추가); RViz에서만 필요
            print(f"[----] {base} → {f} no transform (not needed for SLAM; "
                  f"add one with static_transform_publisher if needed)")
        else:
            problems += 1
            print(f"[WARN] {base} → {f} no transform: is robot_state_publisher / URDF running?")

    if args.motion:
        problems += motion_test(node, topics, stats, args, rclpy)

    print(f"\n(check ran on {socket.gethostname()})")
    print("\n" + ("All good, SLAM can start." if not problems
                  else f"{problems} problems found. See the lines marked '!'."))
    node.destroy_node()
    rclpy.try_shutdown()


def motion_test(node, topics, stats, args, rclpy) -> int:
    """0.5 rad/s로 3 s 제자리 회전; 오도메트리 yaw, 적분한 자이로, LiDAR가 서로 맞아야 함."""
    from geometry_msgs.msg import Twist, TwistStamped

    odom = next((n for n, t in topics.items() if t == "nav_msgs/msg/Odometry"), None)
    imu = next((n for n, t in topics.items() if t == "sensor_msgs/msg/Imu"), None)
    scan = next((n for n, t in topics.items() if t == "sensor_msgs/msg/LaserScan"), None)
    if not odom:
        print("\nMotion test: no odometry found, skipped")
        return 1

    pub = node.create_publisher(TwistStamped if args.stamped else Twist, args.cmd_vel, 10)

    def send(w):
        if args.stamped:
            m = TwistStamped()
            m.header.stamp = node.get_clock().now().to_msg()
            m.twist.angular.z = w
        else:
            m = Twist()
            m.angular.z = w
        pub.publish(m)

    print("\nMotion test: Pinky turns in place for 3 s (clear the area around it)...")
    yaw0 = yaw_of(stats[odom]["last"].pose.pose.orientation)
    scan0 = np.asarray(stats[scan]["last"].ranges, dtype=np.float32) if scan and stats[scan]["last"] else None
    gyro_yaw, last_t, last_imu = 0.0, time.monotonic(), None
    end = time.monotonic() + 3.0
    try:
        while time.monotonic() < end:
            send(0.5)
            rclpy.spin_once(node, timeout_sec=0.02)
            if imu and stats[imu]["last"] is not last_imu and stats[imu]["last"] is not None:
                now = time.monotonic()
                gyro_yaw += GYRO_SCALE * stats[imu]["last"].angular_velocity.z * (now - last_t)
                last_t, last_imu = now, stats[imu]["last"]
    finally:
        for _ in range(5):
            send(0.0)
            time.sleep(0.02)
    t_stop = time.monotonic() + 1.0
    while time.monotonic() < t_stop:
        rclpy.spin_once(node, timeout_sec=0.05)

    d_odom = math.degrees(math.atan2(math.sin(yaw_of(stats[odom]["last"].pose.pose.orientation) - yaw0),
                                     math.cos(yaw_of(stats[odom]["last"].pose.pose.orientation) - yaw0)))
    problems = 0
    print(f"  odometry: {d_odom:+.0f}° (command ~+86°)")
    if abs(d_odom) < 10:
        problems += 1
        print("  ! odometry barely changed: did the robot turn? Check the /cmd_vel name or --stamped")
    elif d_odom < 0:
        problems += 1
        print("  ! odometry turned the wrong way: left/right wheel or sign is wrong")
    if imu:
        d_gyro = math.degrees(gyro_yaw)
        print(f"  IMU gyro: {d_gyro:+.0f}°")
        if abs(d_odom) > 10 and (d_gyro * d_odom < 0 or abs(d_gyro - d_odom) > 0.3 * abs(d_odom)):
            problems += 1
            if 50 < abs(d_gyro / d_odom) < 65:
                print("  ! IMU gyro is ~57x too large: it is in deg/s, not rad/s. "
                      "Add --gyro-deg to this script; for ROS use robot/imu_fix.py -> /imu/data")
            else:
                print("  ! IMU and odometry disagree: IMU axis/sign or wheel radius/separation is wrong")
    if scan0 is not None and stats[scan]["last"] is not None:
        r1 = np.asarray(stats[scan]["last"].ranges, dtype=np.float32)
        both = np.isfinite(scan0) & np.isfinite(r1)
        if r1.size == scan0.size and both.any():
            diff = float(np.abs(scan0[both] - r1[both]).mean())
            print(f"  LiDAR change: mean {diff:.2f} m")
            if diff < 0.02:
                problems += 1
                print("  ! LiDAR scan did not change: is the scan updating?")
    if not problems:
        print("  OK: odometry, IMU and LiDAR agree")
    return problems


if __name__ == "__main__":
    main()
