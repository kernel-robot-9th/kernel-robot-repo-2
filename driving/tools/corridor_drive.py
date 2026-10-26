# 협로 벽 따라가기: 한쪽 벽을 라이다로 직접 재서 (벽까지 거리·벽과 이루는 각) 축선 위를 곧게 달린다.
# - 옆 방향/방향 제어: 벽이 보이면 벽 직선 맞춤(RANSAC), 안 보이면(입구·출구) AMCL(TF map->base_footprint) 축선 오차
# - 진행 거리: AMCL 위치를 축선에 내린 값. 끝 근처에서 감속, 끝나면 마지막 방향으로 제자리 회전
# - --stop-on-tape: p1 = 차선 위 점. 나오면서 IR 센서 줄이 테이프를 가로로 밟으면 센서-축 거리만큼 더 가서 멈춤
#   (바퀴 축 = 테이프 위 -> 제자리 회전 뒤 IR 가 바로 테이프를 봄). AMCL 은 '이 근처' 확인용 (예상 ±TAPE_WIN).
#   IR 노드(pinky_sensor_adc)가 떠 있어야 함. 2026-10-26: AMCL 로만 서면 차선에서 2cm 어긋나 IR 바깥 센서만 테이프를 봤음
# - 안전: 몸체 앞 FRONT_GAP 안 장애물 -> 정지·대기, 몸체 옆 SIDE_GAP 안 -> 정지·중단
# 좌표는 그림 cm, 위치는 **라이다 중심** 기준 (run_route.py 와 같음). 속도는 /cmd_vel_nav (velocity_smoother 입력) 로 낸다.
#   python3 corridor_drive.py --check 130,15 130,145 --side right --offset 10      # 움직이지 않고 벽 맞춤만 계속 출력
#   python3 corridor_drive.py 130,15 130,145 --side right --offset 10 --final-heading 180   # 실제 주행 (로봇이 움직임!)
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from follow_path_client import LIDAR_BEHIND_AXLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BODY_R = 0.07       # m, 몸체 반경 (중심 = 라이다)
FRONT_GAP = 0.04    # m, 몸체 앞 이 거리 안에 점 -> 정지·대기
SIDE_GAP = 0.01     # m, 몸체 둘레 이 거리 안에 점 -> 정지·중단
REAR_X = -0.03      # m, 라이다 중심 기준 이보다 뒤의 점은 접촉 검사에서 뺌 (앞으로 갈 때 닿을 수 없음.
                    #    2026-10-26 B1 에서 협로 쪽으로 제자리 회전하면 뒤가 바닥 패널에 닿은 채 출발 -> contact 로 멈췄음)
WIN_X = 0.30        # m, 벽 맞춤에 쓰는 앞뒤 범위 (base_footprint 기준)
MAX_WALL_ANG = math.radians(25)
SELF_R = 0.068       # m, 라이다에서 이 거리 안 점 = 로봇 자기 부품 (2026-10-22 새 핑키: 오른쪽 앞 -20~-45°, 3.4~5.7cm)
SENSOR_AHEAD = 0.03  # m, IR 센서 줄이 바퀴 축 앞 (line_follow 회전 시험 추정)
TAPE_WIN = 0.04      # m, 테이프를 찾는 AMCL 범위 (예상 위치 앞뒤)
TAPE_SEEN = 1.5      # 흰 정도 합 (세 센서가 테이프를 가로로 밟음)
MIN_INLIERS = 40     # 협로 안에서는 250개 안팎
MAX_RES = 0.004      # m, 직선 잔차 (협로 안 2~3mm)


