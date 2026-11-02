"""경로 계획: 시공간 A* (로봇 하나) + CBS (여러 대 충돌 해소).

시간 = 정수 칸 (STEP 초). 엣지 지나는 시간 = ceil(길이 / 속도 / STEP).
로봇이 차지하는 것 = Item: 노드에 머묾 [t0, t1] 또는 엣지 지남 [t0, t1].
두 Item 이 시간이 겹치고 자리가 부딪히면 충돌 (fms_core 의 예약 규칙과 같은 기준):
  - 같은 노드, NEAR_CM 안의 노드, 엣지가 가까이 지나가는 노드, 같은 엣지·끝점 공유
  - 같은 1대 zone (협로·계단 통로·갈림목·병실·약제실·POCKET·충전기)
  - 둘 다 약을 실었고 같은 교행통로의 다른 차선에서 x 범위가 NEAR_CM 안으로 겹침
CBS: 충돌이 나면 두 갈래로 나눠 한쪽 로봇에게 "그 시간에 그 자리 피하기" 제약을 준다.
    ECBS (11-02, w = Planner.w): 두 단계 모두 "비용이 최솟값 × w 안인 것 중 다른 로봇과 덜 부딪히는 것 먼저".
    A* 는 다른 로봇의 지금 계획과 겹치는 수(Soft)를 세어 그 수가 적은 상태부터 펼치고, CBS 는 남은 충돌 수가 적은 갈래부터.
    w=None 이면 예전 CBS (최적).
    협로 추론 (11-02): 충돌이 1대 zone(협로·계단 통로·갈림목·약제실·병실)이면 "상대가 그 zone 에 들어가서 나올 때까지
    전체를 피하기" 로 가른다 → 협로 안에서 몇 초씩 밀려 엣지마다 다시 부딪히며 갈래가 줄줄이 느는 것을 한 번에 끝냄.
    시간·노드 한도를 넘으면 우선순위 계획(먼저 정한 로봇의 자리를 뒤 로봇이 피함)으로 내려간다.
"""
import heapq
import itertools
import math
import time
from collections import defaultdict

INF = 10 ** 9


class Item:
    __slots__ = ('kind', 'key', 't0', 't1', 'zones', 'lane', 'x0', 'x1', 'loaded', 'agent', 'fixed')

    def __init__(self, g, kind, key, t0, t1, loaded, agent, fixed=False, zones=None):
        self.kind, self.key, self.t0, self.t1 = kind, key, t0, t1
        self.loaded, self.agent, self.fixed = loaded, agent, fixed
        if kind == 'zone':                  # 자리 없이 zone 만 (협로 추론 제약)
            self.zones, self.lane, self.x0, self.x1 = set(zones), None, 0.0, 0.0
        elif kind == 'node':
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
    if X.kind == 'zone' or Y.kind == 'zone':
        return False
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


class Soft:
    """ECBS: 다른 로봇들의 지금 계획(Item)을 노드·엣지·zone 별 시간 구간으로 모아, 한 Item 과 겹치는 수를 빨리 센다.
    가까운 노드·엣지 끝점·zone 은 보고, 실은 로봇끼리 나란히 규칙 등은 뺀 근사 (펼치는 순서에만 씀, 충돌 판정은 그대로)"""
    def __init__(self, g, items, win=None):
        self.node, self.edge, self.zone = defaultdict(list), defaultdict(list), defaultdict(list)
        for it in items:
            if win is not None and it.t0 > win:
                continue
            iv = (it.t0, it.t1)
            if it.kind == 'node':
                for n in {it.key} | g.near[it.key]:
                    self.node[n].append(iv)
            elif it.kind == 'edge':
                self.edge[frozenset(it.key)].append(iv)
                for n in it.key:
                    self.node[n].append(iv)
            for z in it.zones:
                self.zone[z].append(iv)

    def count(self, it):
        ls = [self.node.get(it.key, ())] if it.kind == 'node' else [self.edge.get(frozenset(it.key), ()), self.node.get(it.key[1], ())]
        ls += [self.zone.get(z, ()) for z in it.zones]
        return sum(1 for L in ls for a, b in L if a <= it.t1 and it.t0 <= b)


