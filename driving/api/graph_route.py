# 주행 그래프(graph/graph.yaml)에서 지금 자리 → 목적지 경로를 찾아 주행 구간(segment) 목록으로 바꾼다. ROS 없이 돈다.
# 좌표는 그림 cm (왼쪽 아래 원점, y 위), 위치 = **라이다 중심**, 방향 deg (0 = +x, 90 = +y).
#   python3 graph_route.py 182.7,24,180 PHARMACY          # 경로 출력 (출발 x,y,heading → 목적지 이름)
#   python3 graph_route.py 182.7,24,180 105,52            # 목적지 x,y (heading 은 x,y,h 로)
# 2026-10-22 사용자 결정: 라인트레이싱 전까지 교행 복도는 **복도 가운데**(차선 두 줄의 가운데: 아래 y=15, 위 y=145)를 Nav2 로 달린다.
#   → 같은 복도의 차선 노드(B1_130, B2_130)를 복도 가운데 노드 B_130 하나로 합치고, line/transfer 엣지는 Nav2 로 달린다.
# 구간 mode: nav = Nav2 FollowPath (30° 넘게 꺾이는 곳에서 나눔), wall = 협로 벽 따라가기 (corridor_drive.py), dock = 카메라 정밀 주차
import heapq
import math
import os
import sys

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GRAPH = os.path.join(ROOT, 'graph', 'graph.yaml')
SPEC = os.path.join(ROOT, 'graph', 'graph_spec.yaml')
sys.path.insert(0, os.path.join(ROOT, 'tools'))

BODY_R = 5.5          # cm, 몸체 Ø11 (그릇 없이)
LEG_MIN_GAP = 1.0     # cm, 그래프 밖 직선 구간(출발 → 그래프, 그래프 → 목적지)의 실제 벽 여유 최소. 그림의 벽(문 포함)도 못 가로지름
LEG_MAX_LEN = 40.0    # cm, 그 직선 구간 최대 길이 (복도 폭 30 남짓: 멀리 가로지르지 말고 그래프를 타게)
ON_EDGE_CM = 5.0      # cm, 이만큼 안이면 '엣지 위에 있다'로 보고 그 엣지를 따라 들어감 (10-22: 3 → 5, 협로 입구에서 4cm 비켜 선 경우도 벽 따라가기로)
LEG_NODE_TYPES = ('center', 'stop')   # 그래프 밖 직선은 복도 가운데·목적지로만. 협로·문 경계점(gate)·협로 안 경유점(way)으로 비스듬히 바로 들어가면
                                      # 좁은 입구에서 Nav2 충돌 검사에 걸림 (10-22 위 복도 → GT130D 대각선으로 협로 입구에서 멈춤)
SAME_CM = 2.0         # cm, 이만큼 안이면 같은 점
TURN_SPLIT_DEG = 30   # nav 경로가 이보다 크게 꺾이면 FollowPath 를 나눠 보냄 (모서리 깎기 방지, 제자리 회전 먼저)
COLLINEAR_DEG = 5     # wall 구간 앞뒤로 같은 축의 nav 다리(복도 가운데 ↔ 경계점)를 벽 따라가기에 붙임 (10-22 S2 와 같은 방식)

_dmap = None
_dwalls = None


def diagram_walls():
    """그림의 벽 선분 (tools/diagram_walls.yaml, 문 포함 전체 길이). 실제로는 안 세운 방 벽도 있어서 그래프 밖 직선은 이걸로도 막는다"""
    global _dwalls
    if _dwalls is None:
        W = yaml.safe_load(open(os.path.join(ROOT, 'tools', 'diagram_walls.yaml')))
        _dwalls = [tuple(map(float, w)) for g in W.values() for w in g]
    return _dwalls


def crosses_diagram_wall(p, q, eps=0.5):
    """p→q 직선이 그림의 벽 선분과 만나면 True. 벽 모서리(끝점)를 스치는 것도 막고, p·q 자체가 벽에 eps cm 안으로 닿는 것만 봐준다"""
    L = math.dist(p, q)
    if L < 1e-6:
        return False
    rx, ry = q[0] - p[0], q[1] - p[1]
    for x1, y1, x2, y2 in diagram_walls():
        sx, sy = x2 - x1, y2 - y1
        den = rx * sy - ry * sx
        if abs(den) < 1e-9:      # 평행
            continue
        t = ((x1 - p[0]) * sy - (y1 - p[1]) * sx) / den
        u = ((x1 - p[0]) * ry - (y1 - p[1]) * rx) / den
        W = math.hypot(sx, sy)
        if eps / L < t < 1 - eps / L and -eps / W <= u <= 1 + eps / W:
            return True
    return False


