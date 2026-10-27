# 주행 그래프 엣지 시간 측정: 엣지를 하나씩 실제 주행 방식으로 달리며 (회전 시간, 이동 시간)을 따로 잰다 → FMS 엣지 비용.
# **로봇에서** 실행 (IR 노드 pinky_sensor_adc 가 /ir_sensor/range 를 내고 있어야 함). 로봇이 움직임!
#   python3 edge_run.py --start B2_130 --nodes '^B[12]_'                 # 경로만 출력 (움직이지 않음)
#   python3 edge_run.py --start B2_130 --nodes '^B[12]_' --go            # 영역 안 모든 방향 엣지를 한 번씩 덮는 경로로 주행
#   python3 edge_run.py --start B2_130 --route B2_180,B1_180 --go        # 정해 준 노드 순서대로
#   --pre transfer:22.5   측정 전에 lane_drive 단계 먼저 (노드 위에 올려놓기). --reps 2  엣지마다 두 번씩
# 엣지마다: ① 제자리 회전 (엣지 방향으로) ② 이동. 이동 방식은 graph.yaml 엣지 mode 를 따른다
#   line     = 테이프 따라가기 (b 의 x/y 에 라이다 중심이 닿을 때까지)
#   transfer = 차선 → 차선 / 협로 입구 → 차선: 직진하다 IR 로 새 테이프를 찾으면 바퀴 축이 테이프 위에서 멈춤
#              차선 → 협로 입구: 벽 따라가기 (corridor_drive, 벽이 안 보이면 AMCL 축선)
#   wall     = 협로 벽 따라가기 (오른쪽 협로는 늘 x=140 벽: 올라갈 때 right, 내려갈 때 left)
#   nav      = 아직 안 함 (Nav2 FollowPath)
# 노드마다 멈춘다 (회전 + 이동을 따로 재려고). 결과: edge_logs/edges_<시각>.csv — 한 줄씩 바로 씀 (중간에 멈춰도 남음)
import argparse
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
WALL_SIDE = {'narrow_right': {90: ('right', 10.0), 270: ('left', 10.0)}}   # zone → 진행 방향별 (벽 쪽, 축선-벽 cm)


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


def tour(N, E, start, keep, reps=1, hd=None):
    """keep 노드끼리의 모든 방향 엣지를 reps 번씩 지나는 경로 (욕심쟁이: 가장 가까운 안 지난 엣지로). hd = 지금 방향 (회전 줄이기)"""
    adj = {}
    for (a, b) in E:
        if a in keep and b in keep:
            adj.setdefault(a, []).append(b)
    need = {(a, b): reps for a in adj for b in adj[a]}

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
    def __init__(self, N):
        import rclpy
        from corridor_drive import CorridorDrive
        from lane_drive import LIDAR_BEHIND_AXLE, Driver
        self.rclpy, self.N, self.LB = rclpy, N, LIDAR_BEHIND_AXLE
        rclpy.init()
        self.dr = Driver()
        self.CorridorDrive = CorridorDrive

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
        if mode in ('transfer', 'wall'):
            zone = E_ZONE.get((a, b)) or ''
            side, off = WALL_SIDE.get(zone, {}).get(hd, ('right', 10.0))
            cd = self.CorridorDrive(self.dr.n, side, off, SPEED, tf_buffer=self.dr.n.tfb, body_r=BODY_R)
            r = cd.run(N[a]['xy'], N[b]['xy'])
            return r.pop('status'), r
        return f'mode_{mode}_todo', {}

    def close(self):
        self.dr.stop()
        self.dr.n.destroy_node()
        self.rclpy.shutdown()


E_ZONE = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='지금 로봇이 서 있는 노드')
    ap.add_argument('--nodes', help='이 정규식에 맞는 노드끼리의 엣지를 모두 덮는 경로')
    ap.add_argument('--route', help='노드 순서 (쉼표), start 다음부터')
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--heading', type=float, help='지금 로봇 방향 deg (경로 짤 때 첫 회전 줄이기)')
    ap.add_argument('--pre', nargs='*', default=[], help='측정 전 lane_drive 단계 (예: transfer:22.5)')
    ap.add_argument('--go', action='store_true', help='실제 주행 (없으면 경로만 출력)')
    a = ap.parse_args()
    N, E = load_graph()
    for (x, y), e in E.items():
        E_ZONE[(x, y)] = e.get('zone')
    if a.start not in N:
        raise SystemExit(f'모르는 노드 {a.start}')
    if a.route:
        route = [a.start] + a.route.split(',')
    elif a.nodes:
        keep = {n for n in N if re.search(a.nodes, n)} | {a.start}
        route = tour(N, E, a.start, keep, a.reps, a.heading)
    else:
        raise SystemExit('--nodes 또는 --route')
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

    run = Runner(N)
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
            st = run.dr.transfer(float(p[1])) if p[0] == 'transfer' else run.dr.rotate(float(p[1])) if p[0] == 'rotate' else 'unknown'
            run.dr.spin(0.3)
            print(f'준비 {s}: {st}  라이다 ({run.lidar_pose()[0]:.1f}, {run.lidar_pose()[1]:.1f}) {run.lidar_pose()[2]:.1f}°')
            if st != 'ok':
                return 2
        x, y, th = run.lidar_pose()
        sx, sy = N[a.start]['xy']
        print(f'시작 {a.start}: 라이다 ({x:.1f}, {y:.1f}) {th:.1f}°  노드와 {math.hypot(x - sx, y - sy):.1f} cm')
        for i, (na, nb, mode, hd, L) in enumerate(moves, 1):
            if stop['now']:
                print('SIGTERM → 멈춤'); rc = 3; break
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
                  f'{st:8s} 끝 ({x:.1f}, {y:.1f}) {th:.0f}° 노드와 {err:.1f}cm {ex}', flush=True)
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
