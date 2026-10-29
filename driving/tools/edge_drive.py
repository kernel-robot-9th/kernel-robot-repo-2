# 주행 그래프 엣지 하나를 실제 주행 방식으로 달리는 공용 코드 — edge_run.py (시간 측정) 와 api/pinky_api.py (/drive) 가 같이 쓴다.
# **로봇에서** (IR 노드 pinky_sensor_adc, AMCL TF 필요). rclpy.init() 은 부르는 쪽이 먼저.
# 엣지 mode (graph.yaml):
#   line     = 테이프 따라가기 (b 의 x/y 에 라이다 중심이 닿을 때까지. 다음에 꺾으면 회전 뒤 라이다가 노드에 오게 바퀴 축으로 멈춤)
#   transfer = 차선 → 차선 / 협로 입구 → 차선: 직진하다 IR 로 새 테이프를 찾으면 바퀴 축이 테이프 위에서 멈춤
#              차선 → 협로 입구: 벽 따라가기 (벽 없는 입구는 AMCL 축선 직진)
#   wall     = 협로 벽 따라가기 (따라갈 쪽 = 엣지 wall 선분이 진행 방향 왼쪽/오른쪽)
#   nav      = a→b 직선을 AMCL 축선으로 (라이다 접촉 검사)
#   dock     = 정밀 주차 노드(type dock)로 들어가면 카메라 마커 정밀 주차 (precise_dock.py),
#              거기서 나오면 방향 그대로 뒤로 (undock). 나오는 엣지는 출발 전에 엣지 방향으로 돌지 않는다 → face()
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GRAPH = os.path.join(HERE, '..', 'graph', 'graph.yaml')
TIMES = os.path.join(HERE, '..', 'graph', 'edge_times.yaml')
SPEED = 0.05            # m/s, 벽 따라가기 속도 (테이프 따라가기는 lane_drive.SPEED = 0.05)
BODY_R = 0.055          # m, 빈 로봇 (그릇 없음)
DRIVEABLE = ('line', 'transfer', 'wall', 'nav', 'dock')
UNDOCK_V = 0.02         # m/s, 정밀 주차 자리에서 뒤로
FALLBACK_SPEED = 4.5    # cm/s, edge_times.yaml 에 없는 엣지의 예상 시간 (FMS Params.speed 와 같음)
FALLBACK_S = {'dock': 30.0, 'undock': 6.0}   # 아직 안 잰 정밀 주차·물러나기 예상 (10-29 어림, 실측 필요)


def load_graph(path=GRAPH):
    g = yaml.safe_load(open(path))
    N = {k: v for k, v in g['nodes'].items() if not v.get('deferred')}
    E = {}
    for e in g['edges']:
        if e.get('deferred') or e['a'] not in N or e['b'] not in N:
            continue
        E[(e['a'], e['b'])] = e
        E[(e['b'], e['a'])] = e
    return N, E


def heading(N, a, b):
    (ax, ay), (bx, by) = N[a]['xy'], N[b]['xy']
    return math.degrees(math.atan2(by - ay, bx - ax)) % 360


def is_undock(N, E, a, b):
    return E[(a, b)]['mode'] == 'dock' and N[a].get('type') == 'dock'


def face(N, E, a, b):
    """엣지 a→b 를 달릴 때 로봇이 바라볼 방향 deg. 정밀 주차 자리에서 나오는 엣지는 뒤로 가므로 반대 방향"""
    h = heading(N, a, b)
    return (h + 180) % 360 if is_undock(N, E, a, b) else h


def wall_of(N, E, a, b):
    """엣지 a→b 가 따라갈 벽 선분: wall 엣지면 그 wall, 협로 입구(gate)로 드는 transfer 면 그 gate 에 붙은 wall 엣지의 wall"""
    e = E[(a, b)]
    if e.get('wall'):
        return e['wall']
    for g in (b, a):
        if N[g]['type'] == 'gate':
            for (x, y), f in E.items():
                if x == g and f.get('mode') == 'wall' and f.get('wall'):
                    return f['wall']
    return None


def wall_side(N, E, a, b):
    """(벽 쪽 'left'/'right', 축선-벽 cm). 벽 선분을 진행 방향 왼쪽/오른쪽으로 가름 (10-26: 오른쪽 협로는 늘 x=140 벽 —
    올라갈 때 right, 내려갈 때 left)"""
    w = wall_of(N, E, a, b)
    if not w:
        return 'right', 10.0
    (ax, ay), (bx, by) = N[a]['xy'], N[b]['xy']
    L = math.hypot(bx - ax, by - ay); ux, uy = (bx - ax) / L, (by - ay) / L
    (wx0, wy0), (wx1, wy1) = w
    mx, my = (wx0 + wx1) / 2, (wy0 + wy1) / 2
    cross = ux * (my - ay) - uy * (mx - ax)          # > 0 = 벽이 왼쪽
    return ('left' if cross > 0 else 'right'), round(abs(cross), 1)


