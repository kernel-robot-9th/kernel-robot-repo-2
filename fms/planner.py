"""경로 계획: 시공간 A* (로봇 하나) + CBS (여러 대 충돌 해소).

시간 = 정수 칸 (STEP 초). 엣지 지나는 시간 = ceil(길이 / 속도 / STEP).
로봇이 차지하는 것 = Item: 노드에 머묾 [t0, t1] 또는 엣지 지남 [t0, t1].
두 Item 이 시간이 겹치고 자리가 부딪히면 충돌 (fms_core 의 예약 규칙과 같은 기준):
  - 같은 노드, NEAR_CM 안의 노드, 엣지가 가까이 지나가는 노드, 같은 엣지·끝점 공유
  - 같은 1대 zone (협로·계단 통로·갈림목·병실·약제실·POCKET·충전기)
  - 둘 다 약을 실었고 같은 교행통로의 다른 차선에서 x 범위가 NEAR_CM 안으로 겹침
CBS: 충돌이 나면 두 갈래로 나눠 한쪽 로봇에게 "그 시간에 그 자리 피하기" 제약을 준다.
    시간·노드 한도를 넘으면 우선순위 계획(먼저 정한 로봇의 자리를 뒤 로봇이 피함)으로 내려간다.
"""
import heapq
import itertools
import math
import time

INF = 10 ** 9


class Item:
    __slots__ = ('kind', 'key', 't0', 't1', 'zones', 'lane', 'x0', 'x1', 'loaded', 'agent', 'fixed')

    def __init__(self, g, kind, key, t0, t1, loaded, agent, fixed=False, zones=None):
        self.kind, self.key, self.t0, self.t1 = kind, key, t0, t1
        self.loaded, self.agent, self.fixed = loaded, agent, fixed
        if kind == 'node':
            self.zones = set(zones) if zones is not None else g.stop_zones(key)
            self.lane = g.nodes[key].get('lane')
            self.x0 = self.x1 = g.xy(key)[0]
        else:
            e = g.edge[key]
            self.zones = {e['zone']} if g.cap1(e['zone']) else set()
            self.lane = e['lane']
            self.x0, self.x1 = g.x_range(*key)

    def __repr__(self):
        return f'{self.agent}:{self.kind}:{self.key}[{self.t0},{self.t1}]'


def space_conflict(g, X, Y, near_cm):
    if X.zones & Y.zones:
        return True
    if X.kind == 'node' and Y.kind == 'node':
        if X.key == Y.key or Y.key in g.near[X.key]:
            return True
    elif X.kind == 'node' or Y.kind == 'node':
        n, e = (X.key, Y.key) if X.kind == 'node' else (Y.key, X.key)
        if n in e or n in g.seg_near[e]:
            return True
    else:
        a, b = X.key
        c, d = Y.key
        if {a, b} & {c, d} or {a, b} & g.seg_near[Y.key] or {c, d} & g.seg_near[X.key]:
            return True
    if X.loaded and Y.loaded and X.lane and Y.lane and X.lane != Y.lane and X.lane[0] == Y.lane[0]:
        if min(X.x1, Y.x1) - max(X.x0, Y.x0) > -near_cm:
            return True
    return False


def overlap(X, Y):
    return X.t0 <= Y.t1 and Y.t0 <= X.t1


