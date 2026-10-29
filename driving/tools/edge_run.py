# 주행 그래프 엣지 시간 측정: 엣지를 하나씩 실제 주행 방식으로 달리며 (회전 시간, 이동 시간)을 따로 잰다 → FMS 엣지 비용.
# **로봇에서** 실행 (IR 노드 pinky_sensor_adc 가 /ir_sensor/range 를 내고 있어야 함). 로봇이 움직임!
#   python3 edge_run.py --start B2_130 --nodes '^B[12]_'                 # 경로만 출력 (움직이지 않음)
#   python3 edge_run.py --start B2_130 --nodes '^B[12]_' --go            # 영역 안 모든 방향 엣지를 한 번씩 덮는 경로로 주행
#   python3 edge_run.py --start B2_130 --route B2_180,B1_180 --go        # 정해 준 노드 순서대로
#   --new-only            graph/edge_times.yaml 에 이미 있는 엣지는 재지 않고 지나가기만
#   --min-n 2             edge_times.yaml 에서 2번 미만 잰 엣지만 모자란 만큼 더 (나머지는 지나가기만)
#   --done-log edge_logs/edges_X.csv   끊긴 한 바퀴를 이어서: 그 기록에서 ok 로 잰 엣지는 빼고
#   --pre transfer:22.5   측정 전에 단계 먼저 (transfer:<차선> / rotate:<deg> / straight:<cm>, 노드 위에 올려놓기). --reps 2  엣지마다 두 번씩
#   배터리: 기본은 안 봄. --batt-stop <%> 를 주면 /battery/voltage 1분 중앙값이 그 % 이하일 때 지금 엣지를 마치고 저장·중지
# 엣지마다: ① 제자리 회전 (엣지 방향으로) ② 이동. 이동 방식은 graph.yaml 엣지 mode 를 따른다
#   line     = 테이프 따라가기 (b 의 x/y 에 라이다 중심이 닿을 때까지)
#   transfer = 차선 → 차선 / 협로 입구 → 차선: 직진하다 IR 로 새 테이프를 찾으면 바퀴 축이 테이프 위에서 멈춤
#              차선 → 협로 입구: 벽 따라가기 (corridor_drive, 벽이 안 보이면 AMCL 축선)
#   wall     = 협로 벽 따라가기. 따라갈 쪽은 graph.yaml 엣지의 wall 선분이 진행 방향 왼쪽/오른쪽 어디인지로 정함
#              (오른쪽 협로 = x=140 벽: 올라갈 때 right, 내려갈 때 left. 차선→협로 입구 transfer 도 그 협로의 벽)
#   nav      = a→b 직선을 AMCL 축선으로 5 cm/s (corridor_drive 의 벽 없는 구간과 같음, 라이다 접촉 검사 Ø11). 벽 없는 경계점
#              (방·약제실 문 앞)으로 들어가는 transfer 도 이것으로 (나올 때는 IR 로 테이프 잡는 transfer).
#              --nav2 면 Nav2 FollowPath (10-28: 계단 통로·협로 입구에서 Nav2 충돌 검사가 여유 3~5cm 를 충돌로 보고 멈춤)
# 노드마다 멈춘다 (회전 + 이동을 따로 재려고). 결과: edge_logs/edges_<시각>.csv — 한 줄씩 바로 씀 (중간에 멈춰도 남음)
import argparse
import collections
import heapq
import math
import os
import re
import signal
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GRAPH = os.path.join(HERE, '..', 'graph', 'graph.yaml')
SPEED = 0.05            # m/s, 벽 따라가기 속도 (테이프 따라가기는 lane_drive.SPEED = 0.05)
BODY_R = 0.055          # m, 빈 로봇 (그릇 없음)
BATT_STOP = None        # 기본: 배터리 안 봄 (10-28 사용자: '배터리 보지 말아봐' — 측정값이 들쭉날쭉해 일찍 멈췄음). --batt-stop <%> 로 켬
BATT_N = 12             # /battery/voltage 최근 12번(5초마다 → 1분)의 **중앙값** 전압으로 판단
V_EMPTY, V_FULL = 6.8, 7.6   # pinkylib battery_percentage 와 같은 식 (6.8 V = 0 %, 7.6 V = 100 %)
# 10-28: /battery/percent 를 5번 평균했더니 7.09 V(≈36 %)일 때 8.9 % 로 나와 일찍 멈춤 (사용자: '배터리 측정 이상해').
#        percent 와 voltage 는 따로 읽은 값이고 한 번 읽을 때마다 ±0.15 V(≈±19 %) 흔들림 → 전압 1분 중앙값으로 바꿈
TIMES = os.path.join(HERE, '..', 'graph', 'edge_times.yaml')
DRIVEABLE = ('line', 'transfer', 'wall', 'nav')   # 이 도구가 달릴 수 있는 엣지 mode


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