def wall_dist_cm(P):
    """점들(cm) → 가장 가까운 벽까지 거리 cm (map_drawn + 바닥 패널, build_graph.body_gap 과 같은 기준)"""
    global _dmap
    if _dmap is None:
        _argv = sys.argv; sys.argv = [sys.argv[0]]
        import scan_fit as sf  # map_drawn 거리 지도 (불러올 때 sys.argv 를 파일 목록으로 읽음)
        sys.argv = _argv
        _dmap = sf.dmap
    P = np.asarray(P, float)
    return np.minimum(_dmap(P / 100) * 100, P[:, 1] - 0.0)


def seg_gap(p, q, step=0.5):
    n = max(1, int(math.dist(p, q) / step))
    P = [(p[0] + (q[0] - p[0]) * t / n, p[1] + (q[1] - p[1]) * t / n) for t in range(n + 1)]
    return float(wall_dist_cm(P).min()) - BODY_R


def heading_of(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def angdiff(a, b):
    return (a - b + 180) % 360 - 180


class Graph:
    def __init__(self, graph_path=GRAPH, spec_path=SPEC):
        g = yaml.safe_load(open(graph_path))
        lanes = yaml.safe_load(open(spec_path))['lanes']
        cy = {}
        for L in lanes.values():
            cy.setdefault(L['corridor'], []).append(L['y'])
        self.corridor_y = {c: sum(v) / len(v) for c, v in cy.items()}     # B: 15, T: 145
        lane_corr = {k: v['corridor'] for k, v in lanes.items()}
        self.nodes, self.alias = {}, {}
        for k, n in g['nodes'].items():
            if n.get('deferred') or n.get('type') == 'dock':   # 정밀 주차 자리는 /drive 전용 (/goto 는 dock 구간으로 따로)
                continue
            if n.get('type') == 'lane':        # 차선 노드 → 복도 가운데 노드
                c = lane_corr[n['lane']]; x = n['xy'][0]
                key = f'{c}_{x:g}'
                self.alias[k] = key
                self.nodes.setdefault(key, dict(xy=[x, self.corridor_y[c]], type='center', corridor=c))
            else:
                self.alias[k] = k
                self.nodes[k] = dict(n)
        self.adj = {k: {} for k in self.nodes}
        for e in g['edges']:
            if e.get('deferred') or e['a'] not in self.alias or e['b'] not in self.alias:
                continue
            a, b = self.alias[e['a']], self.alias[e['b']]
            if a == b:   # 같은 갈림목의 차선끼리 (합치면 같은 점)
                continue
            mode = 'wall' if e['mode'] == 'wall' else 'nav'
            info = dict(mode=mode, src_mode=e['mode'], zone=e.get('zone'), wall=e.get('wall'), wall2=e.get('wall2'))
            L = math.dist(self.nodes[a]['xy'], self.nodes[b]['xy'])
            if b not in self.adj[a] or self.adj[a][b][0] > L:   # 차선 둘이 합쳐져 겹친 엣지는 하나만
                self.adj[a][b] = (L, info); self.adj[b][a] = (L, info)
        self.edges = [(a, b, L, info) for a in self.adj for b, (L, info) in self.adj[a].items() if a < b]

    def stops(self):
        return {k: n for k, n in self.nodes.items() if n.get('type') == 'stop'}

    def xy(self, k):
        return tuple(self.nodes[k]['xy'])

    # --- 그래프 밖 점(출발·목적지)을 그래프에 붙이는 후보 -------------------------------------------------
    def attach(self, p, k=4):
        """반환 [(노드, 비용 cm, 다리 dict)] — 엣지 위면 그 엣지 양 끝으로 엣지 mode 그대로, 아니면 벽 안 막힌 가까운 노드로 직선 nav"""
        out = []
        for a, b, L, info in self.edges:
            pa, pb = self.xy(a), self.xy(b)
            ux, uy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
            t = (p[0] - pa[0]) * ux + (p[1] - pa[1]) * uy
            d = abs(-(p[0] - pa[0]) * uy + (p[1] - pa[1]) * ux)
            if d < ON_EDGE_CM and SAME_CM < t < L - SAME_CM:
                out.append((a, t, dict(info, edge=(a, b))))
                out.append((b, L - t, dict(info, edge=(a, b))))
        if out:   # 엣지 위면 그 엣지로만 (협로 안에서 Nav2 직선 다리를 만들지 않게)
            return out
        cands = sorted(self.nodes, key=lambda n: math.dist(p, self.xy(n)))
        for n in cands:
            d = math.dist(p, self.xy(n))
            if d > LEG_MAX_LEN or len([o for o in out if o[2].get('leg')]) >= k:
                break
            if d < SAME_CM:
                out.append((n, 0.0, dict(mode='nav', leg=True, same=True))); continue
            if self.nodes[n]['type'] not in LEG_NODE_TYPES:
                continue
            if crosses_diagram_wall(p, self.xy(n)):
                continue
            gap = seg_gap(p, self.xy(n))
            if gap >= LEG_MIN_GAP:
                out.append((n, d, dict(mode='nav', leg=True, gap=round(gap, 1))))
        return out

    def dijkstra(self, src):
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, (L, _) in self.adj[u].items():
                if d + L < dist.get(v, 1e18):
                    dist[v] = d + L; prev[v] = u; heapq.heappush(pq, (d + L, v))
        return dist, prev

    def resolve_goal(self, goal):
        """goal: 노드 이름(stop 이름 START_A·PHARMACY, 차선 노드 B2_130 도) 또는 (x, y[, heading]). 반환 (xy, heading|None, 노드|None)"""
        if isinstance(goal, str):
            for k in (goal, goal.upper()):
                if k in self.alias:
                    n = self.nodes[self.alias[k]]
                    return tuple(n['xy']), n.get('heading'), self.alias[k]
            raise ValueError(f'그래프에 "{goal}" 없음. 목적지: {", ".join(self.stops())}')
        return (float(goal[0]), float(goal[1])), (float(goal[2]) if len(goal) > 2 and goal[2] is not None else None), None

    def plan(self, start, goal, dock=False):
        """start: (x, y, heading) 라이다 중심. 반환 dict(points, segments, nodes, length_cm, goal)"""
        s = (float(start[0]), float(start[1]))
        gxy, gh, gnode = self.resolve_goal(goal)
        if math.dist(s, gxy) < SAME_CM:
            segs = []
            if gh is not None and abs(angdiff(gh, start[2])) > 3:
                segs.append(dict(mode='rotate', heading=gh))
            return self._finish(segs, [s], [], 0.0, gxy, gh, gnode, dock)
        starts = self.attach(s)
        if not starts:
            raise ValueError(f'출발점 {s} 를 그래프에 붙일 수 없음 (벽에 안 막힌 노드가 {LEG_MAX_LEN:g}cm 안에 없음)')
        ends = [(gnode, 0.0, None)] if gnode else self.attach(gxy)
        if not ends:
            raise ValueError(f'목적지 {gxy} 를 그래프에 붙일 수 없음')
        best = None
        for n0, c0, leg0 in starts:
            dist, prev = self.dijkstra(n0)
            for n1, c1, leg1 in ends:
                if n1 not in dist:
                    continue
                c = c0 + dist[n1] + c1
                if best is None or c < best[0]:
                    best = (c, n0, leg0, n1, leg1, prev)
        if best is None:
            raise ValueError('출발점과 목적지가 그래프에서 이어지지 않음')
        c, n0, leg0, n1, leg1, prev = best
        path = [n1]
        while path[-1] != n0:
            path.append(prev[path[-1]])
        path.reverse()
        # 꼭짓점과 꼭짓점 사이 다리(mode 정보)
        pts, legs = [s], []
        if math.dist(s, self.xy(n0)) >= SAME_CM:
            pts.append(self.xy(n0)); legs.append(leg0)
        for a, b in zip(path, path[1:]):
            pts.append(self.xy(b)); legs.append(self.adj[a][b][1])
        if gnode is None and math.dist(pts[-1], gxy) >= SAME_CM:
            pts.append(gxy); legs.append(leg1)
        return self._finish(self._segments(pts, legs), pts, path, c, gxy, gh, gnode, dock)

    def _finish(self, segs, pts, path, c, gxy, gh, gnode, dock):
        # 각 구간 끝 방향 = 다음 구간 시작 방향, 마지막 = 목적지 방향(없으면 진행 방향)
        for i, sg in enumerate(segs):
            if sg['mode'] == 'rotate':
                continue
            nxt = next((t for t in segs[i + 1:] if t['mode'] in ('nav', 'wall')), None)
            if nxt is not None:
                sg['final_heading'] = round(heading_of(nxt['points'][0], nxt['points'][1]), 1)
            else:
                p = sg['points']
                sg['final_heading'] = round(gh if gh is not None else heading_of(p[-2], p[-1]), 1)
        if dock:
            if gnode is None or not self.nodes[gnode].get('dock'):
                raise ValueError(f'dock 은 dock 표시가 있는 목적지에서만 (예: PHARMACY). 지금 목적지: {gnode or gxy}')
            segs.append(dict(mode='dock', kind=self.nodes[gnode]['dock']))
        return dict(goal=dict(xy=[round(v, 1) for v in gxy], heading=gh, node=gnode),
                    nodes=path, points=[[round(v, 1) for v in p] for p in pts], length_cm=round(c, 1), segments=segs)

    def _segments(self, pts, legs):
        """다리마다 mode → 같은 mode 끼리 묶어 구간으로. wall 구간 앞뒤의 같은 축 nav 다리는 벽 따라가기에 붙인다"""
        kinds = [lg['mode'] for lg in legs]
        hd = [heading_of(pts[i], pts[i + 1]) for i in range(len(legs))]
        for i, lg in enumerate(legs):   # 엣지 위에서 출발·도착하는 다리는 엣지 방향으로 본다 (축에서 몇 cm 비켜 있어도 협로 벽 따라가기에 붙게)
            if lg.get('edge'):
                ea, eb = (self.xy(n) for n in lg['edge'])
                hd[i] = heading_of(ea, eb) if math.dist(pts[i + 1], eb) < math.dist(pts[i + 1], ea) else heading_of(eb, ea)
        for i, k in enumerate(kinds):     # wall 앞뒤 같은 축 nav 다리 → wall (복도 가운데 ↔ 협로 경계점)
            if k != 'wall':
                continue
            j = i - 1
            while j >= 0 and kinds[j] == 'nav' and legs[j].get('src_mode') == 'transfer' and abs(angdiff(hd[j], hd[i])) < COLLINEAR_DEG:
                kinds[j] = 'wall'; legs[j] = dict(legs[j], wall=legs[i].get('wall'), wall2=legs[i].get('wall2')); j -= 1
            j = i + 1
            while j < len(kinds) and kinds[j] == 'nav' and legs[j].get('src_mode') == 'transfer' and abs(angdiff(hd[j], hd[i])) < COLLINEAR_DEG:
                kinds[j] = 'wall'; legs[j] = dict(legs[j], wall=legs[i].get('wall'), wall2=legs[i].get('wall2')); j += 1
        segs = []
        for i, k in enumerate(kinds):
            new = (not segs or segs[-1]['mode'] != k or
                   (k == 'nav' and abs(angdiff(hd[i], hd[i - 1])) > TURN_SPLIT_DEG) or
                   (k == 'wall' and abs(angdiff(hd[i], hd[i - 1])) > COLLINEAR_DEG))
            if new:
                segs.append(dict(mode=k, points=[pts[i]], legs=[]))
            segs[-1]['points'].append(pts[i + 1])
            segs[-1]['legs'].append(legs[i])
        for sg in segs:
            sg['points'] = [[round(v, 1) for v in p] for p in sg['points']]
            if sg['mode'] == 'wall':
                sg.update(wall_side(sg['points'][0], sg['points'][-1], sg['legs']))
            sg['zones'] = sorted({lg.get('zone') for lg in sg['legs'] if lg.get('zone')})
            del sg['legs']
        return segs


def wall_side(p0, p1, legs):
    """벽 따라가기 구간: 벽 선분(엣지의 wall/wall2) 이 진행 방향 어느 쪽인지와 축선에서 벽까지 거리"""
    L = math.dist(p0, p1); ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    best = None
    for lg in legs:
        for w in (lg.get('wall'), lg.get('wall2')):
            if not w:
                continue
            for q in w:
                c = ux * (q[1] - p0[1]) - uy * (q[0] - p0[0])   # 진행 방향 왼쪽 +
                if best is None or abs(c) < abs(best):
                    best = c
    if best is None:
        raise ValueError(f'벽 따라가기 구간 {p0}→{p1} 에 wall 정보가 없음')
    return dict(side='left' if best > 0 else 'right', offset=round(abs(best), 1))


def main():
    import json
    if len(sys.argv) < 3:
        print(__doc__ or open(__file__).read().split('\nimport')[0]); return 1
    st = [float(v) for v in sys.argv[1].split(',')]
    goal = sys.argv[2]
    goal = [float(v) for v in goal.split(',')] if goal[0].isdigit() or goal[0] == '-' else goal
    r = Graph().plan(st, goal, dock='--dock' in sys.argv)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
