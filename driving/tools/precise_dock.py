# 카메라(ArUco) 정밀 주차: 가르쳐 둔 기준 자세(aruco_ref.json)와 같아질 때까지 조금씩 움직인다. **로봇에서 실행** (picamera2).
# - 방향: AMCL(TF map->base_footprint, 멈춘 채 nomotion update) 를 기준 방향(heading_map_deg)에 맞춘다.
#   카메라 PnP 각도는 1.7cm 마커·10cm 거리에서 같은 자리 ±7° 로 튀어서 쓰지 않는다 (2026-10-22 확인).
# - 앞뒤·좌우: 방향이 같으면 '마커가 로봇 기준 어디 보이나'의 차이 = 로봇이 움직여야 할 양. 카메라 tvec 으로 잰다.
# - 움직임은 /odom 으로 닫힌 제어 (제자리 회전, 직진). 좌우가 크면 뒤로 물러났다 비스듬히 다시 들어간다.
#   python3 precise_dock.py --teach          # 지금 자세를 기준으로 (카메라 + AMCL 방향) 저장
#   python3 precise_dock.py --check          # 기준과 차이만 출력
#   python3 precise_dock.py                  # 정밀 주차 (로봇이 움직임!)
#   python3 precise_dock.py --move -0.04,0.02,5   # 시험용: 뒤 4cm, 왼 2cm 만큼 옮기고 5° 돌려 둔다 (odom)
import argparse
import json
import math
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aruco_ref as AR  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, 'aruco_ref.json')
TOL_XY = 0.010              # m, 끝으로 보는 앞뒤·좌우 (10-22 사용자: 4mm → 1cm 로 여유. OMX 팀 원래 허용 ±5mm)
TOL_TH = math.radians(3.0)  # 끝으로 보는 방향 (10-22 사용자: 1° → 3°. 원래 허용 ±2°)
LAT_STRAIGHT = 0.005        # m, 좌우가 이보다 작으면 BACKOFF 우회 없이 곧게만 (예전 2mm, 허용 1cm 에 맞춰)
BACKOFF = 0.05              # m, 좌우 보정할 때 목표 앞에서 이만큼 뒤 지점을 거쳐 곧게 들어간다
MAX_ITERS = 6
CAM_X = 0.035               # m, 카메라가 바퀴 축보다 앞 (TF base_footprint -> front_camera_link)
ROT_GAIN = 1.1              # odom 회전이 실제보다 8~15% 적게 잼 → 방향 보정 때 지시각 / ROT_GAIN
TH_DEADBAND = math.radians(1.5)  # 이보다 작은 방향 차이는 안 고침 (AMCL 잡음 ±0.3~0.5°, 허용 3° 안에 넉넉히. 예전 0.8°)
FRONT_MIN = 0.015           # m, 앞으로 갈 때 몸체 앞 이만큼은 비어 있어야


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class Camera:
    def __init__(self):
        from picamera2 import Picamera2
        self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, AR.DICT)),
                                           cv2.aruco.DetectorParameters())
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_video_configuration(main={"size": (AR.W, AR.H), "format": "RGB888"}))
        self.cam.start(); time.sleep(1.0)

    def measure(self, n=7):
        """마커 위치 (로봇 기준 앞 fwd, 왼 left, m) 중앙값. 못 찾으면 None"""
        F, L, C = [], [], []
        for _ in range(n * 2):
            img = self.cam.capture_array()
            c, ids, _ = self.det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
            if ids is None or AR.MARKER_ID not in ids.ravel():
                continue
            cc = c[list(ids.ravel()).index(AR.MARKER_ID)][0]
            _, t = AR.solve(cc)
            p = AR.robot_pose(np.zeros(3), t)
            F.append(p['z']); L.append(p['x_left']); C.append(cc.mean(0))
            if len(F) >= n:
                break
        if len(F) < max(3, n // 2):
            return None
        return dict(fwd=float(np.median(F)), left=float(np.median(L)), n=len(F),
                    spread_mm=1000 * float(max(np.ptp(F), np.ptp(L))), center_px=np.median(C, 0).tolist())

    def close(self):
        self.cam.stop(); self.cam.close()


class Base:
    def __init__(self):
        import rclpy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
        from std_srvs.srv import Empty
        from tf2_ros import Buffer, TransformListener
        rclpy.init()
        self.rclpy = rclpy
        self.n = rclpy.create_node('precise_dock')
        self.Twist = Twist
        self.pub = self.n.create_publisher(Twist, 'cmd_vel_nav', 10)
        self.odom = None
        self.n.create_subscription(Odometry, '/odom', self._odom, qos_profile_sensor_data)
        self.scan = None
        self.n.create_subscription(LaserScan, '/scan', lambda m: setattr(self, 'scan', m), qos_profile_sensor_data)
        self.nomo = self.n.create_client(Empty, '/request_nomotion_update'); self.Empty = Empty
        self.tfb = Buffer(); TransformListener(self.tfb, self.n)
        t0 = time.time()
        while (self.odom is None or self.scan is None) and time.time() - t0 < 5:
            self.spin(0.1)
        if self.odom is None:
            raise RuntimeError('/odom 안 들어옴')

    def _odom(self, m):
        p = m.pose.pose
        self.odom = (p.position.x, p.position.y, yaw_of(p.orientation))

    def spin(self, sec):
        t = time.time()
        while time.time() - t < sec:
            self.rclpy.spin_once(self.n, timeout_sec=0.01)

    def send(self, v, w):
        t = self.Twist(); t.linear.x = float(v); t.angular.z = float(w); self.pub.publish(t)

    def stop(self):
        for _ in range(5):
            self.send(0, 0); self.spin(0.03)
        self.spin(0.3)

    def amcl_heading(self):
        """멈춘 채 AMCL 을 몇 번 갱신시킨 뒤 map 방향 (rad)"""
        if self.nomo.wait_for_service(timeout_sec=2.0):
            for _ in range(8):
                self.nomo.call_async(self.Empty.Request()); self.spin(0.25)
        t0 = time.time()
        while not self.tfb.can_transform('map', 'base_footprint', self.rclpy.time.Time()) and time.time() - t0 < 5:
            self.spin(0.1)
        tr = self.tfb.lookup_transform('map', 'base_footprint', self.rclpy.time.Time()).transform
        return yaw_of(tr.rotation), tr.translation.x, tr.translation.y

    def front_gap(self):
        """몸체(라이다 중심 원 r7cm) 앞쪽 빈 거리 m"""
        s = self.scan
        if s is None:
            return 9.0
        R = np.asarray(s.ranges, float); a = s.angle_min + np.arange(len(R)) * s.angle_increment + math.pi  # 라이다 180° 장착
        ok = np.isfinite(R) & (R > 0.068) & (R < 1.0)
        x, y = R[ok] * np.cos(a[ok]), R[ok] * np.sin(a[ok])
        m = (x > 0) & (np.abs(y) < 0.07)
        return float((np.hypot(x[m], y[m]) - 0.07).min()) if m.any() else 9.0

    def rotate_by(self, ang, tol=math.radians(0.3), timeout=15):
        self.spin(0.1); th0 = self.odom[2]; t0 = time.time()
        while time.time() - t0 < timeout:
            self.spin(0.02)
            err = wrap(th0 + ang - self.odom[2])
            if abs(err) < tol:
                break
            w = max(0.12, min(0.5, 1.5 * abs(err)))
            self.send(0, math.copysign(w, err))
        self.stop()
        return wrap(self.odom[2] - th0)

    def drive_by(self, dist, tol=0.001, timeout=20):
        """odom 직선 거리로 dist(m, 음수면 후진). 방향은 시작 방향 유지"""
        self.spin(0.1); x0, y0, th0 = self.odom; t0 = time.time()
        while time.time() - t0 < timeout:
            self.spin(0.02)
            x, y, th = self.odom
            s = (x - x0) * math.cos(th0) + (y - y0) * math.sin(th0)
            err = dist - s
            if abs(err) < tol:
                break
            if err > 0 and self.front_gap() < FRONT_MIN:
                print('  앞이 막혀 멈춤'); break
            v = max(0.015, min(0.05, 1.2 * abs(err)))
            self.send(math.copysign(v, err), 2.0 * wrap(th0 - th))
        self.stop()
        x, y, _ = self.odom
        return (x - x0) * math.cos(th0) + (y - y0) * math.sin(th0)

    def go_relative(self, mx, my, dth=0.0):
        """로봇 기준 (mx 앞, my 왼) 으로 옮기고, 원래 방향 + dth 로. 좌우가 있으면 BACKOFF 뒤 지점을 거쳐 곧게 들어간다"""
        if abs(my) < LAT_STRAIGHT:
            self.drive_by(mx)
        else:
            qx = mx - BACKOFF  # 거쳐 갈 점 (목표에서 BACKOFF 뒤)
            d = math.hypot(qx, my)
            b = math.atan2(my, qx)
            if abs(b) > math.pi / 2:  # 뒤쪽이면 후진으로
                b = wrap(b + math.pi); d = -d
            r1 = self.rotate_by(b)
            self.drive_by(d)
            self.rotate_by(-r1)
            self.drive_by(BACKOFF)
        if abs(dth) > math.radians(0.2):
            self.rotate_by(dth)

    def close(self):
        self.stop(); self.n.destroy_node(); self.rclpy.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--teach', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--move', help='시험용 이동 "앞m,왼m,deg"')
    ap.add_argument('--ref', default='dock', help='aruco_ref.json 안 기준 이름 (기본 dock = OMX, dock_surgery_test = 수술실 시험 마커)')
    a = ap.parse_args()
    base = Base()
    try:
        if a.move:
            mx, my, dd = map(float, a.move.split(','))
            base.go_relative(mx, my, math.radians(dd))
            print('옮김', a.move); return 0
        cam = Camera()
        try:
            th, x, y = base.amcl_heading()
            m = cam.measure(9)
            if a.teach:
                if m is None:
                    print('마커 못 찾음'); return 1
                ref = json.load(open(REF)) if os.path.exists(REF) else {}
                ref[a.ref] = (dict(fwd=m['fwd'], left=m['left'], center_px=m['center_px'], heading_map_deg=math.degrees(th),
                                     amcl_axle_cm=[100 * x, 100 * y], time=time.strftime('%Y-%m-%d %H:%M:%S')))
                json.dump(ref, open(REF, 'w'), indent=1, ensure_ascii=False)
                print(f'기준 저장: 마커 앞 {100 * m["fwd"]:.2f}cm 왼 {100 * m["left"]:+.2f}cm (흔들림 {m["spread_mm"]:.1f}mm), AMCL 방향 {math.degrees(th):.2f}°')
                return 0
            ref = json.load(open(REF))[a.ref]
            print(f'기준: {a.ref}')
            th_ref = math.radians(ref['heading_map_deg'])

            def pos_err(m, th):
                """기준 자세 좌표계에서 로봇 바퀴 축이 어긋난 양 (앞 +, 왼 +, m). 방향 차이 d 는 바퀴 축 중심 회전으로 되돌려 뺀다:
                p = m_ref - R(d) m   (m = 바퀴 축 기준 마커 위치). 앞 + = 마커에서 멀다(뒤로 처짐)가 아니라 '앞으로 가야 할 양'의 반대"""
                d = wrap(th - th_ref)
                ax, ay = m['fwd'] + CAM_X, m['left']
                rx, ry = ref['fwd'] + CAM_X, ref['left']
                return -(rx - (math.cos(d) * ax - math.sin(d) * ay)), -(ry - (math.sin(d) * ax + math.cos(d) * ay))

            def report(tag, m, th):
                if m is None:
                    print(f'{tag}: 마커 못 찾음, 방향 오차 {math.degrees(wrap(th - th_ref)):+.2f}°'); return None
                px, py = pos_err(m, th)
                e = dict(fwd_mm=1000 * px, left_mm=1000 * py, th_deg=math.degrees(wrap(th - th_ref)))
                print(f'{tag}: 앞뒤 {e["fwd_mm"]:+.1f}mm, 좌우 {e["left_mm"]:+.1f}mm, 방향 {e["th_deg"]:+.2f}°  (마커 {m["n"]}장, 흔들림 {m["spread_mm"]:.1f}mm)')
                return e
            e = report('시작', m, th)
            if a.check:
                return 0
            log = dict(start=e, steps=[])
            t0 = time.time(); ok = False
            for it in range(1, MAX_ITERS + 1):
                dth = wrap(th_ref - th)
                if abs(dth) > TH_DEADBAND:
                    base.rotate_by(dth / ROT_GAIN)
                    th, _, _ = base.amcl_heading(); m = cam.measure()
                if m is None:
                    print('마커가 안 보여 중단'); break
                ex, ey = pos_err(m, th); d = wrap(th - th_ref)
                done = abs(ex) < TOL_XY and abs(ey) < TOL_XY and abs(d) < TOL_TH
                e = report(f'({it}) 측정', m, th); log['steps'].append(e)
                if done:
                    ok = True; break
                # 가야 할 양 = 기준 좌표계에서 (ex, ey) [표시 부호: 앞뒤 + = 마커가 기준보다 멀다 = 앞으로 가야 함]
                # → 지금 로봇 좌표계로 방향 차이 d 만큼 돌려서
                mx = math.cos(-d) * ex - math.sin(-d) * ey; my = math.sin(-d) * ex + math.cos(-d) * ey
                print(f'  이동: 앞 {1000 * mx:+.1f}mm, 왼 {1000 * my:+.1f}mm')
                base.go_relative(mx, my)
                th, _, _ = base.amcl_heading(); m = cam.measure()
            final = report('최종', m, th)
            log.update(final=final, ok=ok, iters=it, time_s=round(time.time() - t0, 1))
            os.makedirs(os.path.join(HERE, 'dock_logs'), exist_ok=True)
            json.dump(log, open(os.path.join(HERE, 'dock_logs', f'dock_{time.strftime("%m%d_%H%M%S")}.json'), 'w'), indent=1)
            print(f'{"성공" if ok else "실패"} — {it}회, {log["time_s"]}s')
            return 0 if ok else 1
        finally:
            cam.close()
    finally:
        base.close()


if __name__ == '__main__':
    sys.exit(main())