def tour(N, E, start, keep, reps=1, hd=None, done=None):
    """keep 노드끼리의 모든 방향 엣지를 reps 번씩 지나는 경로 (욕심쟁이: 가장 가까운 안 지난 엣지로). hd = 지금 방향 (회전 줄이기)"""
    adj = {}
    for (a, b), e in E.items():
        if a in keep and b in keep and e['mode'] in DRIVEABLE:
            adj.setdefault(a, []).append(b)
    done = done or {}                                  # {(a, b): 이미 잰 횟수} → reps 에서 뺀 만큼만 더 잼 (나머지는 지나가기만)
    need = {(a, b): max(0, reps - done.get((a, b), 0)) for a in adj for b in adj[a]}

    def dist(a, b):
        return math.dist(N[a]['xy'], N[b]['xy'])

    route, cur = [start], start
    while any(need.values()):
        # 지금 노드에서 바로 나가는 안 지난 엣지 (방향이 지금과 같은 것 먼저 → 회전 줄임)
        out = [b for b in adj.get(cur, []) if need[(cur, b)] > 0]
        if out:
            b = min(out, key=lambda b: (0 if hd is None else abs((heading(N, cur, b) - hd + 180) % 360 - 180), dist(cur, b)))
            need[(cur, b)] -= 1; hd = heading(N, cur, b); route.append(b); cur = b
            continue
        # 가장 가까운, 안 지난 엣지가 남은 노드로 (지나가는 엣지도 측정으로 셈)
        D, prev, pq = {cur: 0.0}, {}, [(0.0, cur)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > D[u]:
                continue
            for v in adj.get(u, []):
                nd = d + dist(u, v)
                if nd < D.get(v, 1e9):
                    D[v], prev[v] = nd, u; heapq.heappush(pq, (nd, v))
        cands = [n for n in D if any(need[(n, b)] > 0 for b in adj.get(n, []))]
        if not cands:
            break
        tgt = min(cands, key=D.get)
        path = [tgt]
        while path[-1] != cur:
            path.append(prev[path[-1]])
        for a, b in zip(path[::-1], path[::-1][1:]):
            need[(a, b)] = max(0, need[(a, b)] - 1); hd = heading(N, a, b); route.append(b)
        cur = tgt
    return route


def plan_moves(N, E, route):
    out = []
    for a, b in zip(route, route[1:]):
        e = E.get((a, b))
        if e is None:
            raise SystemExit(f'엣지 없음: {a} → {b}')
        out.append((a, b, e['mode'], heading(N, a, b), math.dist(N[a]['xy'], N[b]['xy'])))
    return out


class Runner:
    def __init__(self, N, E):
        import rclpy
        from corridor_drive import CorridorDrive
        from lane_drive import LIDAR_BEHIND_AXLE, Driver
        self.rclpy, self.N, self.E, self.LB = rclpy, N, E, LIDAR_BEHIND_AXLE
        from std_msgs.msg import Float32
        rclpy.init()
        self.dr = Driver()
        self.CorridorDrive = CorridorDrive
        self.fp = None                                  # Nav2 FollowPath 액션 클라이언트 (--nav2 일 때만)
        self.use_nav2 = False
        self.batt = collections.deque(maxlen=BATT_N)   # /battery/voltage 최근 값 (5초마다 옴)
        self.dr.n.create_subscription(Float32, '/battery/voltage', lambda m: self.batt.append(float(m.data)), 10)

    def battery(self):
        """최근 BATT_N 번 전압의 중앙값을 % 로 (6 번 미만이면 None)"""
        if len(self.batt) < 6:
            return None
        v = sorted(self.batt)[len(self.batt) // 2]
        return max(0.0, min(100.0, (v - V_EMPTY) / (V_FULL - V_EMPTY) * 100))

    def lidar_pose(self):
        x, y, th = self.dr.pose()
        return (x - self.LB * math.cos(th)) * 100, (y - self.LB * math.sin(th)) * 100, math.degrees(th) % 360

    def move(self, a, b, mode, hd):
        N = self.N
        bx, by = N[b]['xy']
        if mode == 'line':
            tgt = bx if hd in (0, 180) else by
            return self.dr.follow(hd, tgt, 'lidar'), {}
        if mode == 'transfer' and N[b]['type'] == 'lane':
            return self.dr.transfer(by if hd in (90, 270) else bx), {}
        if mode == 'nav' or (mode == 'transfer' and not wall_of(N, self.E, a, b)):
            if self.use_nav2:
                return self.follow_path(N[a]['xy'], N[b]['xy'], hd)
            # Nav2 대신: AMCL 축선 직진 + 라이다 접촉 검사 (벽 맞춤 없음). 10-28 Nav2 충돌 검사가 계단 통로·협로 입구에서
            # 여유 3~5cm 를 '충돌'로 보고 멈춤 → 협로의 벽 없는 구간처럼 달림 (사용자)
            cd = self.CorridorDrive(self.dr.n, 'right', 10.0, SPEED, tf_buffer=self.dr.n.tfb, body_r=BODY_R, use_wall=False)
            r = cd.run(N[a]['xy'], N[b]['xy'])
            r['drive'] = 'amcl'
            return r.pop('status'), r
        if mode in ('transfer', 'wall'):     # 차선 → 협로 입구, 협로 벽 따라가기
            side, off = wall_side(N, self.E, a, b)
            cd = self.CorridorDrive(self.dr.n, side, off, SPEED, tf_buffer=self.dr.n.tfb, body_r=BODY_R)
            r = cd.run(N[a]['xy'], N[b]['xy'])
            r['side'] = side
            return r.pop('status'), r
        return f'mode_{mode}_todo', {}

    def follow_path(self, p0, p1, hd, timeout=None):
        """Nav2 FollowPath 로 p0→p1 직선 (라이다 중심 cm). 반환 (status, extra)"""
        from follow_path_client import build_poses, densify
        from geometry_msgs.msg import PoseStamped
        from nav2_msgs.action import FollowPath
        from nav_msgs.msg import Path
        from rclpy.action import ActionClient
        n = self.dr.n
        if self.fp is None:
            self.fp = ActionClient(n, FollowPath, 'follow_path')
        if not self.fp.wait_for_server(timeout_sec=3.0):
            return 'no_nav2', {}
        path = Path(); path.header.frame_id = 'map'; path.header.stamp = n.get_clock().now().to_msg()
        for x, y, yaw in build_poses(densify([tuple(p0), tuple(p1)], 2.0), hd):
            q = PoseStamped(); q.header = path.header
            q.pose.position.x, q.pose.position.y = x, y
            q.pose.orientation.z, q.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            path.poses.append(q)
        goal = FollowPath.Goal(path=path, controller_id='FollowPath', goal_checker_id='general_goal_checker',
                               progress_checker_id='progress_checker')

        def wait(f, sec):
            t = time.time() + sec
            while not f.done() and time.time() < t:
                self.rclpy.spin_once(n, timeout_sec=0.02)
            return f.done()
        fs = self.fp.send_goal_async(goal)
        if not wait(fs, 10) or not fs.result().accepted:
            return 'nav_rejected', {}
        gh = fs.result()
        fr = gh.get_result_async()
        L = math.dist(p0, p1) / 100
        if not wait(fr, timeout or L / 0.03 + 30):
            wait(gh.cancel_goal_async(), 5); self.dr.stop()
            return 'timeout', {}
        r = fr.result()
        return ('ok' if r.status == 4 else 'nav_fail'), dict(action_status=r.status, error_code=r.result.error_code)

    def straight(self, cm, v=0.02):
        """방향 유지하고 odom 으로 cm 만큼 천천히 직진 (노드 위에 올리기용)"""
        n = self.dr.n
        o0 = n.odom; yaw0 = o0[2]
        t_end = time.time() + abs(cm) / 100 / v + 5
        while time.time() < t_end:
            self.rclpy.spin_once(n, timeout_sec=0.02)
            d = math.hypot(n.odom[0] - o0[0], n.odom[1] - o0[1])
            if d >= abs(cm) / 100:
                self.dr.stop(); return 'ok'
            err = math.atan2(math.sin(n.odom[2] - yaw0), math.cos(n.odom[2] - yaw0))
            n.cmd(v, -2.0 * err)
        self.dr.stop(); return 'timeout'

    def close(self):
        self.dr.stop()
        self.dr.n.destroy_node()
        self.rclpy.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='지금 로봇이 서 있는 노드')
    ap.add_argument('--nodes', help='이 정규식에 맞는 노드끼리의 엣지를 모두 덮는 경로')
    ap.add_argument('--route', help='노드 순서 (쉼표), start 다음부터')
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--nav2', action='store_true', help='nav 엣지를 Nav2 FollowPath 로 (기본: AMCL 축선 직진)')
    ap.add_argument('--skip', default='', help='쓰지 않을 엣지 (쉼표, a-b 양방향). 예: L70-R90')
    ap.add_argument('--new-only', action='store_true', help='graph/edge_times.yaml 에 이미 있는 엣지는 재지 않음 (지나가는 길로만 씀)')
    ap.add_argument('--done-log', nargs='*', default=[], help='이 edges_*.csv 에서 ok 로 잰 엣지는 뺌 (끊긴 한 바퀴 이어 돌기)')
    ap.add_argument('--min-n', type=int, default=0, help='edge_times.yaml 기준 측정 횟수가 이보다 적은 엣지만 모자란 만큼 더 잼')
    ap.add_argument('--heading', type=float, help='지금 로봇 방향 deg (경로 짤 때 첫 회전 줄이기)')
    ap.add_argument('--pre', nargs='*', default=[], help='측정 전 lane_drive 단계 (예: transfer:22.5)')
    ap.add_argument('--go', action='store_true', help='실제 주행 (없으면 경로만 출력)')
    ap.add_argument('--batt-stop', type=float, default=BATT_STOP, help='배터리 전압 1분 중앙값 %% 가 이 이하면 저장하고 멈춤')
    a = ap.parse_args()
    N, E = load_graph()
    for ab in filter(None, a.skip.split(',')):
        x, y = ab.split('-')
        E.pop((x, y), None); E.pop((y, x), None)
    if a.start not in N:
        raise SystemExit(f'모르는 노드 {a.start}')
    if a.route:
        route = [a.start] + a.route.split(',')
    elif a.nodes:
        keep = {n for n in N if re.search(a.nodes, n)} | {a.start}
        done = {}
        for fn in a.done_log:          # 이 기록들에서 ok 로 잰 엣지는 이미 한 것으로 (끊긴 한 바퀴 이어 돌기)
            import csv
            for r in csv.DictReader(open(fn)):
                if r['status'] == 'ok':
                    done[(r['a'], r['b'])] = done.get((r['a'], r['b']), 0) + 1
        if (a.new_only or a.min_n) and os.path.exists(TIMES):
            done = {(v['a'], v['b']): v.get('n', 1) for v in (yaml.safe_load(open(TIMES)).get('edges') or {}).values()}
        route = tour(N, E, a.start, keep, a.reps if not a.min_n else a.min_n, a.heading, done)
    elif a.pre:
        route = [a.start]          # 준비 단계만
    else:
        raise SystemExit('--nodes 또는 --route (또는 --pre 만)')
    moves = plan_moves(N, E, route)
    hd0 = None
    turns = 0
    for i, (x, y, mode, hd, L) in enumerate(moves, 1):
        t = 0 if hd0 is None else abs((hd - hd0 + 180) % 360 - 180)
        turns += t > 1
        print(f'{i:3d}  {x:8s} → {y:8s} {mode:8s} {hd:5.1f}°  {L:5.1f} cm' + (f'  (회전 {t:.0f}°)' if t > 1 else ''))
        hd0 = hd
    print(f'엣지 {len(moves)}개, 거리 {sum(m[4] for m in moves):.0f} cm, 꺾임 {turns}번')
    if not a.go:
        return 0

    run = Runner(N, E)
    run.use_nav2 = a.nav2
    stop = {'now': False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    os.makedirs(os.path.join(HERE, 'edge_logs'), exist_ok=True)
    path = os.path.join(HERE, 'edge_logs', time.strftime('edges_%m%d_%H%M%S.csv'))
    f = open(path, 'w')
    f.write('i,a,b,mode,heading,len_cm,rot_deg,rot_s,move_s,status,end_x,end_y,end_th,err_cm,extra\n')
    ft = open(path.replace('.csv', '_ir.csv'), 'w')   # 테이프 따라가기 중 IR (엣지 번호별)
    ft.write('i,t,remain_cm,ir_l,ir_c,ir_r,w_l,w_c,w_r,tape_y_cm\n')
    rc = 0
    try:
        for s in a.pre:
            p = s.split(':')
            st = (run.dr.transfer(float(p[1])) if p[0] == 'transfer' else run.dr.rotate(float(p[1])) if p[0] == 'rotate'
                  else run.straight(float(p[1])) if p[0] == 'straight' else 'unknown')
            run.dr.spin(0.3)
            print(f'준비 {s}: {st}  라이다 ({run.lidar_pose()[0]:.1f}, {run.lidar_pose()[1]:.1f}) {run.lidar_pose()[2]:.1f}°')
            if st != 'ok':
                return 2
        import line_follow
        print(f'IR 보정: {line_follow.CAL_SRC}  흰색 {[round(v) for v in line_follow.WHITE]} 바닥 {[round(v) for v in line_follow.FLOOR]}')
        x, y, th = run.lidar_pose()
        sx, sy = N[a.start]['xy']
        print(f'시작 {a.start}: 라이다 ({x:.1f}, {y:.1f}) {th:.1f}°  노드와 {math.hypot(x - sx, y - sy):.1f} cm')
        for i, (na, nb, mode, hd, L) in enumerate(moves, 1):
            if stop['now']:
                print('SIGTERM → 멈춤'); rc = 3; break
            bat = run.battery() if a.batt_stop is not None else None
            if bat is not None and bat <= a.batt_stop:
                print(f'배터리 전압 1분 중앙값 {bat:.1f}% ≤ {a.batt_stop:.0f}% → 저장하고 멈춤'); rc = 4; break
            th0 = run.lidar_pose()[2]
            rot = (hd - th0 + 180) % 360 - 180
            t0 = time.time()
            st = run.dr.rotate(hd) if abs(rot) > 1.5 else 'ok'
            t1 = time.time()
            extra = {}
            run.dr.trace = []
            if st == 'ok':
                st, extra = run.move(na, nb, mode, round(hd) % 360)
            t2 = time.time()
            for r in run.dr.trace:
                ft.write(f'{i},' + ','.join('' if v is None else str(v) for v in r) + '\n')
            ft.flush()
            run.dr.spin(0.3)
            x, y, th = run.lidar_pose()
            bx, by = N[nb]['xy']
            err = math.hypot(x - bx, y - by)
            ex = ';'.join(f'{k}={v}' for k, v in extra.items())
            f.write(f'{i},{na},{nb},{mode},{hd:.1f},{L:.1f},{rot:.1f},{t1 - t0:.2f},{t2 - t1:.2f},{st},'
                    f'{x:.1f},{y:.1f},{th:.1f},{err:.1f},{ex}\n'); f.flush()
            print(f'{i:3d}  {na:8s} → {nb:8s} {mode:8s} 회전 {rot:+6.1f}° {t1 - t0:5.1f}s  이동 {L:5.1f}cm {t2 - t1:5.1f}s  '
                  f'{st:8s} 끝 ({x:.1f}, {y:.1f}) {th:.0f}° 노드와 {err:.1f}cm {ex}'
                  + ('' if bat is None else f'  배터리 {bat:.0f}%'), flush=True)
            if st != 'ok':
                rc = 2; break
    except KeyboardInterrupt:
        print('Ctrl+C → 멈춤'); rc = 1
    finally:
        run.close()
        f.close(); ft.close()
        print(f'저장: {path}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