def fit_wall(P, side, d_ref, rng=None):
    """P: base_footprint 기준 점 (N,2), x 앞 y 왼쪽. side 쪽 벽 직선 y = a x + b 맞춤.
    반환: dict(d=벽까지 수직거리, alpha=벽 방향(로봇 기준, 왼쪽 +), n=inlier 수, span=앞뒤 길이) 또는 None"""
    s = -1.0 if side == 'right' else 1.0
    m = (np.abs(P[:, 0]) < WIN_X) & (s * P[:, 1] > 0.02) & (s * P[:, 1] < d_ref + 0.08)
    Q = P[m]
    if len(Q) < 12:
        return None
    rng = rng or np.random.default_rng(0)
    best = None
    for _ in range(80):
        i, j = rng.choice(len(Q), 2, replace=False)
        dx, dy = Q[j] - Q[i]
        if abs(dx) < 0.05 or abs(math.atan2(dy, dx) if dx > 0 else math.atan2(-dy, -dx)) > MAX_WALL_ANG:
            continue
        a = dy / dx; b = Q[i, 1] - a * Q[i, 0]
        r = np.abs(Q[:, 1] - (a * Q[:, 0] + b)) / math.sqrt(1 + a * a)
        inl = r < 0.01
        if best is None or inl.sum() > best.sum():
            best = inl
    if best is None or best.sum() < 12:
        return None
    X, Y = Q[best, 0], Q[best, 1]
    a, b = np.polyfit(X, Y, 1)
    span = X.max() - X.min()
    if span < 0.12 or abs(math.atan(a)) > MAX_WALL_ANG:
        return None
    res = float(np.std(Y - (a * X + b)))
    if best.sum() < MIN_INLIERS or res > MAX_RES:  # 점이 적거나 잔차가 크면 (입구·모서리에서 엉뚱한 직선) 버림
        return None
    return dict(d=abs(b) / math.sqrt(1 + a * a), alpha=math.atan(a), n=int(best.sum()), span=float(span), res=res)


def scan_to_base(ranges, a0, inc, rmin, laser_tf):
    lx, ly, lyaw = laser_tf
    R = np.asarray(ranges, float)
    ang = a0 + np.arange(len(R)) * inc + lyaw
    ok = np.isfinite(R) & (R > max(rmin, SELF_R)) & (R < 1.0)
    return np.c_[lx + R[ok] * np.cos(ang[ok]), ly + R[ok] * np.sin(ang[ok])]