class Times:
    """graph/edge_times.yaml 실측 → 예상 시간 (이동은 방향별 중앙값, 회전은 r0 + s/deg · |각도|)"""

    def __init__(self, path=TIMES):
        try:
            d = yaml.safe_load(open(path)) or {}
        except OSError:
            d = {}
        self.edges = d.get('edges') or {}
        self.rot = d.get('rotate') or {'r0_s': 2.1, 's_per_deg': 0.0233}

    def move_s(self, N, E, a, b):
        r = self.edges.get(f'{a}>{b}')
        if r:
            return float(r['move_s'])
        if E[(a, b)]['mode'] == 'dock':
            return FALLBACK_S['undock' if is_undock(N, E, a, b) else 'dock']
        return math.dist(N[a]['xy'], N[b]['xy']) / FALLBACK_SPEED

    def rot_s(self, deg):
        deg = abs((deg + 180) % 360 - 180)
        return 0.0 if deg < 1.5 else self.rot['r0_s'] + self.rot['s_per_deg'] * deg


class EdgeDriver:
    """엣지 주행기. dr = lane_drive.Driver (자기 ROS 노드를 spin_once 로 돌림), should_stop = 취소 확인 함수"""

    def __init__(self, N=None, E=None):
        from corridor_drive import CorridorDrive
        from lane_drive import LIDAR_BEHIND_AXLE, Driver
        if N is None:
            N, E = load_graph()
        self.N, self.E, self.LB = N, E, LIDAR_BEHIND_AXLE
        self.dr = Driver()                     # odom / IR / TF 가 5초 안에 안 오면 RuntimeError
        self.CorridorDrive = CorridorDrive
        self.dock_log = []                     # 정밀 주차 출력 (마지막 몇 줄)
        self._stop = None
        self._cdo = None

    def _cd(self, side, off_cm, use_wall=True):
        """벽 따라가기·AMCL 직진기 하나를 다시 씀 (만들 때마다 /scan 구독·발행기가 노드에 쌓이므로 — API 는 오래 돈다)"""
        if self._cdo is None:
            self._cdo = self.CorridorDrive(self.dr.n, side, off_cm, SPEED, tf_buffer=self.dr.n.tfb, body_r=BODY_R)
        cd = self._cdo
        cd.side, cd.d_ref, cd.use_wall, cd.v, cd.body_r = side, off_cm / 100, use_wall, SPEED, BODY_R
        return cd

    @property
    def should_stop(self):
        return self._stop

    @should_stop.setter
    def should_stop(self, f):
        self._stop = f
        self.dr.should_stop = f

    def lidar_pose(self):
        x, y, th = self.dr.pose()
        return (x - self.LB * math.cos(th)) * 100, (y - self.LB * math.sin(th)) * 100, math.degrees(th) % 360

    def rotate(self, hd):
        return self.dr.rotate(hd)

    def move(self, a, b, mode, hd, nxt=None):
        """엣지 a→b 를 달림 (회전은 부르는 쪽이 먼저: face()). hd = 진행 방향 deg, nxt = 다음 엣지 방향 (모르면 None).
        반환 (status, extra dict)"""
        N = self.N
        bx, by = N[b]['xy']
        if mode == 'line':
            tgt = bx if hd in (0, 180) else by
            if nxt is None:
                return self.dr.follow(hd, tgt, 'lidar'), {}
            # 다음 엣지로 꺾는 제자리 회전은 바퀴 축 중심이라 라이다(1.7cm 뒤)가 옆으로 밀린다. 회전 뒤 라이다가 노드에 오게
            # 바퀴 축을 노드 + LB·cos(꺾는 각) 에 세운다 (90° 면 축 = 노드). 10-29: B2_78→B2_40 뒤 90° 돌아 GB40 으로
            # 올라갈 때 1.7cm 왼쪽에서 출발해 벽 따라가기가 80~84° 로 꺾임
            u = 1 if hd in (0, 90) else -1
            return self.dr.follow(hd, tgt + u * self.LB * 100 * math.cos(math.radians(nxt - hd)), 'axle'), {}
        if mode == 'transfer' and N[b]['type'] == 'lane':
            return self.dr.transfer(by if hd in (90, 270) else bx), {}
        if mode == 'dock':
            return self.undock(b) if is_undock(N, self.E, a, b) else self.dock()
        if mode == 'nav' or (mode == 'transfer' and not wall_of(N, self.E, a, b)):
            # Nav2 대신: AMCL 축선 직진 + 라이다 접촉 검사 (벽 맞춤 없음). 10-28 Nav2 충돌 검사가 계단 통로·협로 입구에서
            # 여유 3~5cm 를 '충돌'로 보고 멈춤 → 협로의 벽 없는 구간처럼 달림 (사용자)
            cd = self._cd('right', 10.0, use_wall=False)
            r = cd.run(N[a]['xy'], N[b]['xy'], should_stop=self._stop)
            r['drive'] = 'amcl'
            return r.pop('status'), r
        if mode in ('transfer', 'wall'):     # 차선 → 협로 입구, 협로 벽 따라가기
            side, off = wall_side(N, self.E, a, b)
            cd = self._cd(side, off)
            r = cd.run(N[a]['xy'], N[b]['xy'], should_stop=self._stop)
            r['side'] = side
            return r.pop('status'), r
        return f'mode_{mode}_todo', {}

    def straight(self, cm, v=0.02):
        """방향 유지하고 odom 으로 cm 만큼 천천히 직진 (cm < 0 = 뒤로)"""
        import rclpy
        n = self.dr.n
        o0 = n.odom; yaw0 = o0[2]
        v = math.copysign(abs(v), cm)
        t_end = time.time() + abs(cm) / 100 / abs(v) + 5
        while time.time() < t_end:
            rclpy.spin_once(n, timeout_sec=0.02)
            if self.dr.canceled():
                self.dr.stop(); return 'canceled'
            d = math.hypot(n.odom[0] - o0[0], n.odom[1] - o0[1])
            if d >= abs(cm) / 100:
                self.dr.stop(); return 'ok'
            err = math.atan2(math.sin(n.odom[2] - yaw0), math.cos(n.odom[2] - yaw0))
            n.cmd(v, -2.0 * err)
        self.dr.stop(); return 'timeout'

    def undock(self, b):
        """정밀 주차 자리에서 방향 그대로 뒤로: 라이다 중심이 b 의 진행 축 위치에 올 때까지 (AMCL)"""
        self.dr.spin(0.3)
        x, y, th = self.lidar_pose()
        bx, by = self.N[b]['xy']
        d = (x - bx) * math.cos(math.radians(th)) + (y - by) * math.sin(math.radians(th))   # b 보다 앞으로 나와 있는 거리 cm
        if d < 0.5:
            return 'ok', dict(back_cm=0.0)
        return self.straight(-d, UNDOCK_V), dict(back_cm=round(d, 1))

    def dock(self):
        """precise_dock.py (따로 프로세스, 카메라). 취소면 SIGINT"""
        p = subprocess.Popen([sys.executable, os.path.join(HERE, 'precise_dock.py')], cwd=HERE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = self.dock_log = []

        def read():
            for ln in p.stdout:
                ln = ln.rstrip()
                if not (ln.startswith('[') and ('INFO' in ln or 'WARN' in ln)):   # libcamera 로그 빼고
                    lines.append(ln)
        th = threading.Thread(target=read, daemon=True); th.start()
        while p.poll() is None:
            if self.dr.canceled():
                p.send_signal(signal.SIGINT)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                self.dr.stop()
                return 'canceled', dict(lines=lines[-6:])
            time.sleep(0.1)
        th.join(2)
        out = dict(exit=p.returncode, lines=lines[-6:])
        for ln in reversed(lines):   # "최종: 앞뒤 -0.4mm, 좌우 +1.7mm, 방향 +0.40°  (...)" → 마커 기준 자세와의 어긋남
            m = re.search(r'최종: 앞뒤 ([-+\d.]+)mm, 좌우 ([-+\d.]+)mm, 방향 ([-+\d.]+)°', ln)
            if m:
                out['final'] = dict(fwd_mm=float(m[1]), left_mm=float(m[2]), heading_deg=float(m[3])); break
        return ('ok' if p.returncode == 0 else 'dock_failed'), out

    def spin360(self):
        """제자리 한 바퀴 (병실 배송 완료 표시): 120° 씩 세 번, 끝은 처음 방향"""
        h0 = self.lidar_pose()[2]
        for k in (1, 2, 3):
            st = self.dr.rotate((h0 + 120 * k) % 360)
            if st != 'ok':
                return st
        return 'ok'

    def stop(self):
        self.dr.stop()