def overlap(X, Y):
    return X.t0 <= Y.t1 and Y.t0 <= X.t1


class Planner:
    def __init__(self, g, speed, step=1.0, near_cm=14.5, wrong_lane=1.5, horizon=400,
                 cbs_nodes=150, cbs_expand=40000, corridor=True, w=1.5):
        # cbs_expand: A* 창(11-02)으로 탐색이 가벼워져 15000 → 40000. w: ECBS 허용 배수 (None = 예전 CBS)
        self.g, self.speed, self.step, self.near_cm = g, speed, step, near_cm
        self.wrong_lane, self.horizon = wrong_lane, horizon
        self.cbs_nodes, self.cbs_expand = cbs_nodes, cbs_expand   # CBS 한도: 노드 수, A* 펼침 수 (시계 대신 → 같은 입력이면 같은 결과)
        self.expanded = 0
        self.corridor = corridor                # 협로 추론 켬
        self._win = None                        # 지금 solve 의 창 (칸)
        self.w = w                              # ECBS 허용 배수 (None = 예전 CBS)
        self.node_stop = 0                      # 비교용: 직선 이어 달리기가 없을 때 지나는 노드에서 서는 칸 (차선·협로 경유 노드)
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
    def astar(self, agent, start, t0, legs, cons, h0=None, soft=None):
        """legs: [(목적지, 머무는 칸, 그 구간 동안 약 실음)] — 마지막 목적지의 머무는 칸이 INF 면 계속 거기 있음,
        유한하면 그만큼 머문 뒤 계획 끝 (그 뒤는 다시 출발할 때 새로 계획).
        목적지 i 에 닿으면 그 자리에서 머무는 칸만큼 반드시 머문 뒤 목적지 i+1 로.
        cons: 피해야 할 Item 목록. h0: 시작 방향 deg (회전 비용, None = 모름 → 첫 회전 0).
        soft: Soft (ECBS) — 있으면 f ≤ fmin × w 인 상태 중 다른 로봇과 겹치는 수가 적은 것부터 (focal search).
        상태 = (노드, t, 구간, 방향). 엣지를 타려면 먼저 그 엣지 방향으로 제자리 회전 (실측 회전 시간, 그동안 노드 점유).
        반환 [(노드, 도착 t, 출발 t, 구간, 실음)] 또는 None"""
        g = self.g
        if self._win is not None:           # 창 뒤에 시작하는 제약은 안 봄 (그때 가서 다시 계획). 안 그러면 먼 제약으로
            cons = [c for c in cons if c.t0 <= self._win]   # 못 가게 된 A* 가 시간 한계까지 다 뒤지고 실패 → CBS 펼침 한도에 걸림 (11-02)
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
        prev = {start_s: None}
        gbest = {start_s: 0.0}
        tmax = t0 + self.horizon
        focal_on = soft is not None and self.w is not None
        w = self.w if focal_on else 1.0
        nconf = {start_s: 0}
        openq = [(h(start, 0), next(tick), 0.0, start_s)]   # f 순 (fmin 용)
        pending, focal, closed = [], [], set()              # focal: f ≤ fmin×w 인 것, (겹침 수, f) 순
        fmin = h(start, 0)
        if focal_on:
            focal = [(0, fmin, next(tick), 0.0, start_s)]

        def live(e_gc, st):
            return st not in closed and e_gc <= gbest.get(st, INF)

        def pop_next():
            nonlocal fmin
            if not focal_on:
                while openq:
                    f, _, gc, st = heapq.heappop(openq)
                    if live(gc, st):
                        return f, gc, st
                return None
            while openq and not live(openq[0][2], openq[0][3]):
                heapq.heappop(openq)
            if not openq:
                return None
            if openq[0][0] > fmin:                          # fmin 이 오르면 그만큼 focal 에 더 넣음
                fmin = openq[0][0]
                while pending and pending[0][0] <= fmin * w:
                    f, tk, gc, st = heapq.heappop(pending)
                    if live(gc, st):
                        heapq.heappush(focal, (nconf.get(st, 0), f, tk, gc, st))
            while focal:
                c_, f, _, gc, st = heapq.heappop(focal)
                if live(gc, st):
                    return f, gc, st
            while pending:                                  # focal 이 비면 남은 것 중 f 가 가장 작은 것
                f, _, gc, st = heapq.heappop(pending)
                if live(gc, st):
                    return f, gc, st
            return None

        while True:
            nx = pop_next()
            if nx is None:
                break
            f, gc, (n, t, i, hd) = nx
            closed.add((n, t, i, hd))
            self.expanded += 1
            if (stays and i == L - 1 and n == last_goal and t > latest) or i == L:
                out, st = [], (n, t, i, hd)
                while st is not None:
                    out.append(st[:3])
                    st = prev[st]
                self._lb = fmin
                return self._compress(out[::-1], legs)
            if t >= tmax:
                continue
            goal_i, dwell_i, loaded = legs[i]
            nxt = []
            nc0 = nconf.get((n, t, i, hd), 0)
            sc = soft.count if focal_on else (lambda it: 0)
            if n == goal_i and (i < L - 1 or not stays):                           # 목적지: 머무는 시간 (정밀 주차·회전 등)
                ld = loaded or (legs[i + 1][2] if i + 1 < L else False)
                it = Item(g, 'node', n, t, t + dwell_i, ld, agent)
                if not blocked(it):
                    nxt.append(((n, t + dwell_i, i + 1, hd), gc + dwell_i, nc0 + sc(it)))
            else:
                it = Item(g, 'node', n, t, t + 1, loaded, agent)
                if not blocked(it):     # 기다림
                    nxt.append(((n, t + 1, i, hd), gc + 1.0, nc0 + sc(it)))
                for m in g.adj[n]:
                    he = round(g.heading(n, m)) % 360
                    r = self.turn(hd, he)
                    if r:                                                          # 먼저 그 엣지 방향으로 제자리 회전
                        it = Item(g, 'node', n, t, t + r, loaded, agent)
                        if not blocked(it):
                            nxt.append(((n, t + r, i, he), gc + r, nc0 + sc(it)))
                        continue
                    d = self.dur[(n, m)]                                           # 엣지 지나기
                    if (self.node_stop and hd is not None and (n, t, i, hd) != start_s
                            and g.nodes[n]['type'] in ('lane', 'way') and g.edge[(n, m)]['mode'] in ('line', 'wall')):
                        d += self.node_stop                                        # 이어 달리기 없음: 지나는 노드에서 섬
                    it = Item(g, 'edge', (n, m), t, t + d, loaded, agent)
                    if blocked(it) or blocked(Item(g, 'node', m, t + d, t + d, loaded, agent)):
                        continue
                    nxt.append(((m, t + d, i, he), gc + d + self.penalty(n, m) + 0.1, nc0 + sc(it)))   # 0.1: 괜히 돌아다니지 말고 제자리 대기
            for st, c, ncf in nxt:
                if c < gbest.get(st, INF):
                    gbest[st] = c
                    prev[st] = (n, t, i, hd)
                    nconf[st] = ncf
                    fs = c + h(st[0], st[2])
                    e = (fs, next(tick), c, st)
                    heapq.heappush(openq, e)
                    if focal_on:
                        if fs <= fmin * w:
                            heapq.heappush(focal, (ncf, fs, e[1], c, st))
                        else:
                            heapq.heappush(pending, e)
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
    def solve(self, agents, statics, window=None):
        """단계적으로: 예전 CBS(최적) → 한도에 걸리면 ECBS(w) → 그래도 안 되면 우선순위 계획.
        11-02 비교: ECBS 를 늘 쓰면 낮은 부하에서 배송이 ~9% 줄고(겹침을 근사로 세어 괜히 돌아감), 높은 부하에서도 배송은 같음
        → 쉬운 계획은 최적으로, 어려운 계획만 ECBS 로 살림"""
        t_start = time.time()
        w0 = self.w
        if w0 is None:
            return self._solve(agents, statics, window, t_start, last_try=True)
        try:
            self.w = None
            out = self._solve(agents, statics, window, t_start, last_try=False)
            if out is not None:
                return out
            self.w = w0
            out = self._solve(agents, statics, window, t_start, last_try=True)
            if self.last['mode'] == 'cbs':
                self.last['mode'] = 'ecbs'
            return out
        finally:
            self.w = w0

    def _solve(self, agents, statics, window, t_start, last_try):
        """agents: [dict(id, start, t0, legs=[(목적지, 머무는 칸, 실음)...], loaded, prefix=[Item...], plan_only)]
        statics: [Item ...] (끝까지 서 있는 로봇)
        window: 이 칸 수 안에서 시작하는 충돌만 푼다 (그 뒤는 다음 계획에서, RHCR). None = 끝까지
        반환 {id: plan} (못 풀면 그 로봇은 빠짐), 그리고 self.last 에 통계. last_try=False 면 한도에 걸릴 때 None"""
        self.expanded = 0
        self._win = window
        self.last = dict(mode='cbs', nodes=0, ms=0, agents=len(agents), conflicts=0, corridor=0)
        if not agents:
            return {}
        A = {a['id']: a for a in agents}

        def plan_one(aid, cons, its=None):
            """안 되면 뒤 목적지(예측)를 줄여 다시: 이번 목적지까지만. its = 다른 로봇들의 지금 Item (ECBS 겹침 세기)"""
            a = A[aid]
            legs = list(a['legs'])
            soft = None
            if self.w is not None and its is not None:
                soft = Soft(self.g, [x for o, L_ in its.items() if o != aid for x in L_], window)
            while legs:
                p = self.astar(aid, a['start'], a['t0'], legs, statics + cons, a.get('heading'), soft)
                if p is not None:
                    return p
                if len(legs) == 1:
                    return None
                legs = legs[:-1]
                self.last['trimmed'] = self.last.get('trimmed', 0) + 1
            return None

        root_cons = {aid: [] for aid in A}
        root, root_its = {}, {}
        for aid in A:                                   # ECBS: 앞에서 정한 로봇들 계획과 덜 겹치게
            p = plan_one(aid, [], root_its)
            if p is None:
                return self.prioritized(agents, statics, t_start) if last_try else None
            root[aid] = p
            root_its[aid] = self.items(aid, p, A[aid].get('prefix', ()))
        tick = itertools.count()

        def cost(plans):
            return sum(p[-1][1] for p in plans.values())

        def make(plans, cons):                          # 갈래: (비용, 번호, 계획, 제약, Item, 첫 충돌, 충돌 수)
            its = {aid: self.items(aid, plans[aid], A[aid].get('prefix', ())) for aid in plans}
            first, n = self.conflicts(its, window, count=self.w is not None)
            return [cost(plans), next(tick), plans, cons, its, first, n]

        openl = [make(root, root_cons)]

        def take():                                     # 비용 ≤ 최소 × w 인 갈래 중 남은 충돌이 가장 적은 것 (w=None: 비용 순)
            lo = min(x[0] for x in openl)
            pool = [x for x in openl if x[0] <= lo * (self.w or 1.0)]
            best = min(pool, key=lambda x: (x[6], x[0], x[1]) if self.w is not None else (x[0], x[1]))
            openl.remove(best)
            return best

        while openl:
            if self.last['nodes'] >= self.cbs_nodes or self.expanded > self.cbs_expand:
                return self.prioritized(agents, statics, t_start) if last_try else None
            _, _, plans, cons, its, c, _ = take()
            self.last['nodes'] += 1
            if c is None:
                self.last['ms'] = round((time.time() - t_start) * 1000, 1)
                return plans
            self.last['conflicts'] += 1
            X, Y = c
            if self.corridor:
                kids = self.corridor_split(X, Y, its, plans, cons, plan_one)
                if kids:
                    self.last['corridor'] += 1
                    for np_, nc in kids:
                        openl.append(make(np_, nc))
                    continue
            lo, hi = max(X.t0, Y.t0), min(X.t1, Y.t1)
            for mine, other in ((X, Y), (Y, X)):
                if mine.fixed:
                    continue                                   # 이미 지나는 중인 엣지는 못 바꾼다
                aid = mine.agent
                block = Item(self.g, other.kind, other.key, lo, hi, other.loaded, other.agent, zones=other.zones)
                nc = dict(cons)
                nc[aid] = cons[aid] + [block]
                p = plan_one(aid, nc[aid], its)
                if p is None:
                    continue
                np_ = dict(plans)
                np_[aid] = p
                openl.append(make(np_, nc))
        return self.prioritized(agents, statics, t_start) if last_try else None

    @staticmethod
    def zone_visit(items, z, at):
        """items 중 zone z 에 한 번 들어갔다 나오는 동안 [t0, t1] (시각 at 을 포함하는 방문). z 밖 엣지를 타면 방문이 끊김"""
        inside = sorted((it for it in items if z in it.zones), key=lambda it: it.t0)
        outside = [it.t0 for it in items if it.kind == 'edge' and z not in it.zones]
        runs = []
        for it in inside:
            if runs and not any(runs[-1][1] < t < it.t0 for t in outside):
                runs[-1][1] = max(runs[-1][1], it.t1)
            else:
                runs.append([it.t0, it.t1])
        return next(((a, b) for a, b in runs if a <= at <= b), None)

    def corridor_split(self, X, Y, its, plans, cons, plan_one):
        """1대 zone 충돌이면 두 갈래: 각 로봇이 상대의 zone 방문 전체 동안 그 zone 밖에 있기. 만든 갈래 목록 (없으면 [])"""
        zs = X.zones & Y.zones
        if not zs:
            return []
        z, at = next(iter(zs)), max(X.t0, Y.t0)
        vis = {X.agent: self.zone_visit(its[X.agent], z, at), Y.agent: self.zone_visit(its[Y.agent], z, at)}
        if None in vis.values():
            return []
        kids = []
        for mine, other in ((X, Y), (Y, X)):
            if mine.fixed:
                continue
            aid = mine.agent
            t0, t1 = vis[other.agent]
            nc = dict(cons)
            nc[aid] = cons[aid] + [Item(self.g, 'zone', z, t0, t1, other.loaded, other.agent, zones={z})]
            p = plan_one(aid, nc[aid], its)
            if p is None:
                continue
            np_ = dict(plans)
            np_[aid] = p
            kids.append((np_, nc))
        return kids

    def first_conflict(self, its, window=None):
        return self.conflicts(its, window)[0]

    def conflicts(self, its, window=None, count=False):
        """(가장 이른 충돌 (X, Y) 또는 None, 충돌 수). count=False 면 수는 0 (빨리)"""
        best, n = None, 0
        ids = list(its)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                for X in its[ids[i]]:
                    for Y in its[ids[j]]:
                        if overlap(X, Y) and space_conflict(self.g, X, Y, self.near_cm):
                            t = max(X.t0, Y.t0)
                            if window is not None and t > window:
                                continue
                            n += 1
                            if best is None or t < best[0]:
                                best = (t, X, Y)
        return (None if best is None else (best[1], best[2])), n

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
