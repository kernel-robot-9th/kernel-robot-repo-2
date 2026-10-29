# IR 라인 센서 값 실시간 보기 (가변저항 맞출 때). **로봇에서** 실행 — PC 에서는 tools/ir_watch.sh 로.
#   python3 ir_watch.py            # r = 최소/최대 초기화, q 또는 Ctrl+C = 끝
# 화면: 채널마다 지금 값(최근 3개 중앙값, 튀는 값 제거) · 막대 · 초기화 뒤 최소/최대 · 최대-최소(대비)
#       + 세 채널 차이 (테이프 위 / 바닥 위에서 이 값이 작을수록 세 센서 감도가 비슷함)
# 값: 12비트 ADC 0~4095, 흰 테이프 = 낮음, 바닥 = 높음, 반사 없음(틈·검은 것) ≈ 3400 이상
import os
import select
import sys
import termios
import time
import tty

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import UInt16MultiArray

NAMES = ('왼쪽', '가운데', '오른쪽')   # 토픽 배열 [adc2, adc1, adc0] = [왼, 가운데, 오른] (진행 방향 기준)
FULL = 4095
BAR = 40


class Watch(Node):
    def __init__(self):
        super().__init__('ir_watch')
        self.buf, self.v, self.t, self.n = [], None, 0.0, 0
        self.reset()
        self.create_subscription(UInt16MultiArray, '/ir_sensor/range', self.on_ir, qos_profile_sensor_data)

    def reset(self):
        self.lo, self.hi = [FULL] * 3, [0] * 3

    def on_ir(self, m):
        if len(m.data) < 3:
            return
        self.buf = (self.buf + [tuple(m.data[:3])])[-3:]
        self.v = tuple(sorted(c)[len(c) // 2] for c in zip(*self.buf))
        self.t, self.n = time.time(), self.n + 1
        for i, x in enumerate(self.v):
            self.lo[i], self.hi[i] = min(self.lo[i], x), max(self.hi[i], x)


def bar(x):
    k = round(BAR * x / FULL)
    return '█' * k + '·' * (BAR - k)


def draw(w, hz):
    out = ['\033[H\033[J', 'IR 센서 실시간 (r = 최소/최대 초기화, q = 끝)   흰 테이프 = 낮음, 바닥 = 높음\n\n']
    if w.v is None or time.time() - w.t > 1.0:
        out.append('  /ir_sensor/range 가 안 들어옴 — IR 노드(pinky_sensor_adc main_node) 떠 있는지 확인\n')
    else:
        for i, nm in enumerate(NAMES):
            out.append(f'  {nm:4s} {w.v[i]:5d}  {bar(w.v[i])}  최소 {w.lo[i]:5d}  최대 {w.hi[i]:5d}  대비 {w.hi[i] - w.lo[i]:5d}\n')
        out.append(f'\n  세 채널 차이 (지금): {max(w.v) - min(w.v):5d}     ')
        out.append(f'최소끼리 차이: {max(w.lo) - min(w.lo):5d}   최대끼리 차이: {max(w.hi) - min(w.hi):5d}\n')
        if min(w.v) > 3400:
            out.append('  ⚠ 세 채널 모두 3400 넘음 = 반사 없음 (들림·틈·검은 물체) 또는 I2C 잡음\n')
        out.append(f'\n  수신 {hz:4.1f} Hz\n')
    sys.stdout.write(''.join(out)); sys.stdout.flush()


def main():
    rclpy.init()
    w = Watch()
    fd = sys.stdin.fileno()
    tty_ok = os.isatty(fd)
    old = termios.tcgetattr(fd) if tty_ok else None
    if tty_ok:
        tty.setcbreak(fd)
    n0, t0, hz = 0, time.time(), 0.0
    try:
        while True:
            t_end = time.time() + 0.1
            while time.time() < t_end:
                rclpy.spin_once(w, timeout_sec=0.02)
            if time.time() - t0 >= 1.0:
                hz, n0, t0 = (w.n - n0) / (time.time() - t0), w.n, time.time()
            draw(w, hz)
            if tty_ok and select.select([sys.stdin], [], [], 0)[0]:
                c = sys.stdin.read(1)
                if c in ('q', 'Q'):
                    break
                if c in ('r', 'R'):
                    w.reset()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if tty_ok:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()
        w.destroy_node(); rclpy.try_shutdown()


if __name__ == '__main__':
    main()