def control(e_left, th_rel, k_lat=8.0, k_h=2.0, max_corr=math.radians(20), w_max=0.6):
    """e_left: 축선(원하는 선)보다 왼쪽으로 벗어난 거리 m, th_rel: 축 방향 대비 로봇 방향 rad (왼쪽 +)."""
    th_des = -max(-max_corr, min(max_corr, math.atan(k_lat * e_left)))
    return max(-w_max, min(w_max, k_h * (th_des - th_rel)))


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class CorridorDrive:
    def __init__(self, node, side='right', offset_cm=10.0, speed=0.08, cmd_topic='cmd_vel_nav', tf_buffer=None, body_r=BODY_R):
        """tf_buffer: 늘 돌고 있는 다른 노드의 TF 버퍼를 같이 씀 (API 서버). 없으면 이 노드에 TF 리스너를 만든다 —
        이 노드는 run() 동안만 spin 되므로, 오래 쉬었다 다시 쓰면 옛 TF 와 새 TF 가 섞여 조회가 깨진다 (10-22 API 실패)"""
        from geometry_msgs.msg import Twist
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
        from tf2_ros import Buffer, TransformListener
        self.node, self.side, self.d_ref, self.v = node, side, offset_cm / 100, speed
        self.body_r = body_r   # 접촉·앞 검사용 몸체 반경 (기본 그릇 Ø14, 빈 로봇이면 0.055)
        self.Twist = Twist
        self.pub = node.create_publisher(Twist, cmd_topic, 10)
        self.scan = None
        node.create_subscription(LaserScan, '/scan', self._on_scan, qos_profile_sensor_data)
        if tf_buffer is None:
            self.tfb = Buffer(); TransformListener(self.tfb, node)
        else:
            self.tfb = tf_buffer
        self.laser_tf = None
        self.ir = None

    def _enable_ir(self):
        if getattr(self, '_ir_sub', None) is None:
            from rclpy.qos import qos_profile_sensor_data
            from std_msgs.msg import UInt16MultiArray
            from line_follow import IrFilter
            irf = IrFilter()
            def on_ir(m):
                if len(m.data) >= 3:
                    self.ir = (irf(m.data), time.time())
            self._ir_sub = self.node.create_subscription(UInt16MultiArray, '/ir_sensor/range', on_ir, qos_profile_sensor_data)

    def _on_scan(self, m):
        self.scan = m

    def _spin(self, sec):
        import rclpy
        t = time.time()
        while time.time() - t < sec:
            rclpy.spin_once(self.node, timeout_sec=0.01)

    def _yaw(self, q):
        return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

    def wait_ready(self, timeout=5.0):
        import rclpy
        self.scan = None   # 지난번 run() 때 받은 낡은 스캔 말고 새 스캔을 기다림
        t = time.time()
        while time.time() - t < timeout:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if self.scan is None:
                continue
            try:
                tr = self.tfb.lookup_transform('base_footprint', self.scan.header.frame_id, rclpy.time.Time()).transform
                self.laser_tf = (tr.translation.x, tr.translation.y, self._yaw(tr.rotation))
                self.tfb.lookup_transform('map', 'base_footprint', rclpy.time.Time())
                return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def map_pose(self, timeout=1.0):
        """라이다 중심 (x, y) m 와 yaw (map). TF 조회가 잠깐 실패하면 timeout 초까지 다시 시도"""
        import rclpy
        from tf2_ros import TransformException
        t0 = time.time()
        while True:
            try:
                tr = self.tfb.lookup_transform('map', 'base_footprint', rclpy.time.Time()).transform
                break
            except TransformException:
                if time.time() - t0 > timeout:
                    raise
                self._spin(0.05)
        th = self._yaw(tr.rotation)
        return tr.translation.x - LIDAR_BEHIND_AXLE * math.cos(th), tr.translation.y - LIDAR_BEHIND_AXLE * math.sin(th), th

    def points(self):
        s = self.scan
        return scan_to_base(s.ranges, s.angle_min, s.angle_increment, s.range_min, self.laser_tf)

    def measure(self, p0, p1):
        """지금 상태: 축선 기준 오차(지도), 벽 맞춤, 진행 거리"""
        x, y, th = self.map_pose()
        ux, uy = p1[0] - p0[0], p1[1] - p0[1]; L = math.hypot(ux, uy); ux, uy = ux / L, uy / L
        s = (x - p0[0]) * ux + (y - p0[1]) * uy
        e_map = -(x - p0[0]) * uy + (y - p0[1]) * ux          # 축선 왼쪽 +
        th_map = wrap(th - math.atan2(uy, ux))
        P = self.points()
        w = fit_wall(P, self.side, self.d_ref)
        if w is not None and abs(w['d'] - self.d_ref) > 0.05:
            w = None  # 기대 거리에서 5cm 넘게 벗어난 직선은 다른 물체로 본다
        if w is not None:
            e_wall = (w['d'] - self.d_ref) if self.side == 'right' else (self.d_ref - w['d'])
            th_wall = -w['alpha']
        else:
            e_wall = th_wall = None
        # 몸체(라이다 중심 원) 주변 최소 거리, 앞쪽 최소 거리
        C = P - np.array([-LIDAR_BEHIND_AXLE, 0.0])
        r = np.hypot(C[:, 0], C[:, 1]) - self.body_r
        front = r[(C[:, 0] > 0) & (np.abs(C[:, 1]) < self.body_r)]
        side = r[C[:, 0] > REAR_X]
        return dict(s=s, L=L, e_map=e_map, th_map=th_map, wall=w, e_wall=e_wall, th_wall=th_wall,
                    min_gap=float(side.min()) if len(side) else 9.0, front_gap=float(front.min()) if len(front) else 9.0,
                    x=x, y=y, th=th)

    def send(self, v, w):
        t = self.Twist(); t.linear.x = float(v); t.angular.z = float(w); self.pub.publish(t)

    def stop(self):
        for _ in range(5):
            self.send(0, 0); self._spin(0.02)

    def rotate_to(self, yaw_target, tol=math.radians(2), timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self._spin(0.05)
            err = wrap(yaw_target - self.map_pose()[2])
            if abs(err) < tol:
                self.stop(); return True
            self.send(0, max(-0.6, min(0.6, 1.5 * err)) if abs(err) > math.radians(8) else math.copysign(0.15, err))
        self.stop(); return False

    def run(self, p0_cm, p1_cm, final_heading=None, log_path=None, should_stop=None, stop_on_tape=False):
        """p0 -> p1 축선을 따라 벽 따라가기. 반환 dict(status=ok|blocked|contact|timeout|lost|canceled|no_tape|ir_stale, ...)
        should_stop: 매 주기 부르는 함수, True 면 멈추고 canceled (API 서버의 취소)
        stop_on_tape: p1 = 차선 위 점. IR 가 테이프를 밟으면 바퀴 축이 테이프 위에 올 때까지 가서 멈춤"""
        p0 = (p0_cm[0] / 100, p0_cm[1] / 100); p1 = (p1_cm[0] / 100, p1_cm[1] / 100)
        if stop_on_tape:
            from line_follow import tape_pos
            self._enable_ir(); self.ir = None
        if not self.wait_ready():
            return dict(status='lost', why='scan/TF 없음')
        if stop_on_tape:
            t_ir = time.time() + 3
            while self.ir is None and time.time() < t_ir:
                self._spin(0.05)
            if self.ir is None:
                return dict(status='ir_stale', why='/ir_sensor/range 없음 (IR 노드?)')
        tape_s = None      # IR 가 테이프를 밟은 순간의 진행 거리 (라이다 기준)
        axis = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        m = self.measure(p0, p1)
        if abs(m['th_map']) > math.radians(10):
            self.rotate_to(axis)
        rows, t0, blocked_since, status = [], time.time(), None, 'timeout'
        L = m['L']
        if stop_on_tape:   # 테이프(p1)를 IR 가 밟는 라이다 진행 거리 = L - (라이다->축 + 축->센서)
            s_ir = L - LIDAR_BEHIND_AXLE - SENSOR_AHEAD
        elif final_heading is not None:  # 끝 제자리 회전(바퀴 축 중심)으로 라이다가 축 방향으로 밀리는 만큼 미리 선다
            L -= LIDAR_BEHIND_AXLE * (1 - math.cos(math.radians(final_heading) - axis))
        while time.time() - t0 < L / self.v * 3 + 20:
            self._spin(0.05)
            if should_stop and should_stop():
                self.stop(); status = 'canceled'; break
            m = self.measure(p0, p1)
            src = 'wall' if m['wall'] is not None else 'map'
            e, th_rel = (m['e_wall'], m['th_wall']) if src == 'wall' else (m['e_map'], m['th_map'])
            rows.append([time.time() - t0, m['x'], m['y'], m['th'], m['s'], m['e_map'], m['th_map'],
                         np.nan if m['e_wall'] is None else m['e_wall'], np.nan if m['th_wall'] is None else m['th_wall'],
                         m['min_gap'], m['front_gap'], src == 'wall'])
            if m['min_gap'] < SIDE_GAP:
                self.stop(); status = 'contact'; break
            if m['front_gap'] < FRONT_GAP:
                self.stop()
                blocked_since = blocked_since or time.time()
                if time.time() - blocked_since > 10:
                    status = 'blocked'; break
                continue
            blocked_since = None
            if stop_on_tape:
                if time.time() - self.ir[1] > 0.5:
                    self.stop(); status = 'ir_stale'; break
                if tape_s is None and m['s'] > s_ir - TAPE_WIN and sum(tape_pos(self.ir[0])[0]) >= TAPE_SEEN:
                    tape_s = m['s']
                if tape_s is None and m['s'] > s_ir + TAPE_WIN:
                    self.stop(); status = 'no_tape'; break
                remain = (tape_s + SENSOR_AHEAD - m['s']) if tape_s is not None else (s_ir + SENSOR_AHEAD - m['s'])
            else:
                remain = L - m['s']
            if remain < 0.003:
                self.stop(); status = 'ok'; break
            v = max(0.03, min(self.v, self.v * remain / 0.08))
            self.send(v, control(e, th_rel))
        self.stop()
        if status == 'ok' and final_heading is not None:
            self.rotate_to(math.radians(final_heading))
        R = np.array(rows) if rows else np.zeros((0, 12))
        if log_path and len(R):
            np.savez(log_path, rows=R, cols=np.array(['t', 'x', 'y', 'th', 's', 'e_map', 'th_map', 'e_wall', 'th_wall',
                                                       'min_gap', 'front_gap', 'use_wall']),
                     p0=np.array(p0_cm), p1=np.array(p1_cm), side=self.side, d_ref=self.d_ref)
        out = dict(status=status, time_s=round(time.time() - t0, 1))
        if stop_on_tape:
            out.update(tape_found_cm=None if tape_s is None else round(100 * (tape_s - s_ir), 1))  # 예상보다 + 늦게 / - 일찍
        if len(R):
            out.update(wall_pct=round(100 * R[:, 11].mean()), min_gap_cm=round(100 * R[:, 9].min(), 1),
                       max_abs_e_wall_cm=round(100 * np.nanmax(np.abs(R[:, 7])), 1) if np.isfinite(R[:, 7]).any() else None,
                       max_abs_e_map_cm=round(100 * np.abs(R[:, 5]).max(), 1))
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('p0'); ap.add_argument('p1')
    ap.add_argument('--side', choices=['right', 'left'], default='right')
    ap.add_argument('--offset', type=float, default=10.0, help='축선에서 벽까지 cm')
    ap.add_argument('--speed', type=float, default=0.08)
    ap.add_argument('--final-heading', type=float, default=None)
    ap.add_argument('--check', action='store_true', help='움직이지 않고 측정만 출력')
    ap.add_argument('--body-r', type=float, default=BODY_R * 100, help='접촉 검사 몸체 반경 cm (기본 7 = 그릇 Ø14, 빈 로봇 5.5)')
    ap.add_argument('--stop-on-tape', action='store_true', help='p1 = 차선 위 점, IR 로 테이프를 밟고 축이 테이프 위에 오면 멈춤')
    a = ap.parse_args()
    p0 = tuple(map(float, a.p0.split(','))); p1 = tuple(map(float, a.p1.split(',')))
    import rclpy
    rclpy.init()
    node = rclpy.create_node('corridor_drive')
    cd = CorridorDrive(node, a.side, a.offset, a.speed, body_r=a.body_r / 100)
    if not cd.wait_ready():
        print('scan/TF 없음'); return 1
    if a.check:
        try:
            while True:
                cd._spin(0.5)
                m = cd.measure((p0[0] / 100, p0[1] / 100), (p1[0] / 100, p1[1] / 100))
                w = m['wall']
                ws = (f"벽 d {100 * w['d']:.1f}cm α {math.degrees(w['alpha']):+.1f}° (점 {w['n']}, 길이 {100 * w['span']:.0f}cm, 잔차 {1000 * w['res']:.1f}mm)"
                      f" → 옆 오차 {100 * m['e_wall']:+.1f}cm" if w else '벽 없음')
                print(f"라이다 ({100 * m['x']:.1f}, {100 * m['y']:.1f}) {math.degrees(m['th']):.1f}°  진행 {100 * m['s']:.1f}/{100 * m['L']:.0f}cm  "
                      f"지도 옆 오차 {100 * m['e_map']:+.1f}cm {math.degrees(m['th_map']):+.1f}°  | {ws}  | 둘레 여유 {100 * m['min_gap']:.1f} 앞 {100 * m['front_gap']:.1f}cm",
                      flush=True)
        except KeyboardInterrupt:
            return 0
    os.makedirs(os.path.join(HERE, 'route_logs'), exist_ok=True)
    log = os.path.join(HERE, 'route_logs', f'corridor_{time.strftime("%m%d_%H%M%S")}.npz')
    try:
        r = cd.run(p0, p1, a.final_heading, log, stop_on_tape=a.stop_on_tape)
    except KeyboardInterrupt:
        cd.stop(); print('취소'); return 1
    print(r, '기록', log)
    rclpy.shutdown()
    return 0 if r['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
