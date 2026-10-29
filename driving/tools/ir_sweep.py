# IR 라인 센서 회전 시험: 제자리에서 좌우로 천천히 돌며 IR 3채널 값과 odom 각도를 함께 기록한다.
# 센서들이 테이프를 가로질러 지나가므로 채널별 흰색/바닥 값, 실제 가운데 채널, 센서 간격을 알 수 있다.
# **로봇에서** 실행 (IR 노드 pinky_sensor_adc 가 /ir_sensor/range 를 내고 있어야 함). 로봇이 움직임!
#   python3 ir_sweep.py --amp 30 --speed 0.2          # 0 -> +30 -> -30 -> 0 (odom 각도, 실제는 8~15% 더 돎)
#   python3 ir_sweep.py --amp 45 --save               # 로봇별 보정: 테이프 위에서 차선 방향으로 놓고 실행 →
#       채널마다 흰색 = 하위 3%, 바닥 = 상위 10% 값을 ~/.config/pinky/ir_cal.json 에 저장 (line_follow 가 읽음).
#       로봇마다 센서 감도가 달라 고정값을 쓰지 않는다 (10-27 사용자). 세 채널 동시 >3300 (I2C 잡음) 줄은 뺌
# 결과: ir_logs/ir_sweep_<시각>.csv (t, yaw_deg, ch_a, ch_b, ch_c = 토픽 배열 순서 [adc2, adc1, adc0])
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

HERE = os.path.dirname(os.path.abspath(__file__))


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class Sweep(Node):
    def __init__(self):
        super().__init__('ir_sweep')
        self.pub = self.create_publisher(Twist, 'cmd_vel_nav', 10)
        self.yaw = None          # 펼친(unwrap) odom 각도, rad
        self._last = None
        self.rows = []
        self.t0 = time.time()
        self.create_subscription(Odometry, '/odom', self._on_odom, 20)
        self.create_subscription(UInt16MultiArray, '/ir_sensor/range', self._on_ir, qos_profile_sensor_data)

    def _on_odom(self, m):
        y = yaw_of(m.pose.pose.orientation)
        if self._last is None:
            self.yaw = y
        else:
            self.yaw += math.atan2(math.sin(y - self._last), math.cos(y - self._last))
        self._last = y

    def _on_ir(self, m):
        if self.yaw is not None and len(m.data) >= 3:
            self.rows.append((time.time() - self.t0, math.degrees(self.yaw), *m.data[:3]))

    def cmd(self, w):
        t = Twist(); t.angular.z = float(w); self.pub.publish(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--amp', type=float, default=30.0, help='좌우 진폭 deg (odom)')
    ap.add_argument('--speed', type=float, default=0.2, help='최대 각속도 rad/s')
    ap.add_argument('--save', action='store_true', help='흰색·바닥 값을 ~/.config/pinky/ir_cal.json 에 저장')
    a = ap.parse_args()

    rclpy.init()
    n = Sweep()
    t_end = time.time() + 5
    while (n.yaw is None or not n.rows) and time.time() < t_end:
        rclpy.spin_once(n, timeout_sec=0.05)
    if n.yaw is None or not n.rows:
        print('odom 또는 /ir_sensor/range 가 안 들어옴'); return 1

    y0 = n.yaw
    targets = [a.amp, -a.amp, 0.0]
    deadline = time.time() + 4 * (3 * a.amp / math.degrees(a.speed)) + 15
    try:
        for tgt in targets:
            goal = y0 + math.radians(tgt)
            while time.time() < deadline:
                rclpy.spin_once(n, timeout_sec=0.02)
                err = goal - n.yaw
                if abs(err) < math.radians(0.7):
                    break
                w = max(0.06, min(a.speed, 1.5 * abs(err)))
                n.cmd(math.copysign(w, err))
            n.cmd(0.0)
            t_hold = time.time() + 0.6
            while time.time() < t_hold:
                rclpy.spin_once(n, timeout_sec=0.02)
            print(f'목표 {tgt:+.0f}° → odom {math.degrees(n.yaw - y0):+.1f}°')
    finally:
        for _ in range(5):
            n.cmd(0.0); time.sleep(0.02)

    os.makedirs(os.path.join(HERE, 'ir_logs'), exist_ok=True)
    path = os.path.join(HERE, 'ir_logs', time.strftime('ir_sweep_%m%d_%H%M%S.csv'))
    with open(path, 'w') as f:
        f.write('t,yaw_deg,ch_a,ch_b,ch_c\n')
        for r in n.rows:
            f.write(f'{r[0]:.3f},{r[1] - math.degrees(y0):.2f},{r[2]},{r[3]},{r[4]}\n')
    print(f'{len(n.rows)} 줄 저장: {path}')
    n.destroy_node(); rclpy.shutdown()
    return save_cal(n.rows) if a.save else 0


def save_cal(rows, min_contrast=400):
    import json
    vals = [r[2:5] for r in rows if not all(v > 3300 for v in r[2:5])]
    if len(vals) < 50:
        print('보정 실패: 값이 너무 적음'); return 2
    white, floor = [], []
    for c in range(3):
        v = sorted(x[c] for x in vals)
        white.append(float(v[int(0.03 * (len(v) - 1))])); floor.append(float(v[int(0.90 * (len(v) - 1))]))
    names = ('왼', '가운데', '오른')
    for nm, w, f in zip(names, white, floor):
        print(f'  {nm:3s} 흰색 {w:6.0f}  바닥 {f:6.0f}  대비 {f - w:6.0f}')
    bad = [nm for nm, w, f in zip(names, white, floor) if f - w < min_contrast]
    if bad:
        print(f'보정 실패: {bad} 채널 대비 < {min_contrast} — 테이프 위 차선 방향으로 놓였는지 확인'); return 2
    serial = next((ln.split(':')[1].strip() for ln in open('/proc/cpuinfo') if ln.startswith('Serial')), '?')
    path = os.path.expanduser('~/.config/pinky/ir_cal.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(dict(serial=serial, time=time.strftime('%Y-%m-%d %H:%M'), white=white, floor=floor), open(path, 'w'), indent=1)
    print(f'보정 저장: {path} (serial {serial})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