class Planner:
    def __init__(self, g, speed, step=1.0, near_cm=14.5, wrong_lane=1.5, horizon=400,
                 cbs_nodes=150, cbs_expand=15000):
        self.g, self.speed, self.step, self.near_cm = g, speed, step, near_cm
        self.wrong_lane, self.horizon = wrong_lane, horizon
        self.cbs_nodes, self.cbs_expand = cbs_nodes, cbs_expand   # CBS 한도: 노드 수, A* 펼침 수 (시계 대신 → 같은 입력이면 같은 결과)
        self.expanded = 0
        # 엣지 시간 칸: 실측 중앙값 (graph/edge_times.yaml, 방향별), 없으면 길이 ÷ speed
        self.dur = {e: max(1, math.ceil(g.edge_s(*e, speed) / step)) for e in g.edge}
        self._h = {}
        self.last = {}

    def turn(self, h0, h1):
        """제자리 회전 시간 칸 (실측 식). h0 None(모름) 이면 0"""
        s = self.g.rot_s(h0, h1)
        return 0 if s <= 0 else max(1, math.ceil(s / self.step))

    # ---- 휴리스틱: 목표까지 가장 짧은 시간 칸 ----
    def h_table(self, goal):
        if goal not in self._h:
            dist, pq = {goal: 0}, [(0, goal)]
            while pq:
                d, u = heapq.heappop(pq)
                if d > dist[u]:
                    continue
                for v in self.g.adj[u]:
                    c = d + self.dur[(v, u)]
                    if c < dist.get(v, INF):
                        dist[v] = c
                        heapq.heappush(pq, (c, v))
            self._h[goal] = dist
        return self._h[goal]

    def penalty(self, a, b):
        e = self.g.edge[(a, b)]
        if not e['lane']:
            return 0.0
        east = self.g.xy(b)[0] > self.g.xy(a)[0]
        right = (e['lane'] in ('B1', 'T1')) == east
        return 0.0 if right else (self.wrong_lane - 1.0) * self.dur[(a, b)]

    # ---- 시공간 A* (여러 목적지: 목적지마다 머무는 시간) ----
    def astar(self, agent, start, t0, legs, cons, h0=None):
        """legs: [(목적지, 머무는 칸, 그 구간 동안 약 실음)] — 마지막 목적지의 머무는 칸이 INF 면 계속 거기 있음,
        유한하면 그만큼 머문 뒤 계획 끝 (그 뒤는 다시 출발할 때 새로 계획).
        목적지 i 에 닿으면 그 자리에서 머무는 칸만큼 반드시 머문 뒤 목적지 i+1 로.
        cons: 피해야 할 Item 목록. h0: 시작 방향 deg (회전 비용, None = 모름 → 첫 회전 0).
        상태 = (노드, t, 구간, 방향). 엣지를 타려면 먼저 그 엣지 방향으로 제자리 회전 (실측 회전 시간, 그동안 노드 점유).
        반환 [(노드, 도착 t, 출발 t, 구간, 실음)] 또는 None"""
        g = self.g
        L = len(legs)
        Hs = [self.h_table(gl) for gl, _, _ in legs]
        if start not in Hs[0]:
            return None
        rest = [0] * L                      # 구간 i 목적지 다음부터 마지막 목적지까지 최소 시간
        for i in range(L - 2, -1, -1):
            nxt_goal = legs[i + 1][0]
            rest[i] = legs[i][1] + Hs[i + 1].get(legs[i][0], INF) + rest[i + 1]
            if nxt_goal == legs[i][0]:
                rest[i] = legs[i][1] + rest[i + 1]

        def h(n, i):
            return 0 if i >= L else Hs[i].get(n, INF) + rest[i]

        def blocked(it):
            for c in cons:
                if c.t1 >= it.t0 and it.t1 >= c.t0 and space_conflict(g, it, c, self.near_cm):
                    return True
            return False

        for gl, _, ld in legs:                 # 누가 끝까지 서 있는 목적지는 못 감 (A* 를 돌리기 전에 거름)
            gi = Item(g, 'node', gl, 0, INF, ld, agent)
            if any(c.t1 >= INF and space_conflict(g, gi, c, self.near_cm) for c in cons):
                return None
        last_goal, last_dwell, last_loaded = legs[-1]
        stays = last_dwell >= INF
        latest = -1
        if stays:
            goal_item = Item(g, 'node', last_goal, 0, INF, last_loaded, agent)
            for c in cons:
                if space_conflict(g, goal_item, c, self.near_cm):
                    latest = max(latest, c.t1)
            if latest >= INF:
                return None
        tick = itertools.count()
        hk = None if h0 is None else round(h0) % 360
        start_s = (start, t0, 0, hk)
        openq = [(h(start, 0), next(tick), 0.0, start_s)]
        prev = {start_s: None}
        gbest = {start_s: 0.0}
        tmax = t0 + self.horizon
        while openq:
            f, _, gc, (n, t, i, hd) = heapq.heappop(openq)
            self.expanded += 1
            if gc > gbest.get((n, t, i, hd), INF):
                continue
            if (stays and i == L - 1 and n == last_goal and t > latest) or i == L:
                out, st = [], (n, t, i, hd)
                while st is not None:
                    out.append(st[:3])
                    st = prev[st]
                return self._compress(out[::-1], legs)
            if t >= tmax:
                continue
            goal_i, dwell_i, loaded = legs[i]
            nxt = []
            if n == goal_i and (i < L - 1 or not stays):                           # 목적지: 머무는 시간 (정밀 주차·회전 등)
                ld = loaded or (legs[i + 1][2] if i + 1 < L else False)
                if not blocked(Item(g, 'node', n, t, t + dwell_i, ld, agent)):
                    nxt.append(((n, t + dwell_i, i + 1, hd), gc + dwell_i))
            else:
                if not blocked(Item(g, 'node', n, t, t + 1, loaded, agent)):     # 기다림
                    nxt.append(((n, t + 1, i, hd), gc + 1.0))
                for m in g.adj[n]:
                    he = round(g.heading(n, m)) % 360
                    r = self.turn(hd, he)
                    if r:                                                          # 먼저 그 엣지 방향으로 제자리 회전
                        if not blocked(Item(g, 'node', n, t, t + r, loaded, agent)):
                            nxt.append(((n, t + r, i, he), gc + r))
                        continue
                    d = self.dur[(n, m)]                                           # 엣지 지나기
                    if blocked(Item(g, 'edge', (n, m), t, t + d, loaded, agent)) or \
                            blocked(Item(g, 'node', m, t + d, t + d, loaded, agent)):
                        continue
                    nxt.append(((m, t + d, i, he), gc + d + self.penalty(n, m) + 0.1))   # 0.1: 괜히 돌아다니지 말고 제자리 대기
            for st, c in nxt:
                if c < gbest.get(st, INF):
                    gbest[st] = c
                    prev[st] = (n, t, i, hd)
                    heapq.heappush(openq, (c + h(st[0], st[2]), next(tick), c, st))
        return None

    @staticmethod
    def _compress(states, legs):
        """(노드, t, 구간) 칸 목록 → [(노드, 도착 t, 출발 t, 도착할 때 구간, 그동안 실음)]. 마지막은 출발 INF.
        목적지에서 머무는 동안은 그 앞뒤 구간 중 하나라도 실었으면 실음"""
        out = []
        for n, t, i in states:
            ld = legs[min(i, len(legs) - 1)][2]
            if out and out[-1][0] == n:
                out[-1][2] = t
                if i != out[-1][3]:
                    out[-1][4] = out[-1][4] or ld
            else:
                out.append([n, t, t, i, ld])
        if legs[-1][1] >= INF:
            out[-1][2] = INF                    # 계속 거기 있음 (유한하면 머문 뒤 계획 끝)
        return [tuple(x) for x in out]

    def items(self, agent, plan, prefix=()):
        g = self.g
        its = list(prefix)
        for k, (n, ta, td, _, ld) in enumerate(plan):
            its.append(Item(g, 'node', n, ta, td, ld, agent))
            if k + 1 < len(plan):
                m, tb, _, _, ld2 = plan[k + 1]
                its.append(Item(g, 'edge', (n, m), td, tb, ld2, agent))
        return its

    # ---- CBS ----
    def solve(self, agents, statics):
        """agents: [dict(id, start, t0, legs=[(목적지, 머무는 칸, 실음)...], loaded, prefix=[Item...], plan_only)]
        statics: [Item ...] (끝까지 서 있는 로봇)
        반환 {id: plan} (못 풀면 그 로봇은 빠짐), 그리고 self.last 에 통계"""
        t_start = time.time()
        self.expanded = 0
        self.last = dict(mode='cbs', nodes=0, ms=0, agents=len(agents), conflicts=0)
        if not agents:
            return {}
        A = {a['id']: a for a in agents}

        def plan_one(aid, cons):
            """안 되면 뒤 목적지(예측)를 줄여 다시: 이번 목적지까지만"""
            a = A[aid]
            legs = list(a['legs'])
            while legs:
                p = self.astar(aid, a['start'], a['t0'], legs, statics + cons, a.get('heading'))
                if p is not None:
                    return p
                if len(legs) == 1:
                    return None
                legs = legs[:-1]
                self.last['trimmed'] = self.last.get('trimmed', 0) + 1
            return None

        root_cons = {aid: [] for aid in A}
        root = {}
        for aid in A:
            p = plan_one(aid, [])
            if p is None:
                return self.prioritized(agents, statics, t_start)
            root[aid] = p
        tick = itertools.count()

        def cost(plans):
            return sum(p[-1][1] for p in plans.values())

        openq = [(cost(root), next(tick), root, root_cons)]
        while openq:
            if self.last['nodes'] >= self.cbs_nodes or self.expanded > self.cbs_expand:
                return self.prioritized(agents, statics, t_start)
            _, _, plans, cons = heapq.heappop(openq)
            self.last['nodes'] += 1
            its = {aid: self.items(aid, plans[aid], A[aid].get('prefix', ())) for aid in plans}
            c = self.first_conflict(its)
            if c is None:
                self.last['ms'] = round((time.time() - t_start) * 1000, 1)
                return plans
            self.last['conflicts'] += 1
            X, Y = c
            lo, hi = max(X.t0, Y.t0), min(X.t1, Y.t1)
            for mine, other in ((X, Y), (Y, X)):
                if mine.fixed:
                    continue                                   # 이미 지나는 중인 엣지는 못 바꾼다
                aid = mine.agent
                block = Item(self.g, other.kind, other.key, lo, hi, other.loaded, other.agent, zones=other.zones)
                nc = dict(cons)
                nc[aid] = cons[aid] + [block]
                p = plan_one(aid, nc[aid])
                if p is None:
                    continue
                np_ = dict(plans)
                np_[aid] = p
                heapq.heappush(openq, (cost(np_), next(tick), np_, nc))
        return self.prioritized(agents, statics, t_start)

    def first_conflict(self, its):
        best = None
        ids = list(its)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                for X in its[ids[i]]:
                    for Y in its[ids[j]]:
                        if overlap(X, Y) and space_conflict(self.g, X, Y, self.near_cm):
                            t = max(X.t0, Y.t0)
                            if best is None or t < best[0]:
                                best = (t, X, Y)
        return None if best is None else (best[1], best[2])

    def prioritized(self, agents, statics, t_start):
        """먼저 정한 로봇의 자리를 뒤 로봇이 피한다. 이미 엣지 위(고정)·실은 로봇·오래 기다린 로봇 먼저"""
        self.last['mode'] = 'prioritized'
        order = sorted(agents, key=lambda a: (not a.get('plan_only'), not a.get('prefix'), not a['loaded'], -a.get('wait', 0.0)))
        cons, out = list(statics), {}
        for a in order:
            cons += list(a.get('prefix', ()))
        for a in order:
            mine = [c for c in cons if c.agent != a['id']]
            legs, p = list(a['legs']), None
            while legs and p is None:
                p = self.astar(a['id'], a['start'], a['t0'], legs, mine, a.get('heading'))
                legs = legs[:-1]
            if p is None:                      # 못 풀면 그 자리에 계속 있는 것으로 (뒤 로봇이 피하게)
                cons.append(Item(self.g, 'node', a['start'], 0, INF, a['loaded'], a['id']))
                continue
            out[a['id']] = p
            cons += self.items(a['id'], p)
        self.last['ms'] = round((time.time() - t_start) * 1000, 1)
        self.last['failed'] = [a['id'] for a in agents if a['id'] not in out]
        return out
