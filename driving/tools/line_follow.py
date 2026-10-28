# 차선 테이프 따라가기 시험: IR 3채널(왼/가운데/오른)로 테이프 옆 위치를 재서 조향, odom 거리로 멈춘다.
# **로봇에서** 실행 (IR 노드 pinky_sensor_adc 가 /ir_sensor/range 를 내고 있어야 함). 로봇이 움직임!
#   python3 line_follow.py --dist 30 --speed 0.05 --heading 180
# - 센서별 보정: 흰색/바닥 값 (ir_sweep 2026-10-26 6364) -> 흰 정도 0~1, 테이프 옆 위치 = 흰 정도 가중 평균 (왼쪽 +)
# - 조향: w = KP * 테이프 위치 + KD * 위치 변화율 + KH * (목표 방향 - AMCL 방향)
#   센서가 바퀴 축 ~3cm 앞이라 P 만으로는 감쇠가 약함 (10-26 보정 시험: 0.9cm 비킴 -> 0.8cm 넘침). KD 로 감쇠
# - 멈춤: odom 거리 도달 / 테이프 놓침 0.3 s / AMCL 옆 벗어남 > MAX_DEV / 시간 초과
# 결과: ir_logs/line_<시각>.csv
import argparse
import math
import os
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import UInt16MultiArray
from tf2_ros import Buffer, TransformException, TransformListener

HERE = os.path.dirname(os.path.abspath(__file__))
# 토픽 배열 순서 [adc2, adc1, adc0] = [왼쪽, 가운데, 오른쪽] (로봇 진행 방향 기준)
WHITE = (640.0, 1870.0, 450.0)    # 보정 파일이 없을 때만 쓰는 값 (pinky_6364 10-26 회전 시험)
# 바닥 값은 자리마다 다름 (10-26 B2: 1900/2720/2000, 10-27 B1 x≈150: 2450/3000/2250, 가장 어두운 곳 2755/-/2970).
# 고정 바닥값이 실제보다 낮으면 테이프 반쯤 밟은 옆 센서가 0 으로 읽혀 가운데-옆 사이에 사각지대 → 10-27 B1 에서 lost.
# → 채널마다 최근 FLOOR_WIN 초 최댓값을 바닥으로 씀 (FLOOR_MIN~FLOOR_MAX 로 자름. 테이프 위에 오래 있으면 FLOOR_MIN)
FLOOR = (2450.0, 3000.0, 2250.0)        # 기록 없을 때 시작값 (보정 파일 없을 때)
FLOOR_MIN = (1700.0, 2700.0, 1500.0)
# 로봇별 보정 (ir_sweep.py --save → ~/.config/pinky/ir_cal.json). 로봇마다 센서 감도가 달라 고정값 대신 이것을 씀 (10-27 사용자)
CAL_PATH = os.path.expanduser('~/.config/pinky/ir_cal.json')
CAL_SRC = '기본값 (pinky_6364 10-26) — ir_sweep.py --save 로 이 로봇을 보정할 것'
try:
    import json as _json
    _c = _json.load(open(CAL_PATH))
    WHITE, FLOOR = tuple(_c['white']), tuple(_c['floor'])
    FLOOR_MIN = tuple(w + 0.6 * (f - w) for w, f in zip(WHITE, FLOOR))   # 바닥 추적 하한: 흰색-바닥 사이 60% 지점
    CAL_SRC = f"{CAL_PATH} ({_c.get('serial')} {_c.get('time')})"
except (OSError, ValueError, KeyError):
    pass
FLOOR_MAX = 3300.0
FLOOR_WIN = 2.0                          # s
SENSOR_Y = (0.02, 0.0, -0.02)    # m, 센서 옆 위치 (왼쪽 +), 회전 시험에서 추정 (10-27 다시 재도 비율 같음: 옆 간격 ≈ 0.7 × 축-센서 거리)
# I2C 충돌로 한 번씩 튀는 값(3400~3800) -> 채널마다 최근 3개 중앙값. (고정 기준 3000 은 어두운 바닥 3125 를 버려서 10-26 폐기)
LOST_W = 0.3                     # 흰 정도 합이 이보다 작으면 테이프 없음
DY_TAU = 0.15                    # s, 변화율 저역 통과 시상수
MAX_DEV = 0.03                   # m, AMCL 기준 출발 직선에서 옆으로 이만큼 벗어나면 중단


