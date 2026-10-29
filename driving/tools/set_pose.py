# AMCL 시작 위치 넣기: 퍼짐(공분산) 있는 /initialpose 를 보내고, 스캔이 맵 벽에 맞는지 확인한다. 로봇은 움직이지 않는다.
# 설정 파일의 initial_pose 는 퍼짐 0 이라 입자가 한 점에 몰려 스캔으로 다듬지 못한다 → Nav2 띄운 직후 이걸로 한 번 넣는다.
# 좌표는 그림 cm, **라이다 중심**, 방향 deg (0 = +x, 90 = +y).
#   python3 set_pose.py A                  # points.yaml 의 이름: markers(A,B,C,D,F,G), start_A, omx_stop, omx_approach
#   python3 set_pose.py 182.7,24 180       # 직접 (라이다 중심)
#   python3 set_pose.py 181,24 180 --axle  # 바퀴 축 좌표로 줄 때
#   python3 set_pose.py --find             # 손으로 옮겼을 때: 스캔만으로 맵 전체에서 찾아서 넣기 (~1분)
#   옵션: --spread 2,2 (cm, deg)   --no-check
import argparse
import math
import os
import sys
import time

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LIDAR_BEHIND_AXLE = 0.017  # m (URDF rplidar_mount x = -0.017)
OK_MATCH, OK_DIST, OK_DEG = 0.80, 0.02, 2.0   # 확인 기준: 벽 3cm 안 점 비율, 최적 자세와 차이


def named(name):
    P = yaml.safe_load(open(os.path.join(HERE, 'points.yaml')))
    for k, v in P.get('markers', {}).items():
        if k.lower() == name.lower():
            return float(v[0]), float(v[1]), float(v[2])
    for k, v in P.items():
        if k.lower() == name.lower() and isinstance(v, dict) and 'xy' in v and 'heading' in v:
            return float(v['xy'][0]), float(v['xy'][1]), float(v['heading'])
    names = list(P.get('markers', {})) + [k for k, v in P.items() if isinstance(v, dict) and 'heading' in v]
    sys.exit(f'points.yaml 에 "{name}" 없음. 있는 이름: {", ".join(names)}')


class Node:
    def __init__(self):
        import rclpy
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
        from std_srvs.srv import Empty
        from tf2_ros import Buffer, TransformListener
        rclpy.init()
        self.rclpy, self.Msg, self.Empty = rclpy, PoseWithCovarianceStamped, Empty
        self.n = rclpy.create_node('set_pose')
        self.pub = self.n.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
        self.amcl = []
        self.n.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', lambda m: self.amcl.append(m), 10)
        self.scans = []
        self.n.create_subscription(LaserScan, '/scan', lambda m: self.scans.append(m), qos_profile_sensor_data)
        self.nomo = self.n.create_client(Empty, '/request_nomotion_update')
        self.tfb = Buffer(); TransformListener(self.tfb, self.n)

    def spin(self, sec):
        t = time.time()
        while time.time() - t < sec:
            self.rclpy.spin_once(self.n, timeout_sec=0.02)

    def scan_points(self, n=20):
        """스캔 n 장 → 라이다 중심 기준 점 (global_find.lidar_points)"""
        import global_find as gf
        self.scans.clear(); t = time.time()
        while len(self.scans) < n and time.time() - t < 10:
            self.spin(0.1)
        if not self.scans:
            sys.exit('/scan 안 들어옴')
        s = self.scans[0]
        tr = None; t = time.time()
        while tr is None and time.time() - t < 5:
            try:
                tr = self.tfb.lookup_transform('base_footprint', s.header.frame_id, self.rclpy.time.Time()).transform
            except Exception:  # noqa: BLE001
                self.spin(0.1)
        if tr is None:
            sys.exit('라이다 TF 없음')
        q = tr.rotation; lyaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        R = np.array([m.ranges for m in self.scans[:n]], float)
        return gf.lidar_points(R, (s.angle_min, s.angle_max, s.angle_increment), (s.range_min, s.range_max),
                               (tr.translation.x, tr.translation.y, lyaw))

    def publish(self, ax, ay, th, sxy, sth):
        t = time.time()
        while self.pub.get_subscription_count() == 0 and time.time() - t < 5:
            self.spin(0.1)
        if self.pub.get_subscription_count() == 0:
            sys.exit('/initialpose 를 받는 노드(amcl)가 없음 — Nav2(nav2_followpath) 가 떠 있는지 확인')
        m = self.Msg(); m.header.frame_id = 'map'   # stamp 0 = 최신 TF 로 처리
        m.pose.pose.position.x, m.pose.pose.position.y = ax, ay
        m.pose.pose.orientation.z, m.pose.pose.orientation.w = math.sin(th / 2), math.cos(th / 2)
        cov = [0.0] * 36; cov[0] = cov[7] = sxy ** 2; cov[35] = sth ** 2
        m.pose.covariance = cov
        self.pub.publish(m); self.spin(0.5)

    def settle(self, k=15):
        """멈춘 채 AMCL 갱신을 k 번 요청하고 마지막 /amcl_pose 반환"""
        self.amcl.clear()
        if self.nomo.wait_for_service(timeout_sec=3.0):
            for _ in range(k):
                self.nomo.call_async(self.Empty.Request()); self.spin(0.3)
        self.spin(0.5)
        return self.amcl[-1] if self.amcl else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('where', nargs='*', help='이름(A, start_A, omx_stop…) 또는 "x,y heading" (그림 cm, deg)')
    ap.add_argument('--axle', action='store_true', help='좌표가 바퀴 축 기준')
    ap.add_argument('--find', action='store_true', help='스캔만으로 맵 전체에서 찾기')
    ap.add_argument('--spread', default='2,2', help='퍼짐 cm,deg (기본 2,2)')
    ap.add_argument('--no-check', action='store_true')
    a = ap.parse_args()
    sxy, sth = (float(v) for v in a.spread.split(','))
    sxy, sth = sxy / 100, math.radians(sth)

    if not a.find:
        if len(a.where) == 1 and ',' not in a.where[0]:
            x, y, h = named(a.where[0])
        elif len(a.where) == 2:
            (x, y), h = map(float, a.where[0].split(',')), float(a.where[1])
        else:
            ap.error('이름 하나, "x,y heading", 또는 --find')
    node = Node()
    if a.find:
        import global_find as gf
        print('스캔만으로 맵 전체에서 찾는 중… (~1분)')
        cands = gf.search(node.scan_points())
        for i, (sc, x, y, th) in enumerate(cands[:3]):
            print(f'  {"★" if i == 0 else " "} 라이다 중심 ({100 * x:.1f}, {100 * y:.1f}) cm, {math.degrees(th) % 360:.1f}°  벽 3cm 안 {100 * sc:.1f}%')
        sc, lx, ly, th = cands[0]
        if sc < OK_MATCH or (len(cands) > 1 and cands[1][0] > sc - 0.10):
            print(f'⚠️ 확실하지 않음 (1등 {100 * sc:.0f}%, 2등 {100 * cands[1][0]:.0f}%) — 그래도 1등으로 넣음. 결과를 꼭 확인할 것')
    else:
        th = math.radians(h)
        if a.axle:
            x, y = x - 100 * LIDAR_BEHIND_AXLE * math.cos(th), y - 100 * LIDAR_BEHIND_AXLE * math.sin(th)
        lx, ly = x / 100, y / 100
    ax, ay = lx + LIDAR_BEHIND_AXLE * math.cos(th), ly + LIDAR_BEHIND_AXLE * math.sin(th)   # 라이다 중심 -> 바퀴 축
    print(f'넣는 위치: 라이다 중심 ({100 * lx:.1f}, {100 * ly:.1f}) cm, {math.degrees(th) % 360:.1f}°  '
          f'(바퀴 축 ({100 * ax:.1f}, {100 * ay:.1f})), 퍼짐 {100 * sxy:.1f}cm·{math.degrees(sth):.1f}°')
    node.publish(ax, ay, th, sxy, sth)
    if a.no_check:
        return 0

    m = node.settle()
    if m is None:
        print('⚠️ /amcl_pose 가 안 나옴 — AMCL 상태 확인'); return 1
    p = m.pose.pose; q = p.orientation
    ath = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    alx, aly = p.position.x - LIDAR_BEHIND_AXLE * math.cos(ath), p.position.y - LIDAR_BEHIND_AXLE * math.sin(ath)
    sx, sy = math.sqrt(m.pose.covariance[0]), math.sqrt(m.pose.covariance[7])
    print(f'AMCL: 라이다 중심 ({100 * alx:.1f}, {100 * aly:.1f}) cm, {math.degrees(ath) % 360:.1f}°, σ {100 * sx:.1f}/{100 * sy:.1f} cm')

    import global_find as gf
    L = node.scan_points()
    sc0 = gf.score(L, alx, aly, ath)
    bx, by, bth, _ = gf.fit(L, alx, aly, ath)
    dd, dth = math.hypot(bx - alx, by - aly), math.degrees((bth - ath + math.pi) % (2 * math.pi) - math.pi)
    print(f'스캔 확인: AMCL 자세에서 벽 3cm 안 {100 * sc0:.0f}%, 가장 잘 맞는 자세와 차이 {100 * dd:.1f}cm·{dth:+.1f}°')
    good = sc0 >= OK_MATCH and dd <= OK_DIST and abs(dth) <= OK_DEG
    print('✅ 위치 맞음' if good else '⚠️ 위치가 의심스러움 — 로봇이 그 자리에 있는지 확인하거나 --find 로 다시 넣기')
    node.n.destroy_node(); node.rclpy.shutdown()
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