class FloorTrack:
    """채널마다 최근 FLOOR_WIN 초 최댓값 = 지금 바닥 값"""
    def __init__(self):
        self.hist = []
        self.now = FLOOR

    def update(self, v):
        t = time.time()
        self.hist = [h for h in self.hist if t - h[0] < FLOOR_WIN] + [(t, v)]
        self.now = tuple(min(FLOOR_MAX, max(lo, max(h[1][i] for h in self.hist))) for i, lo in enumerate(FLOOR_MIN))


FLOOR_NOW = FloorTrack()


class IrFilter:
    """채널마다 최근 3개 원값의 중앙값 (한 번 튀는 값 제거, 50ms 늦음). 바닥 값 추적도 여기서 갱신"""
    def __init__(self):
        self.buf = []

    def __call__(self, data):
        self.buf = (self.buf + [tuple(float(v) for v in data[:3])])[-3:]
        v = tuple(sorted(c)[len(c) // 2] for c in zip(*self.buf))
        FLOOR_NOW.update(v)
        return v


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class LineFollow(Node):
    def __init__(self):
        super().__init__('line_follow')
        self.pub = self.create_publisher(Twist, 'cmd_vel_nav', 10)
        self.odom = None
        self.ir = None
        self.ir_t = 0.0
        self._irf = IrFilter()
        self.create_subscription(Odometry, '/odom', self._on_odom, 20)
        self.create_subscription(UInt16MultiArray, '/ir_sensor/range', self._on_ir, qos_profile_sensor_data)
        self.tfb = Buffer()
        self.tfl = TransformListener(self.tfb, self)

    def _on_odom(self, m):
        p = m.pose.pose
        self.odom = (p.position.x, p.position.y, yaw_of(p.orientation))

    def _on_ir(self, m):
        if len(m.data) >= 3:
            self.ir = self._irf(m.data)
            self.ir_t = time.time()

    def map_pose(self):
        try:
            tr = self.tfb.lookup_transform('map', 'base_footprint', rclpy.time.Time()).transform
        except TransformException:
            return None
        return tr.translation.x, tr.translation.y, yaw_of(tr.rotation)

    def cmd(self, v, w):
        t = Twist(); t.linear.x = float(v); t.angular.z = float(w); self.pub.publish(t)


def tape_pos(ir):
    """흰 정도 (왼, 가운데, 오른) 와 테이프 옆 위치 m (왼쪽 +). 테이프 없으면 위치 None"""
    w = [min(1.0, max(0.0, (f - v) / (f - wh))) for v, wh, f in zip(ir, WHITE, FLOOR_NOW.now)]
    s = sum(w)
    if s < LOST_W:
        return w, None
    return w, sum(wi * yi for wi, yi in zip(w, SENSOR_Y)) / s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dist', type=float, default=30.0, help='갈 거리 cm (odom)')
    ap.add_argument('--speed', type=float, default=0.05, help='m/s')
    ap.add_argument('--heading', type=float, default=None, help='진행 방향 deg (그림/지도 틀). 없으면 출발 AMCL 방향')
    ap.add_argument('--kp', type=float, default=8.0, help='rad/s per m (테이프 위치)')
    ap.add_argument('--kd', type=float, default=15.0, help='rad/s per m/s (테이프 위치 변화율, 감쇠)')
    ap.add_argument('--kh', type=float, default=0.0, help='rad/s per rad (AMCL 방향). 테이프가 지도 축과 1~2° 어긋나 있어 기본 0')
    ap.add_argument('--wmax', type=float, default=0.4)
    a = ap.parse_args()

    rclpy.init()
    n = LineFollow()
    t_end = time.time() + 5
    mp = None
    while time.time() < t_end and (n.odom is None or n.ir is None or mp is None):
        rclpy.spin_once(n, timeout_sec=0.05)
        mp = n.map_pose()
    if n.odom is None or n.ir is None or mp is None:
        print('odom / IR / TF(map) 중 안 들어오는 것 있음'); return 1

    w0, y0 = tape_pos(n.ir)
    print(f'출발: IR {n.ir} 흰 정도 {[round(x, 2) for x in w0]} 테이프 위치 {None if y0 is None else round(y0 * 100, 2)} cm')
    if y0 is None:
        print('출발 자리에서 테이프가 안 보임 -> 중단'); return 1

    hd = math.radians(a.heading) if a.heading is not None else mp[2]
    ux, uy = math.cos(hd), math.sin(hd)
    sx, sy = mp[0], mp[1]
    o0 = n.odom
    rows = []
    status = 'timeout'
    t0 = time.time()
    lost_since = None
    last_ir_t, y_prev, dy = 0.0, None, 0.0
    deadline = t0 + a.dist / 100.0 / a.speed * 2.5 + 5
    try:
        while time.time() < deadline:
            rclpy.spin_once(n, timeout_sec=0.02)
            if time.time() - n.ir_t > 0.5:
                status = 'ir_stale'; break
            d = math.hypot(n.odom[0] - o0[0], n.odom[1] - o0[1])
            if d >= a.dist / 100.0:
                status = 'done'; break
            mp = n.map_pose() or mp
            dev = -(mp[0] - sx) * uy + (mp[1] - sy) * ux          # 출발 직선 왼쪽 +
            if abs(dev) > MAX_DEV:
                status = 'deviated'; break
            herr = wrap(hd - mp[2])
            if n.ir_t == last_ir_t:
                continue                                       # 새 IR 값(20 Hz)마다 한 번 제어
            dt = n.ir_t - last_ir_t if last_ir_t else 0.05
            last_ir_t = n.ir_t
            wts, yt = tape_pos(n.ir)
            if yt is None:
                lost_since = lost_since or time.time()
                if time.time() - lost_since > 0.3:
                    status = 'lost'; break
                n.cmd(0.0, 0.0)
                continue
            lost_since = None
            if y_prev is not None:                             # 테이프 위치 변화율 (저역 통과) -> 감쇠
                k = min(1.0, dt / (DY_TAU + dt))
                dy += k * ((yt - y_prev) / max(dt, 0.02) - dy)
            y_prev = yt
            w = max(-a.wmax, min(a.wmax, a.kp * yt + a.kd * dy + a.kh * herr))
            left = a.dist / 100.0 - d
            v = a.speed if left > 0.05 else max(0.02, a.speed * left / 0.05)
            n.cmd(v, w)
            rows.append((time.time() - t0, d, *n.ir, *wts, yt, dy, dev, math.degrees(herr), v, w))
    finally:
        for _ in range(5):
            n.cmd(0.0, 0.0); time.sleep(0.02)

    t_hold = time.time() + 0.5
    while time.time() < t_hold:
        rclpy.spin_once(n, timeout_sec=0.02)
    mp = n.map_pose() or mp
    d = math.hypot(n.odom[0] - o0[0], n.odom[1] - o0[1])
    dev = -(mp[0] - sx) * uy + (mp[1] - sy) * ux
    print(f'결과 {status}: odom {d * 100:.1f} cm, {time.time() - t0:.1f} s, AMCL 끝 옆 벗어남 {dev * 100:+.1f} cm, '
          f'방향 차 {math.degrees(wrap(mp[2] - hd)):+.1f}°')
    if rows:
        ys = [r[8] for r in rows]; devs = [r[10] for r in rows]
        print(f'테이프 위치 cm: 평균 {sum(ys) / len(ys) * 100:+.2f}, 최대 |{max(abs(y) for y in ys) * 100:.2f}|  '
              f'AMCL 옆 최대 |{max(abs(x) for x in devs) * 100:.2f}| cm')

    os.makedirs(os.path.join(HERE, 'ir_logs'), exist_ok=True)
    path = os.path.join(HERE, 'ir_logs', time.strftime('line_%m%d_%H%M%S.csv'))
    with open(path, 'w') as f:
        f.write('t,dist,ir_l,ir_c,ir_r,w_l,w_c,w_r,tape_y,tape_dy,amcl_dev,head_err_deg,v,w\n')
        for r in rows:
            f.write(','.join(f'{x:.4f}' for x in r) + '\n')
    print(f'{len(rows)} 줄 저장: {path}')
    n.destroy_node(); rclpy.shutdown()
    return 0 if status == 'done' else 2


if __name__ == '__main__':
    raise SystemExit(main())
