"""FMS 코어 + 가상 로봇 (시뮬레이션).

설계 문서: https://claude.ai/artifact/HUtGfUd8E16rrR7mptVymC
좌표 = 그림 cm (왼쪽 아래 원점, y 위), 위치 = 라이다 중심. 시간 = 시뮬레이션 초.

- Graph      : driving/graph/graph.yaml 을 차선까지 그대로 읽는다 (보류 노드·엣지 제외)
- Robot      : 가상 핑키. FMS 가 내준 구간(노드 목록)만 일정 속도로 달린다
- FMS        : 주문 → 배송 묶음·배차 → 경로 → 구간 예약 → 상태(오염도·피로도·적재) 관리
"""
import heapq
import math
import os
import random

import yaml

from planner import INF, Item, Planner, space_conflict

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH = os.path.join(HERE, '../driving/graph/graph.yaml')   # 주행 그래프는 driving/ 의 것을 그대로 씀 (복사하지 말 것)

PHARMACY, POCKET, CHARGER, SURGERY = 'PHARMACY', 'POCKET', 'CHARGER', 'SURGERY'
PHARMACY_DOCK = 'PHARMACY_DOCK'   # 정밀 주차 자리 (graph: PHARMACY–PHARMACY_DOCK 엣지 mode dock). 실제 로봇만 씀
LATE_X = 1.5                      # 실제 로봇: 엣지가 예상의 이만큼 + 2초 넘게 걸리면 '늦음' → 다시 계획
ROOM_INFO = yaml.safe_load(open(os.path.join(HERE, 'rooms.yaml')))['rooms']    # 병실 → 이름·오염도·별칭 (관제 PC 이름)
ROOM_CONTAM = {k: v['contam'] for k, v in ROOM_INFO.items()}   # 1인실 +10, 4인실 +50, 수술실 0 (오염도 0 으로만 진입)
ROOMS = list(ROOM_CONTAM)
ROBOT_TABLE = yaml.safe_load(open(os.path.join(HERE, 'robots.yaml')))['robots']   # 관제 PC 로봇 번호 ↔ 이름
ROOM_KEYS = ('room', 'dest', 'location', '병실', '병실위치', '병실 위치', '목적지', '위치')
ITEM_KEYS = ('item', 'items', '물품', '품목')


def _norm(x):
    return str(x).replace(' ', '').replace('_', '').replace('-', '').lower()


ROOM_ALIAS = {}
for _k, _v in ROOM_INFO.items():
    for _a in [_k, _v.get('name', '')] + list(_v.get('aliases') or []):
        if _a:
            ROOM_ALIAS[_norm(_a)] = _k


def resolve_room(name):
    k = ROOM_ALIAS.get(_norm(name))
    if k is None:
        raise ValueError(f'모르는 병실 "{name}". 쓸 수 있는 이름: ' +
                         ', '.join(sorted(str(v.get('code', k)) for v in ROOM_INFO.values())))
    return k


class Conflict(Exception):
    """API 409: 지금 상태에서는 할 수 없는 요청"""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def room_code(node):
    """그래프 노드 → 관제 PC 방 번호 (101호 …, 수술실, 약제실)"""
    if node == PHARMACY:
        return '약제실'
    return str(ROOM_INFO[node].get('code', node)) if node in ROOM_INFO else node


def room_or_none(node):
    """병실·약제실이면 방 번호, 아니면 None (API 의 room 필드)"""
    return room_code(node) if (node in ROOM_INFO or node == PHARMACY) else None


def place_of(node):
    """사람이 읽는 위치 이름"""
    if node in ROOM_INFO or node == PHARMACY:
        return room_code(node)
    named = {'POCKET': 'POCKET(대기)', 'CHARGER': '충전기'}
    if node in named:
        return named[node]
    head = node[:1]
    if node[:2] in ('B1', 'B2') or node.startswith('GB'):
        return '아래 복도'
    if node[:2] in ('T1', 'T2') or node.startswith('GT'):
        return '위 복도'
    return {'L': '왼쪽 협로', 'R': '오른쪽 협로', 'S': '단일차선 협로'}.get(head, node)


def parse_request(body):
    """관제 PC 요청 → [(병실 노드, 물품)]. 형식이 아직 안 정해져서 키 이름을 넓게 받는다.
    {"병실위치": "4인실 왼쪽", "물품": "약"} / {"room": "ROOM4_L"} / 그 목록 / {"orders": [...]}"""
    if isinstance(body, dict) and isinstance(body.get('orders'), list):
        body = body['orders']
    reqs = body if isinstance(body, list) else [body]
    out = []
    for q in reqs:
        if not isinstance(q, dict):
            raise ValueError(f'요청은 JSON 객체여야 함: {q!r}')
        room = next((q[k] for k in ROOM_KEYS if k in q), None)
        if room is None:
            raise ValueError(f'병실 키가 없음 ({", ".join(ROOM_KEYS)} 중 하나): {q}')
        item = next((q[k] for k in ITEM_KEYS if k in q), '약')
        out.append((resolve_room(room), item))
    return out
PARKING = ['B1_20', 'B2_20', 'T1_20', 'B1_195']   # 노는 로봇 주차 자리 (통행을 안 막는 복도 끝). T2_20 은 콘센트 자리라 그래프에서 뺌 (10-28)
# B2_195 는 수술실 입구(GB180)에 너무 가까워 뺌.
# CHARGER 는 막다른 곳이라 뺌. 같은 x 의 두 차선 자리(짝)에 약 실은 로봇 둘을 세우면 그 복도 끝을 아무도 못 지나가므로 짝은 하나만
EAST_LANE = {'B': 'B1', 'T': 'T1'}                           # 우측통행: 동쪽(+x)으로 갈 때 쓰는 차선 (아래쪽 차선)
COLORS = ['#e4572e', '#2e86de', '#20bf6b', '#a55eea', '#f7b731']
STOP_ZONES = {'POCKET': {'pocket'}}     # POCKET 에 서 있어도 충전 zone 까지 잡지는 않는다 (충전기 출입은 POCKET 노드로 막힘)
NEAR_CM = 14.5                          # 이보다 가까운 두 노드는 동시에 못 씀 (그릇 Ø14 + 여유). 예: 문 앞 점 ↔ 차선 노드 9.5cm
BODY_CLEAR_CM = 14.5                    # 지나간 노드는 이만큼 멀어질 때까지 붙잡는다 (뒤따르는 로봇과 부딪히지 않게)


class Params:
    def __init__(self, **kw):
        self.speed = 4.5           # cm/s — 실측 시간(graph/edge_times.yaml)이 없는 엣지에만 씀 (10-29 실측: 라인·벽 ≈ 4.2~4.6 cm/s)
        self.dock_s = 20.0         # 정밀 주차
        self.load_s = 10.0         # 관제 PC/OMX 적재 (가상: 주차 끝 알림 뒤 이 시간 지나면 적재 완료)
        self.spin_s = 8.0          # 병실 제자리 360° 회전 = 배송 완료
        self.dwell_s = 5.0         # POCKET 5초 = 오염도 0
        self.charge_s = 10.0       # CHARGER 도착 10초 뒤 피로도 100
        self.cap = 3               # 적재 용량 (실는 개수 = 맡은 주문 수. 여분은 싣지 않음 — 2026-10-27 사용자)
        self.pause_s = (1.0, 5.0)  # 병실 회전 뒤 다음 일까지 쉬는 시간 (무작위, 초) — 2026-10-27 사용자
        self.prep_s = 15.0         # 가상 OMX 물품 준비 (배차 → ready). 실제로는 관제 PC 가 POST .../ready
        self.auto_omx = True       # 가상 관제 PC/OMX: ready·loaded 를 시간 지나면 스스로 보냄. 외부 관제 PC 를 붙이면 끔
        self.fatigue_per_room = 10     # 피로도: 가상 값 (실제 핑키 배터리 아님). 병실 하나 배송마다 −10, CHARGER 에서 100
        self.pharmacy_min_fatigue = 20   # 이 값 이하면 약제실 방문 금지
        self.contam_max = 100
        self.wrong_lane = 1.5      # 우측통행 반대 차선 비용 배수
        self.replan_s = 2.0        # 예약 못 하고 기다릴 때 경로 다시 짜는 간격
        self.dispatch_s = 0.5
        self.planner = 'cbs'       # cbs = 시공간 A* + CBS 로 시간까지 계획 / reserve = 최단 경로 + 구간 예약만
        self.plan_step = 1.0       # CBS 시간 칸 (초)
        for k, v in kw.items():
            setattr(self, k, v)


def seg_dist(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


# ----------------------------------------------------------------------------------------------------------
class Graph:
    def __init__(self, path=GRAPH):
        g = yaml.safe_load(open(path))
        self.nodes = {k: n for k, n in g['nodes'].items() if not n.get('deferred')}
        self.edge = {}                     # (a, b) 양방향 키 → info
        self.adj = {k: [] for k in self.nodes}
        for e in g['edges']:
            a, b = e['a'], e['b']
            if e.get('deferred') or a not in self.nodes or b not in self.nodes:
                continue
            lane = None
            if e['mode'] == 'line':
                lane = self.nodes[a].get('lane') or self.nodes[b].get('lane')
            info = dict(a=a, b=b, mode=e['mode'], zone=e.get('zone'), lane=lane, L=math.dist(self.xy(a), self.xy(b)))
            self.edge[(a, b)] = self.edge[(b, a)] = info
            self.adj[a].append(b)
            self.adj[b].append(a)
        # 갈림목 건너기: 경계점 → 먼 차선 transfer 엣지는 가까운 차선 노드를 지나간다
        self.crossed = {}
        for (a, b), info in self.edge.items():
            if info['mode'] != 'transfer' or self.nodes[a]['type'] != 'gate':
                continue
            x, y0, y1 = self.xy(b)[0], self.xy(a)[1], self.xy(b)[1]
            mid = [n for n, m in self.nodes.items() if m['type'] == 'lane' and m['xy'][0] == x
                   and min(y0, y1) < m['xy'][1] < max(y0, y1)]
            if mid:
                self.crossed[(a, b)] = self.crossed[(b, a)] = mid
        self.near = {n: {m for m in self.nodes if m != n and math.dist(self.xy(n), self.xy(m)) < NEAR_CM}
                     for n in self.nodes}
        self.seg_near = {}                 # 엣지가 가까이 지나가는 노드 (예: POCKET–CHARGER 엣지 ↔ T1_190 10cm)
        for (a, b) in self.edge:
            self.seg_near[(a, b)] = {m for m in self.nodes if m not in (a, b)
                                     and seg_dist(self.xy(m), self.xy(a), self.xy(b)) < NEAR_CM}
        self._dist = {}
        # 실측 엣지 시간 (driving/tools/edge_run.py → edge_costs.py → graph/edge_times.yaml). 없으면 길이 ÷ 속도
        self.time, self.rot = {}, None
        tp = os.path.join(os.path.dirname(path), 'edge_times.yaml')
        if os.path.exists(tp):
            t = yaml.safe_load(open(tp)) or {}
            for v in (t.get('edges') or {}).values():
                if (v['a'], v['b']) in self.edge:
                    self.time[(v['a'], v['b'])] = float(v['move_s'])
            R = t.get('rotate')
            if R:
                self.rot = (float(R['r0_s']), float(R['s_per_deg']))

    def heading(self, a, b):
        (ax, ay), (bx, by) = self.xy(a), self.xy(b)
        return math.degrees(math.atan2(by - ay, bx - ax)) % 360

    def edge_s(self, a, b, speed):
        """a→b 이동 시간 s: 실측 중앙값 (방향별), 없으면 길이 ÷ speed"""
        return self.time.get((a, b)) or self.edge[(a, b)]['L'] / speed

    def rot_s(self, h0, h1):
        """제자리 회전 시간 s (실측 식 r0 + 각도·s_per_deg). 모르는 방향(None)·회전 식 없음·1.5° 미만이면 0"""
        if h0 is None or h1 is None or self.rot is None:
            return 0.0
        d = abs((h1 - h0 + 180) % 360 - 180)
        return 0.0 if d < 1.5 else self.rot[0] + self.rot[1] * d

    def time_to(self, a, b, speed):
        """배차·ETA 용: 거리 기준 최단 경로를 실측 시간으로 (회전 제외)"""
        p = self.path(a, b)
        return sum(self.edge_s(p[i], p[i + 1], speed) for i in range(len(p) - 1)) if p else 1e9

    def xy(self, n):
        return tuple(self.nodes[n]['xy'])

    def is_lane(self, n):
        return self.nodes[n]['type'] == 'lane'

    @staticmethod
    def cap1(zone):
        return zone is not None and not zone.startswith('corr_')

    def stop_zones(self, n):
        """목적지(stop) 노드에 서 있으면 붙잡는 1대 zone (막다른 방, 약제실, POCKET/충전)"""
        if self.nodes[n]['type'] != 'stop':
            return set()
        if n in STOP_ZONES:
            return set(STOP_ZONES[n])
        return {self.edge[(n, m)]['zone'] for m in self.adj[n] if self.cap1(self.edge[(n, m)]['zone'])}

    def lane_cost(self, a, b):
        e = self.edge[(a, b)]
        if not e['lane']:
            return e['L']
        east = self.xy(b)[0] > self.xy(a)[0]
        right = (EAST_LANE[e['lane'][0]] == e['lane']) == east
        return e['L'] * (1.0 if right else Params().wrong_lane)

    def path(self, src, dst, extra=None):
        """extra(a, b) → 추가 비용 (다른 로봇이 잡은 곳 벌점)"""
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist[u]:
                continue
            for v in self.adj[u]:
                c = d + self.lane_cost(u, v) + (extra(u, v) if extra else 0.0)
                if c < dist.get(v, 1e18):
                    dist[v] = c
                    prev[v] = u
                    heapq.heappush(pq, (c, v))
        if dst not in dist:
            return None
        p = [dst]
        while p[-1] != src:
            p.append(prev[p[-1]])
        return p[::-1]

    def dist(self, a, b):
        """경로 길이 cm (배차 비용용, 벌점 없이)"""
        if a == b:
            return 0.0
        k = (a, b)
        if k not in self._dist:
            p = self.path(a, b)
            self._dist[k] = sum(self.edge[(p[i], p[i + 1])]['L'] for i in range(len(p) - 1)) if p else 1e9
        return self._dist[k]

    def x_range(self, a, b):
        xa, xb = self.xy(a)[0], self.xy(b)[0]
        return min(xa, xb), max(xa, xb)


# ----------------------------------------------------------------------------------------------------------
class Order:
    _n = 0

    def __init__(self, room, t, item='약', request_id=None, stamp=None):
        Order._n += 1
        self.id = Order._n
        self.room = room
        self.item = item
        self.created = t
        self.state = 'waiting'     # waiting → assigned → loaded → delivered (또는 canceled / failed)
        self.robot = None
        self.done_t = None
        self.request_id = request_id
        self.batch = None
        self.created_at, self.delivered_at, self.fail_reason = stamp, None, None

    @property
    def oid(self):
        return f'o-{self.id}'

    def as_dict(self):
        return dict(id=self.id, room=self.room, item=self.item, state=self.state, robot=self.robot,
                    created=round(self.created, 1), done=None if self.done_t is None else round(self.done_t, 1))


class Batch:
    """배차 때 정해지는 묶음 (핑키 1대 + 주문 ≤3). 정해지면 바뀌지 않는다.
    assigned → (관제 PC ready) called → (정밀 주차 끝) at_pharmacy → (관제 PC loaded) delivering → completed"""
    _n = 0

    def __init__(self, robot, orders, rooms, t):
        Batch._n += 1
        self.id = Batch._n
        self.robot, self.orders, self.rooms, self.created = robot, list(orders), list(rooms), t
        self.status = 'assigned'
        self.status_t = t          # 지금 상태가 된 시각 (가상 OMX 타이머)

    @property
    def bid(self):
        return f'b-{self.id}'


class Robot:
    def __init__(self, rid, node, g, color):
        self.id, self.node, self.g, self.color = rid, node, g, color
        self.pos = g.xy(node)
        self.fatigue, self.contam, self.load = 100, 0, 0
        self.assigned = []          # 맡은 주문 (아직 배송 안 함)
        self.task = None            # None / delivery / decon / charge / park / yield
        self.step = None            # 지금 단계 dict
        self.queue = []             # 다음 단계들
        self.timer = 0.0
        self.loaded_done = True     # 이번 배송에서 약제실 적재가 끝났는지
        # 이동 상태
        self.path, self.k, self.res_to, self.edge_t = [], 0, 0, 0.0
        self.extra_nodes = set()    # 이번 구간에서 가로지르는 차선 노드
        self.dest_zones = set()     # 목적지 zone 미리 잡기
        self.wait_s, self.wait_why, self.replan_t = 0.0, '', 0.0
        self.prev_node, self.since = None, 1e9   # 방금 지나간 노드, 그 뒤로 간 거리
        self.blocked_by = set()
        self.depart = None          # CBS 계획: path[i] 에서 떠나도 되는 시각 (없으면 바로)
        self.plan_wait = False
        self.num, self.name = None, rid        # 관제 PC 로봇 번호, 이름 (robots.yaml)
        self.heading = 0.0          # deg, 마지막으로 달린 엣지 방향 (경로 계획의 회전 비용 시작 방향)
        self.turn_left = None       # CBS 시각 없이 갈 때: 다음 엣지 방향으로 남은 회전 시간 s
        self.batch = None
        # 실제 로봇 (robot_link.HttpLink). None = 시뮬레이션
        self.link = None
        self.drive = None           # 보낸 명령: dict(cid, kind, k0, j, extra, t, late)
        self.fault = None           # 실패해 멈춤: dict(code, why, t, node, edge) — 사람이 풀 때까지 그 자리
        self.at_dock = False        # 정밀 주차 자리(PHARMACY_DOCK)에 있음 → 다음 /drive 앞에 물러나기 엣지
        self.link_lost = False
        self.boot = None            # 로봇 boot_id (바뀌면 재부팅 → 위치를 믿을 수 없음)
        self.reattach_t = 0.0

    @property
    def loaded(self):
        return self.load > 0

    @property
    def idle(self):
        return self.step is None and not self.queue and not self.fault   # 실패로 멈춘 실제 로봇에는 일을 안 줌

    def holds(self):
        """지금 붙잡은 (노드, 엣지, zone)"""
        g = self.g
        if self.step and self.step['kind'] == 'move' and self.path:
            nodes = set(self.path[self.k:self.res_to + 1]) | self.extra_nodes
            edges = {(self.path[i], self.path[i + 1]) for i in range(self.k, self.res_to)}
        else:
            nodes, edges = {self.node}, set()
        if self.prev_node and math.dist(self.pos, self.g.xy(self.prev_node)) < BODY_CLEAR_CM:
            nodes.add(self.prev_node)
        zones = {g.edge[e]['zone'] for e in edges if g.cap1(g.edge[e]['zone'])}
        zones |= g.stop_zones(self.node) | self.dest_zones
        stopped = not (self.step and self.step['kind'] == 'move' and self.path) or \
            (self.edge_t == 0 and self.res_to <= self.k and self.depart is None)   # CBS 대기는 시간으로 이미 맞춤
        if stopped and g.nodes[self.node]['type'] in ('way', 'gate'):
            zones |= {g.edge[(self.node, m)]['zone'] for m in g.adj[self.node] if g.cap1(g.edge[(self.node, m)]['zone'])}
        return nodes, edges, zones

    def state_name(self):
        if self.fault:
            return 'error'
        if self.step is None:
            return 'idle'
        k = self.step['kind']
        if k == 'move':
            return 'waiting' if self.wait_s > 0 else ('planned' if self.plan_wait else 'moving')
        return {'dock': 'docking', 'load': 'loading', 'spin': 'spinning', 'pause': 'pausing', 'dwell': 'decon',
                'charge': 'charging', 'wait_ready': 'reserved'}[k]


# ----------------------------------------------------------------------------------------------------------
class FMS:
    def __init__(self, n_robots=3, params=None, seed=None, graph=None, links=None):
        self.p = params or Params()
        self.g = graph or Graph()
        self.rng = random.Random(seed)
        self.t = 0.0
        starts = ['B1_20', 'T1_20', 'B2_20', 'B1_195']
        self.robots = [Robot(f'R{i + 1}', starts[i], self.g, COLORS[i]) for i in range(n_robots)]
        for i, r in enumerate(self.robots):
            row = ROBOT_TABLE[i] if i < len(ROBOT_TABLE) else {'robot': i + 1, 'name': f'pinky_{i + 1}'}
            r.num, r.name = row['robot'], row['name']
        self.orders = []
        self.batches = []
        self.by_request = {}         # request_id → 주문 (같은 요청 두 번 = 한 번)
        self.outbox = []             # API v1 이벤트 (관제 PC 로 보낼 것). sim_server 가 가져가 보낸다
        self._seq = 0
        self.clock = None            # () → ISO 시각 문자열 (sim_server 가 넣음). 없으면 시뮬레이션 초
        self.events = []
        self.stats = dict(delivered=0, violations=0, collisions=0, near=0)
        self._next_dispatch = 0.0
        self.auto_rate = 0.0         # 분당 자동 주문 수
        self._next_auto = None
        self.planner = Planner(self.g, self.p.speed, step=self.p.plan_step, near_cm=NEAR_CM, wrong_lane=self.p.wrong_lane)   # 실측 시간·회전
        self.plan_stats = dict(replans=0, cbs=0, prioritized=0, failed=0, last=None)
        self.last_plans = {}
        for r in self.robots:                   # 실제 로봇: 시작 노드 = 로봇이 보고한 노드
            if links and r.name in links:
                self.attach_real(r, links[r.name])

    # ---- 기록 ----
    def log(self, msg, kind='info'):
        self.events.append(dict(t=round(self.t, 1), msg=msg, kind=kind))
        if kind == 'violation':
            self.stats['violations'] += 1
        del self.events[:-300]

    # ---- API v1 보기 (관제 PC 로 나가는 모양) ----
    @staticmethod
    def task_name(r):
        if r.step and r.step.get('sidestep'):
            return 'yield'
        return r.task or 'none'

    def robot_status(self, r):
        moving = r.step and r.step['kind'] == 'move' and r.path
        path = r.path[r.k:] if moving else []
        st = r.state_name()
        dest = r.step['to'] if r.step and r.step['kind'] == 'move' else None
        return dict(robot=r.num, name=r.name, online=(r.link.alive() if r.link else True), real=r.link is not None,
                    fault=r.fault,
                    state={'planned': 'moving'}.get(st, st), task=self.task_name(r),
                    pose=dict(x=round(r.pos[0], 1), y=round(r.pos[1], 1), heading=round(r.heading, 1)),
                    node=r.node, next_node=path[1] if len(path) > 1 else None, place=place_of(r.node),
                    destination=None if dest is None else dict(node=dest, room=room_or_none(dest)),
                    path=path, fatigue=r.fatigue, contamination=r.contam, load=r.load, capacity=self.p.cap,
                    batch_id=r.batch.bid if r.batch else None, orders=[o.oid for o in r.assigned])

    def order_api(self, o):
        st = {'waiting': 'queued'}.get(o.state, o.state)
        r = next((x for x in self.robots if x.id == o.robot), None)
        return dict(order_id=o.oid, request_id=o.request_id, room=room_code(o.room), item=o.item, status=st,
                    batch_id=o.batch.bid if o.batch else None, robot=r.num if r else None,
                    created_at=o.created_at, delivered_at=o.delivered_at, fail_reason=o.fail_reason)

    def batch_api(self, b):
        return dict(batch_id=b.bid, status=b.status, robot=b.robot.num, name=b.robot.name,
                    orders=[dict(order_id=o.oid, room=room_code(o.room), item=o.item, status=self.order_api(o)['status'])
                            for o in b.orders],
                    count=len(b.orders), rooms=[room_code(x) for x in b.rooms])

    def find_order(self, oid):
        return next((o for o in self.orders if o.oid == oid), None)

    def find_batch(self, bid):
        return next((b for b in self.batches if b.bid == bid), None)

    def state_v1(self):
        return dict(time=self.stamp(), robots=[self.robot_status(r) for r in self.robots],
                    orders=[self.order_api(o) for o in self.orders if o.state not in ('delivered', 'canceled', 'failed')],
                    batches=[self.batch_api(b) for b in self.batches if b.status not in ('completed', 'failed')],
                    last_seq=self._seq)

    # ---- API v1 이벤트 (FMS → 관제 PC) ----
    def stamp(self):
        return self.clock() if self.clock else f'{self.t:.1f}'

    def emit(self, type_, **kw):
        self._seq += 1
        ev = dict(event_id=f'e-{self._seq}', seq=self._seq, time=self.stamp(), type=type_, **kw)
        self.outbox.append(ev)
        del self.outbox[:-2000]
        return ev

    # ---- 주문 (관제 PC → FMS) ----
    def add_order(self, room, item='약', request_id=None):
        """주문 1건. 같은 request_id 가 이미 있으면 그 주문을 그대로 돌려준다 (새로 안 만듦)"""
        if request_id is not None and request_id in self.by_request:
            return self.by_request[request_id]
        room = resolve_room(room)
        o = Order(room, self.t, item, request_id, self.stamp())
        self.orders.append(o)
        if request_id is not None:
            self.by_request[request_id] = o
        self.log(f'관제 PC → FMS: 주문 #{o.id} {room_code(room)} ({item})')
        self.emit('order_created', order_id=o.oid, request_id=request_id, room=room_code(room), item=item)
        return o

    def cancel_order(self, o):
        if o.state != 'waiting':
            raise Conflict('order_locked', f'주문 {o.oid} 는 이미 묶음 {o.batch.bid if o.batch else ""} 에 들어가 취소할 수 없음')
        o.state = 'canceled'
        self.log(f'관제 PC → FMS: 주문 #{o.id} 취소')
        self.emit('order_canceled', order_id=o.oid)
        return o

    def batch_ready(self, b):
        """관제 PC: OMX 물품 준비 끝 → 핑키를 약제실로"""
        if b.status != 'assigned':
            raise Conflict('bad_batch_state', f'묶음 {b.bid} 상태가 {b.status} (assigned 일 때만 ready)')
        r = b.robot
        b.status, b.status_t = 'called', self.t
        eta = self.g.time_to(r.node, PHARMACY, self.p.speed) + self.p.dock_s
        self.log(f'관제 PC → FMS: 묶음 {b.bid} 준비 완료 → {r.id} 약제실로')
        self.emit('robot_called', batch_id=b.bid, robot=r.num, eta_s=round(eta))
        return round(eta)

    def batch_loaded(self, b):
        """관제 PC: OMX 가 핑키에 다 실음 → 병실로 출발"""
        if b.status != 'at_pharmacy':
            raise Conflict('bad_batch_state', f'묶음 {b.bid} 상태가 {b.status} (at_pharmacy 일 때만 loaded)')
        b.status, b.status_t = 'delivering', self.t
        self.log(f'관제 PC → FMS: 묶음 {b.bid} 적재 완료')
        self.emit('batch_departed', batch_id=b.bid, robot=b.robot.num, rooms=[room_code(x) for x in b.rooms])

    # ---- 단계 만들기 ----
    def visit_steps(self, start, rooms, c0, pocket=False):
        """병실 방문 단계: 가까운 병실부터. 수술실은 오염도 0 에서만.
        pocket=False (배송, 10-29 사용자: 오염도가 0 이 아니어도 배송을 주되 POCKET 을 들르지 않고 끝낼 수 있어야 함):
        수술실이 있으면 오염도 0 일 때 맨 앞으로만, 아니면 None (이 로봇은 못 함).
        pocket=True: 예전 방식 — 중간에 POCKET 들렀다가 수술실"""
        def nn(frm, rs):
            out, here, rs = [], frm, list(rs)
            while rs:
                r = min(rs, key=lambda x: self.g.dist(here, x))
                out.append(r)
                rs.remove(r)
                here = r
            return out

        def steps(order_):
            st = []
            for r in order_:
                if r == 'POCKET*':
                    st += [dict(kind='move', to=POCKET, visit=True), dict(kind='dwell', visit=True)]
                else:
                    st += [dict(kind='move', to=r, visit=True), dict(kind='spin', room=r, visit=True)]
            return st

        def length(order_):
            here, L = start, 0.0
            for r in order_:
                r = POCKET if r == 'POCKET*' else r
                L += self.g.dist(here, r)
                here = r
            return L

        rooms = list(dict.fromkeys(rooms))      # 같은 병실은 한 번
        if SURGERY not in rooms:
            return steps(nn(start, rooms))
        rest = [r for r in rooms if r != SURGERY]
        if not pocket:
            return steps([SURGERY] + nn(SURGERY, rest)) if c0 == 0 else None
        cands = []
        if c0 == 0:
            cands.append([SURGERY] + nn(SURGERY, rest))
        cands.append(['POCKET*', SURGERY] + nn(SURGERY, rest))
        if rest:
            o = nn(start, rest)
            cands.append(o + ['POCKET*', SURGERY])
        return steps(min(cands, key=length))

    def feasible(self, r, steps, include_current=True):
        """오염도 ≤ 100, 수술실은 0 에서만, 피로도 ≥ 0, 약제실은 피로도 > 20"""
        c, b = r.contam, r.fatigue
        seq = ([r.step] if include_current and r.step else []) + steps
        for s in seq:
            if s['kind'] == 'move':
                if s['to'] == PHARMACY and b <= self.p.pharmacy_min_fatigue:
                    return False
                if s['to'] in ROOM_CONTAM and not s.get('arrived'):
                    if s['to'] == SURGERY and c > 0:
                        return False
                    c += ROOM_CONTAM[s['to']]
                    if c > self.p.contam_max:
                        return False
            elif s['kind'] == 'spin':
                b -= self.p.fatigue_per_room
                if b < 0:
                    return False
            elif s['kind'] == 'dwell':
                c = 0
            elif s['kind'] == 'charge':
                b = 100
        return True

    # ---- 교착 풀기: 서로 기다리면 한 대를 옆으로 비킨다 ----
    def break_deadlocks(self):
        for r in self.robots:
            if r.wait_s < 3.0 or not r.blocked_by or not r.step or r.step['kind'] != 'move':
                continue
            seen, stack = set(), list(r.blocked_by)
            while stack:
                o = stack.pop()
                if o in seen:
                    continue
                seen.add(o)
                if o.wait_s > 0:
                    stack += list(o.blocked_by)
            if r not in seen:
                continue
            cyc = [x for x in self.robots if x in seen and x.step and x.step['kind'] == 'move' and x.wait_s > 0]
            best = None
            for v in cyc:                       # 실제로 비킬 수 있는 로봇·자리 중 가장 가까운 것
                if v.step.get('sidestep') and v.wait_s < 6.0:
                    continue
                found = self.sidestep_spot(v, [x for x in self.robots if x is not v])
                if found and (best is None or (found[1], v.loaded) < (best[2], best[0].loaded)):
                    best = (v, found[0], found[1])
            if best is None:
                continue
            victim, spot, _ = best
            self.log(f'교착: {" ↔ ".join(x.id for x in cyc)} → {victim.id} 가 {spot} 로 비킴', 'warn')
            if not victim.step.get('sidestep'):
                victim.queue.insert(0, dict(victim.step, started=False))
            victim.step = dict(kind='move', to=spot, sidestep=True)
            self.next_step_init_move(victim)
            return

    def lane_conflict(self, v, a, b, others):
        """v(실음) 가 엣지 a→b 를 지날 때 실은 다른 로봇과 교행통로에서 나란히/엇갈리게 되는가"""
        g = self.g
        lane = g.edge[(a, b)]['lane'] or g.nodes[b].get('lane')
        if not lane or not v.loaded:
            return False
        x0, x1 = g.x_range(a, b) if g.edge[(a, b)]['lane'] else (g.xy(b)[0],) * 2
        for o in others:
            if not o.loaded:
                continue
            for n in o.holds()[0]:
                ol = g.nodes[n].get('lane')
                if ol and ol[0] == lane[0] and ol != lane and x0 - NEAR_CM < g.xy(n)[0] < x1 + NEAR_CM:
                    return True
        return False

    def sidestep_spot(self, v, others):
        """v 가 다른 로봇이 붙잡은 곳·가려는 길을 안 지나고 갈 수 있는 가장 가까운 빈자리 (차선 노드·협로 안 경유점).
        v 가 약을 실었으면 실은 다른 로봇이 지나갈 복도 구간도 피한다. 반환 (자리, 거리) 또는 None"""
        g = self.g
        held = set()
        for o in others:
            held |= o.holds()[0]
        block = set(held)
        for n in held:
            block |= g.near[n]
        held_zones = set()
        for o in others:
            held_zones |= o.holds()[2]
        onpath = {n for o in others for n in (o.path[o.k:] if o.path else [])}
        future = []                               # 실은 다른 로봇이 앞으로 지날 교행통로 구간 (복도, x0, x1)
        for o in others:
            if not (o.loaded and v.loaded and o.path):
                continue
            pth = o.path[o.k:]
            for i in range(len(pth) - 1):
                ln = g.edge[(pth[i], pth[i + 1])]['lane']
                if ln:
                    future.append((ln[0],) + g.x_range(pth[i], pth[i + 1]))
        dist, pq = {v.node: 0.0}, [(0.0, v.node)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            kind = g.nodes[u]['type']
            if u != v.node and (kind == 'lane' or kind == 'way') and u not in onpath and not (g.near[u] & onpath):
                ln = g.nodes[u].get('lane')
                x = g.xy(u)[0]
                if not (ln and any(c == ln[0] and x0 - NEAR_CM < x < x1 + NEAR_CM for c, x0, x1 in future)):
                    return u, d
            for w in g.adj[u]:
                e = g.edge[(u, w)]
                if w in block or (g.seg_near[(u, w)] & held) or (g.cap1(e['zone']) and e['zone'] in held_zones):
                    continue
                if g.nodes[w]['type'] == 'stop':
                    continue                          # 병실·약제실로는 비키지 않는다
                if self.lane_conflict(v, u, w, others):
                    continue
                c = d + e['L']
                if c < dist.get(w, 1e18):
                    dist[w] = c
                    heapq.heappush(pq, (c, w))
        return None

    def next_step_init_move(self, r):
        r.depart, r.plan_wait = None, False
        r.path, r.k, r.res_to, r.edge_t = [r.node], 0, 0, 0.0
        r.dest_zones, r.wait_s, r.replan_t, r.blocked_by = set(), 0.0, 0.0, set()
        r.step['started'] = False

    # ---- 배차 ----
    def dispatch(self):
        p = self.p
        self.break_deadlocks()
        for r in self.robots:                               # 노는 로봇: 충전·오염 제거 먼저
            if not r.idle:
                continue
            if r.fatigue <= p.pharmacy_min_fatigue:
                st = ([dict(kind='move', to=POCKET, also={'charger'}), dict(kind='dwell')] if r.contam > 0 else []) + \
                     [dict(kind='move', to=CHARGER), dict(kind='charge')]
                self.start_task(r, 'charge', st, f'피로도 {r.fatigue} → 충전')

        # 배차 때 묶음이 정해지면 그 목록은 바꾸지 않는다 (배송 중인 로봇에 끼워 넣기 없음 — 2026-10-27 사용자).
        # 새 주문은 노는 로봇이 생길 때까지 기다린다.
        waiting = sorted([o for o in self.orders if o.state == 'waiting'], key=lambda o: o.created)
        while waiting:                                      # 1) 노는 로봇에 새 묶음 (오염도가 있어도 POCKET 없이 끝낼 수 있으면)
            if not self.new_bundle(waiting):
                break
            waiting = [o for o in waiting if o.state == 'waiting']
        for r in self.robots:                               # 2) 배송을 못 받은 노는 로봇은 오염도가 있으면 POCKET 으로
            if r.idle and r.contam > 0:
                self.start_task(r, 'decon', [dict(kind='move', to=POCKET), dict(kind='dwell')], f'오염도 {r.contam} → POCKET')

        taken = {r.step['to'] for r in self.robots if r.step and r.step['kind'] == 'move'} | \
                {s['to'] for r in self.robots for s in r.queue if s['kind'] == 'move'}
        for r in self.robots:                               # 3) 남는 로봇은 주차 자리로
            if r.idle and r.node not in PARKING:
                spot = self.free_parking(r, taken)
                if spot:
                    taken.add(spot)
                    self.start_task(r, 'park', [dict(kind='move', to=spot)], f'주차 → {spot}')

    def parking_partner(self, s):
        x, lane = self.g.xy(s)[0], self.g.nodes[s].get('lane')
        return next((m for m in PARKING if m != s and self.g.xy(m)[0] == x
                     and self.g.nodes[m].get('lane', ' ')[0] == lane[0]), None)

    def free_parking(self, r, taken, avoid=()):
        """가장 가까운 빈 주차 자리. 약을 실었으면 짝 자리에 실은 로봇이 있거나 누가 가는 중인 자리는 뺀다"""
        occ = {o.node: o for o in self.robots if o is not r}
        going = {}
        for o in self.robots:
            if o is not r:
                for st in ([o.step] if o.step else []) + o.queue:
                    if st['kind'] == 'move':
                        going[st['to']] = o
        spots = []
        for s in PARKING:
            if s in occ or s in taken or s in avoid or s in going:
                continue
            m = self.parking_partner(s)
            if r.loaded and m and ((m in occ and occ[m].loaded) or (m in going and going[m].loaded) or m in taken):
                continue
            spots.append(s)
        return min(spots, key=lambda s: self.g.dist(r.node, s)) if spots else None

    def new_bundle(self, waiting):
        """먼저 들어온 주문부터 씨앗으로: 그 주문을 POCKET 없이 끝낼 수 있는 노는 로봇이 있으면 묶음을 만든다.
        못 받는 주문(예: 오염된 로봇만 남았는데 수술실)은 건너뛰고 다음 주문을 본다"""
        for seed in waiting:
            if self.bundle_from(seed, [o for o in waiting if o is not seed]):
                return True
        return False

    def bundle_from(self, seed, others):
        p = self.p
        cands = []
        for r in self.robots:
            if not r.idle or r.fatigue < p.fatigue_per_room:
                continue
            if r.fatigue <= p.pharmacy_min_fatigue:
                continue
            cands.append((self.g.dist(r.node, PHARMACY), r))
        for _, r in sorted(cands, key=lambda c: c[0]):
            cap, start = p.cap, PHARMACY
            prefix = [dict(kind='wait_ready'), dict(kind='move', to=PHARMACY), dict(kind='dock'), dict(kind='load')]
            bundle, here = [seed], seed.room
            first = self.visit_steps(start, [seed.room], r.contam)
            if first is None or not self.feasible(r, prefix + first, include_current=False):
                continue
            rest = list(others)
            while len(bundle) < cap and rest:
                rest.sort(key=lambda o: self.g.dist(here, o.room))
                for o in rest:
                    trial = self.visit_steps(start, [b.room for b in bundle] + [o.room], r.contam)
                    if trial is not None and self.feasible(r, prefix + trial, include_current=False):
                        bundle.append(o)
                        rest.remove(o)
                        here = o.room
                        break
                else:
                    break
            steps = prefix + self.visit_steps(start, [b.room for b in bundle], r.contam)
            r.loaded_done = False
            rooms = [s['room'] for s in steps if s['kind'] == 'spin']
            b = Batch(r, bundle, rooms, self.t)
            self.batches.append(b)
            for s in steps:
                if s['kind'] in ('wait_ready', 'load'):
                    s['batch'] = b
            for o in bundle:
                o.state, o.robot, o.batch = 'assigned', r.id, b
            r.assigned, r.batch = list(bundle), b
            self.emit('batch_assigned', batch_id=b.bid, robot=r.num, name=r.name,
                      orders=[dict(order_id=o.oid, room=room_code(o.room), item=o.item) for o in bundle],
                      count=len(bundle), rooms=[room_code(x) for x in rooms])
            self.start_task(r, 'delivery', steps, f'배송 {b.bid} {[f"#{o.id} {o.room}" for o in bundle]} (OMX 준비 기다림)')
            return True
        return False

    def start_task(self, r, kind, steps, why):
        r.task = kind
        r.queue = list(steps)
        self.log(f'{r.id}: {why}')
        self.next_step(r)

    # ---- 단계 진행 ----
    def next_step(self, r):
        r.step = r.queue.pop(0) if r.queue else None
        r.timer = 0.0
        if r.step is None:
            if r.task == 'delivery':
                self.log(f'{r.id}: 배송 끝')
            r.task, r.batch = None, None
            return
        k = r.step['kind']
        if k == 'move':
            self.next_step_init_move(r)
            if r.step['to'] != r.node:
                to = r.step['to']
                self.emit('robot_departed', robot=r.num, task=self.task_name(r), **{'from': r.node},
                          to=dict(node=to, room=room_or_none(to)))
        elif k == 'load':
            b = r.step.get('batch')
            if b:
                b.status, b.status_t = 'at_pharmacy', self.t
                self.emit('robot_at_pharmacy', batch_id=b.bid, robot=r.num)
            self.log(f'{r.id} → 관제 PC: 약제실 정밀 주차 끝 (적재 기다림)')

    def other_holds(self, r):
        nodes, edges, zones, lanes = {}, set(), {}, []
        for o in self.robots:
            if o is r:
                continue
            n, e, z = o.holds()
            for x in n:
                nodes[x] = o
            edges |= e
            for x in z:
                zones[x] = o
            for (a, b) in e:
                if self.g.edge[(a, b)]['lane']:
                    lanes.append((o, a, b))
            for x in n:
                if self.g.is_lane(x):
                    lanes.append((o, x, x))
        return nodes, edges, zones, lanes

    def begin_move(self, r):
        """목적지가 막다른 곳(병실·약제실·POCKET·충전)이면 그 zone 을 먼저 잡는다. 못 잡으면 지금 자리에서 기다림"""
        to = r.step['to']
        if to == r.node:
            return True
        dz = self.g.stop_zones(to) | set(r.step.get('also', ()))     # 충전하러 가면 POCKET 들르기 전에 충전기 자리도
        nodes, _, zones, _ = self.other_holds(r)
        busy = [z for z in dz if z in zones]
        if busy:
            self.waiting(r, f'{to} 차례 기다림 ({zones[busy[0]].id})', [zones[busy[0]]])
            return False
        for o in self.robots:                   # 같은 구역을 더 오래 기다린 로봇이 먼저
            if o is r or not (o.step and o.step['kind'] == 'move' and not o.step.get('started')):
                continue
            if self.dest_zones_of(o) & dz and o.wait_s > r.wait_s + 1e-9:
                self.waiting(r, f'{to} 차례 기다림 ({o.id} 먼저)', [o])
                return False
        for o in self.robots:                   # 그 구역 안쪽 막다른 곳(예: POCKET 뒤 CHARGER)에 있는 로봇이 먼저 나온다
            if o is not r and self.trapped_behind(o.node, dz):
                self.waiting(r, f'{to} 차례 기다림 ({o.id} 나오는 중)', [o])
                return False
        for o in self.robots:                   # 그 구역을 지나가야 하는 로봇이 이미 출발했으면 먼저 보낸다
            if o is r or not (o.step and o.step['kind'] == 'move' and o.step.get('started') and o.path):
                continue
            rest = o.path[o.k:]
            if any(self.g.edge[(rest[i], rest[i + 1])]['zone'] in dz for i in range(len(rest) - 1)):
                self.waiting(r, f'{to} 차례 기다림 ({o.id} 지나가는 중)', [o])
                return False
        if not self.trapped_behind(r.node, self.g.stop_zones(r.node) | {self.g.edge[(r.node, m)]['zone'] for m in self.g.adj[r.node]}):
            self.plan(r)                        # 막다른 곳에 갇힌 게 아니면: 오래(15초+) 기다리는 로봇의 목적지 구역을 지나가는 이동은 보류
            if r.path:
                pz = {self.g.edge[(r.path[i], r.path[i + 1])]['zone'] for i in range(len(r.path) - 1)}
                for o in self.robots:
                    if o is r or not (o.step and o.step['kind'] == 'move' and not o.step.get('started')) or o.wait_s < 15.0:
                        continue
                    if self.dest_zones_of(o) & pz - dz:
                        self.waiting(r, f'{o.id} 가 오래 기다리는 구역이라 보류', [o])
                        return False
        r.dest_zones = dz
        r.wait_s, r.wait_why, r.blocked_by = 0.0, '', set()
        self.plan(r)
        r.step['started'] = True
        if r.path is not None:
            self.replan_all(f'{r.id} 출발')
        return r.path is not None

    def dest_zones_of(self, o):
        return self.g.stop_zones(o.step['to']) | set(o.step.get('also', ()))

    def trapped_behind(self, n, zones):
        """n 에서 zones 의 엣지를 안 지나면 차선(복도)에 못 나가는가"""
        if not zones or self.g.is_lane(n):
            return False
        seen, stack = {n}, [n]
        while stack:
            u = stack.pop()
            for w in self.g.adj[u]:
                if w in seen or self.g.edge[(u, w)]['zone'] in zones:
                    continue
                if self.g.is_lane(w):
                    return False
                seen.add(w)
                stack.append(w)
        return True

    ACT_KINDS = ('wait_ready', 'dock', 'load', 'spin', 'pause', 'dwell', 'charge')
    PLAN_LEGS = 2                  # CBS 가 내다보는 목적지 수 (지금 목적지 + 다음 목적지)

    def act_time(self, s, elapsed=0.0):
        """작업 단계 시간 (초). 적재는 관제 PC/OMX 를 기다리므로 예상값"""
        p = self.p
        t = {'dock': p.dock_s, 'load': p.load_s, 'spin': p.spin_s, 'dwell': p.dwell_s, 'charge': p.charge_s,
             'pause': s.get('dur', sum(p.pause_s) / 2), 'wait_ready': p.prep_s}[s['kind']]
        return max(1.0, t - elapsed)

    def legs_for(self, r, first_goal, first_dwell, seq):
        """[(목적지, 머무는 칸, 그 구간 동안 실음)] — 목적지에서 할 작업 시간을 머무는 칸으로. 마지막 목적지는 INF"""
        p, step = self.p, self.p.plan_step
        load, assigned = r.load, list(r.assigned)
        legs, goal, dwell, lo = [], first_goal, first_dwell, r.loaded
        more = False
        for s in seq:
            if s['kind'] == 'move':
                if len(legs) + 1 >= self.PLAN_LEGS:       # 더 내다보지 않음: 이 목적지에서 작업만큼 머문 뒤 계획에서 빠짐
                    more = True
                    break
                legs.append([goal, dwell, lo])
                goal, dwell, lo = s['to'], 0.0, load > 0
            else:
                dwell += self.act_time(s)
                if s['kind'] == 'load':
                    load = max(load, len(assigned))
                elif s['kind'] == 'spin':
                    load -= sum(1 for o in assigned if o.room == s['room'])
                    assigned = [o for o in assigned if o.room != s['room']]
        legs.append([goal, dwell if more else INF, lo])     # 그 뒤 이동이 없으면 계속 거기 있음
        return [(gl, INF if d >= INF else max(1, math.ceil(d / step)), lo_) for gl, d, lo_ in legs]

    def replan_all(self, why=''):
        """CBS 로 다시 계획. 움직이는 로봇 = 지금 목적지 + 거기서 머무는 시간 + 다음 목적지.
        작업 중(정밀 주차·적재·회전·POCKET·충전)이고 다음 이동이 정해진 로봇 = 남은 작업 시간 뒤 다음 목적지로 (계획만, 실행은 출발 때 다시).
        그 밖의 서 있는 로봇 = 끝까지 그 자리"""
        if self.p.planner != 'cbs':
            return
        g, step, now = self.g, self.p.plan_step, self.t
        agents, statics, movers = [], [], {}
        for r in self.robots:
            if r.link and r.drive and r.drive['kind'] == 'drive' and not r.fault:
                # 실제 로봇이 묶음을 달리는 중: 묶음 끝 노드에서 시작, 남은 묶음 엣지는 그동안 차지 (고정)
                j = r.drive['j']
                rest = r.path[r.k:j + 1]
                left = sum(g.edge_s(rest[i], rest[i + 1], self.p.speed) for i in range(len(rest) - 1))
                if r.edge_t > 0:
                    left -= r.edge_t / g.edge[(rest[0], rest[1])]['L'] * g.edge_s(rest[0], rest[1], self.p.speed)
                t0 = max(1, math.ceil(max(0.0, left) / step))
                agents.append(dict(id=r.id, loaded=r.loaded, wait=r.wait_s, start=rest[-1], t0=t0,
                                   heading=g.heading(rest[-2], rest[-1]) if len(rest) > 1 else r.heading,
                                   legs=self.legs_for(r, r.step['to'], 0.0, r.queue),
                                   prefix=[Item(g, 'edge', (rest[i], rest[i + 1]), 0, t0, r.loaded, r.id, fixed=True)
                                           for i in range(len(rest) - 1)]))
                movers[r.id] = r
                continue
            moving = (r.step and r.step['kind'] == 'move' and r.step.get('started') and r.path
                      and r.k < len(r.path) - 1)
            busy = (r.step and r.step['kind'] in self.ACT_KINDS and any(s['kind'] == 'move' for s in r.queue))
            if moving:
                a = dict(id=r.id, loaded=r.loaded, wait=r.wait_s, heading=r.heading,
                         legs=self.legs_for(r, r.step['to'], 0.0, r.queue))
                if r.edge_t > 0:
                    u, v = r.path[r.k], r.path[r.k + 1]
                    left = (1 - r.edge_t / g.edge[(u, v)]['L']) * g.edge_s(u, v, self.p.speed)   # 남은 실측 시간
                    t0 = max(1, math.ceil(left / step))
                    a.update(start=v, t0=t0, heading=g.heading(u, v),
                             prefix=[Item(g, 'edge', (u, v), 0, t0, r.loaded, r.id, fixed=True)])
                else:
                    a.update(start=r.node, t0=0)
                agents.append(a)
                movers[r.id] = r
            elif busy:
                legs = self.legs_for(r, r.node, self.act_time(r.step, r.timer), r.queue)
                agents.append(dict(id=r.id, loaded=r.loaded, wait=0.0, start=r.node, t0=0, legs=legs, plan_only=True,
                                   heading=r.heading))
            else:
                statics.append(Item(g, 'node', r.node, 0, INF, r.loaded, r.id, zones=r.holds()[2]))
        if not movers:
            return
        plans = self.planner.solve(agents, statics)
        st = self.plan_stats
        st['replans'] += 1
        st[self.planner.last['mode']] += 1
        st['last'] = dict(self.planner.last, why=why, t=round(now, 1))
        legs_of = {a['id']: a['legs'] for a in agents}
        self.last_plans = {}                    # 화면용 예정표: 목적지마다 도착·떠날 시각
        for rid, p_ in plans.items():
            lg = legs_of[rid]
            self.last_plans[rid] = [dict(node=n, arrive=round(now + ta * step, 1),
                                         leave=None if td >= INF else round(now + td * step, 1))
                                    for n, ta, td, li, _ in p_ if li < len(lg) and n == lg[li][0]]
        for rid, r in movers.items():
            plan = plans.get(rid)
            if plan is None:
                st['failed'] += 1
                if not (r.link and r.drive):
                    r.depart = None             # 못 풀면 최단 경로 + 예약으로 (예전 방식)
                continue
            goal0 = r.step['to']
            end = next(i for i, e in enumerate(plan) if e[0] == goal0 and e[3] == 0)
            plan = plan[:end + 1]               # 실행은 이번 목적지까지 (그 뒤는 다른 로봇 계획용 예측)
            nodes = [e[0] for e in plan]
            dep = [now + e[2] * step if e[2] < INF else INF for e in plan]
            dep[-1] = INF
            if r.link and r.drive and r.drive['kind'] == 'drive':    # 달리는 묶음은 그대로, 그 뒤만 바꿈
                j = r.drive['j']
                r.path, r.depart = r.path[:j] + nodes, [now] * j + dep
                continue
            if r.edge_t > 0:
                nodes, dep = [r.path[r.k]] + nodes, [now] + dep
            r.path, r.depart = nodes, dep
            r.k = 0
            r.res_to = 1 if r.edge_t > 0 else 0         # 지나는 중인 엣지만 남기고 예약은 출발 시각에 다시
            r.extra_nodes = set()

    def plan(self, r, penalize=False):
        to = r.step['to']
        nodes, _, zones, _ = self.other_holds(r) if penalize else ({}, None, {}, None)

        def busy(a, b):                       # 다른 로봇이 잡은 노드·zone 벌점
            e = self.g.edge[(a, b)]
            return (400.0 if b in nodes else 0.0) + (300.0 if e['zone'] in zones and self.g.cap1(e['zone']) else 0.0)
        p = self.g.path(r.node, to, busy if penalize else None)
        if p is None:
            self.log(f'{r.id}: {to} 로 가는 길 없음', 'violation')
            r.path = None
            return
        r.path, r.k, r.res_to, r.edge_t = p, 0, 0, 0.0

    def chunk(self, r):
        """다음 예약 덩어리: 차선 노드(멈춰도 되는 곳) 또는 목적지까지.
        CBS 계획을 따를 때는 다음 엣지 하나 (통과 순서는 CBS 가 시간으로 맞추고, 예약은 바로 앞 안전만 본다)"""
        if r.depart is not None:
            return r.k + 1
        j = r.k
        while True:
            j += 1
            if j == len(r.path) - 1 or self.g.is_lane(r.path[j]):
                return j

    def occupancy(self, o):
        """o 가 지금 실제로 차지한 자리 (CBS 와 같은 Item): 서 있는 노드, 지나는·예약한 엣지"""
        g = self.g
        out = [Item(g, 'node', o.node, 0, 0, o.loaded, o.id)]
        if o.step and o.step['kind'] == 'move' and o.path:
            for i in range(o.k, min(o.res_to, len(o.path) - 1)):
                out.append(Item(g, 'edge', (o.path[i], o.path[i + 1]), 0, 0, o.loaded, o.id))
                out.append(Item(g, 'node', o.path[i + 1], 0, 0, o.loaded, o.id))
        if o.depart is None:                     # 예전 방식 로봇은 붙잡은 zone 도
            z = o.holds()[2] - o.dest_zones
            if z:
                out.append(Item(g, 'node', o.node, 0, 0, o.loaded, o.id, zones=z))
        return out

    def try_reserve_cbs(self, r):
        """CBS 계획을 따르는 로봇: 다음 엣지 하나가 지금 다른 로봇과 부딪히지 않으면 간다 (CBS 와 같은 충돌 기준)"""
        g = self.g
        a, b = r.path[r.k], r.path[r.k + 1]
        mine = [Item(g, 'edge', (a, b), 0, 0, r.loaded, r.id), Item(g, 'node', b, 0, 0, r.loaded, r.id)]
        blockers = []
        for o in self.robots:
            if o is r:
                continue
            if any(space_conflict(g, X, Y, NEAR_CM) for X in mine for Y in self.occupancy(o)):
                blockers.append(o)
        if blockers:
            self.waiting(r, '길 막힘', blockers)
            return False
        r.res_to = r.k + 1
        r.extra_nodes = set()
        r.wait_s, r.wait_why, r.blocked_by = 0.0, '', set()
        return True

    def try_reserve(self, r):
        if r.depart is not None:
            return self.try_reserve_cbs(r)
        g = self.g
        j = self.chunk(r)
        seg = r.path[r.k:j + 1]
        edges = [(seg[i], seg[i + 1]) for i in range(len(seg) - 1)]
        need_nodes = set(seg[1:])
        for e in edges:
            need_nodes |= set(g.crossed.get(e, [])) | g.seg_near[e]
        for n in list(need_nodes):                    # 너무 가까운 노드도 비어 있어야
            need_nodes |= g.near[n]
        need_nodes.discard(r.node)
        need_zones = {g.edge[e]['zone'] for e in edges if g.cap1(g.edge[e]['zone'])}
        nodes, oedges, zones, lanes = self.other_holds(r)
        blockers = [nodes[n] for n in need_nodes if n in nodes] + [zones[z] for z in need_zones if z in zones]
        why = ''
        if blockers:
            why = '길 막힘'
        elif r.loaded:                                          # 실은 로봇끼리 교행통로에서 나란히/엇갈림 금지
            for (a, b) in edges:
                lane = g.edge[(a, b)]['lane'] or g.nodes[b].get('lane')    # 차선 위, 또는 차선으로 들어오는 엣지
                if not lane:
                    continue
                x0, x1 = g.x_range(a, b) if g.edge[(a, b)]['lane'] else (g.xy(b)[0],) * 2
                for o, c, d in lanes:
                    if not o.loaded:
                        continue
                    ol = g.nodes[c]['lane'] if c == d else g.edge[(c, d)]['lane']
                    if not ol or ol[0] != lane[0] or ol == lane:
                        continue
                    y0, y1 = g.x_range(c, d)
                    if min(x1, y1) - max(x0, y0) > -NEAR_CM:     # 끝점에서 나란히 서는 것도 막음
                        blockers.append(o)
                        why = f'교행 금지 (실은 {o.id})'
        if blockers or why:
            self.waiting(r, why or '길 막힘', blockers)
            return False
        r.res_to = j
        r.extra_nodes = set()
        for e in edges:
            r.extra_nodes |= set(g.crossed.get(e, [])) | g.seg_near[e]
        r.extra_nodes -= {r.node}
        r.wait_s, r.wait_why = 0.0, ''
        r.blocked_by = set()
        return True

    def waiting(self, r, why, blockers):
        dt = self._dt
        r.wait_s += dt
        r.wait_why = why
        r.blocked_by = set(blockers)
        for o in blockers:                                      # 노는 로봇이 막으면 비켜 주기
            if o.idle and o.task is None:
                avoid = set(r.path or []) | {r.step['to'], o.node} | self.g.near[r.step['to']]
                spot = self.free_parking(o, set(), avoid)
                if spot is None:
                    spot = next((n for n in self.g.nodes if self.g.is_lane(n) and n not in avoid
                                 and n not in {x.node for x in self.robots} and not (self.g.near[n] & avoid)), None)
                if spot:
                    self.start_task(o, 'yield', [dict(kind='move', to=spot)], f'{r.id} 에게 비켜 줌 → {spot}')
            elif (o.step and o.step['kind'] == 'move' and not o.step.get('started') and not o.step.get('sidestep')
                  and o.wait_s > 1.0 and r.wait_s > 1.0):
                # 차례를 기다리느라 서 있는 로봇(아직 출발 전)이 길을 막으면 그 로봇도 비킨다.
                # 10-29: R2 가 약제실 차례를 T2_190 (POCKET 으로 가는 유일한 길)에서 기다리고, 약제실의 R1 은 102호의 R3 를,
                # R3 는 POCKET 으로 가려고 R2 를 기다림 → 실측 시간(더 느림)에서 영구 교착 (R1 은 CBS 출발 시각 대기라 교착 검사에 안 걸림)
                found = self.sidestep_spot(o, [x for x in self.robots if x is not o])
                if found:
                    self.log(f'{o.id} 가 차례 기다리다 {r.id} 길을 막음 → {found[0]} 로 비킴', 'warn')
                    o.queue.insert(0, dict(o.step, started=False))
                    o.step = dict(kind='move', to=found[0], sidestep=True)
                    self.next_step_init_move(o)
        if r.step['started'] and r.wait_s - r.replan_t > self.p.replan_s:   # 다른 길 찾아보기
            r.replan_t = r.wait_s
            if self.p.planner == 'cbs':
                self.replan_all(f'{r.id} 예약 막힘')
            elif r.edge_t == 0.0 and r.res_to <= r.k:
                self.plan(r, penalize=True)

    REATTACH = ('unreachable', 'not_localized', 'not_at_node', 'rebooted')

    def check_real(self, r):
        """실제 로봇: 재부팅 알아채기, 붙지 못한(또는 쉬다가 재부팅한) 로봇은 준비되면 자동으로 다시 붙이기"""
        L = r.link
        if not L.alive():
            return
        boot = (L.st.get('robot') or {}).get('boot_id')
        if not r.fault and r.boot and boot and boot != r.boot:
            self.real_fault(r, 'rebooted', '로봇이 재부팅됨 — 위치를 믿을 수 없음. 노드에 놓고 /set_pose')
            return
        if (r.fault and r.fault['code'] in self.REATTACH and r.step is None and not r.queue
                and self.t - r.reattach_t > 2.0):
            r.reattach_t = self.t
            if L.st.get('pose_confirmed') is not False:
                self.attach_real(r, L)

    def tick_robot(self, r, dt):
        p, s = self.p, r.step
        if r.link:
            self.check_real(r)
        if s is None or r.fault:
            return
        k = s['kind']
        if r.link and k in ('dock', 'spin'):
            self.tick_real_act(r, k)
            return
        if k == 'move':
            if not s['started']:
                if not self.begin_move(r):
                    return
            if r.path is None:
                self.next_step(r)
                return
            if r.link:
                self.tick_real_move(r)
                return
            tt = dt                                     # 이번 틱에 쓸 수 있는 시간 s (엣지마다 실측 속도로 움직임)
            r.plan_wait = False
            while tt > 1e-9:
                if r.k >= len(r.path) - 1:
                    break
                if r.edge_t == 0 and r.depart is not None and self.t < r.depart[r.k] - 1e-9:
                    r.plan_wait = True                  # CBS 가 정한 출발 시각까지 기다림 (제자리 회전 시간도 여기 들어 있음)
                    break
                if r.res_to <= r.k and not self.try_reserve(r):
                    break
                a, b = r.path[r.k], r.path[r.k + 1]
                if r.edge_t == 0 and r.depart is None:  # CBS 시각이 없으면 엣지 방향으로 도는 시간을 직접
                    if r.turn_left is None:
                        r.turn_left = self.g.rot_s(r.heading, self.g.heading(a, b))
                    use = min(tt, r.turn_left)
                    r.turn_left -= use
                    tt -= use
                    if r.turn_left > 1e-9:
                        break
                L = self.g.edge[(a, b)]['L']
                v = L / self.g.edge_s(a, b, p.speed)    # cm/s
                d = min(v * tt, L - r.edge_t)
                r.edge_t += d
                r.since += d
                tt -= d / v
                r.heading = self.g.heading(a, b)
                if r.edge_t >= L - 1e-9:
                    r.k += 1
                    r.edge_t = 0.0
                    r.turn_left = None
                    r.prev_node, r.since = a, 0.0
                    r.node = b
                    if r.k >= r.res_to:
                        r.extra_nodes = set()
            a = r.path[r.k]
            if r.k < len(r.path) - 1 and r.edge_t > 0:
                b = r.path[r.k + 1]
                f = r.edge_t / self.g.edge[(a, b)]['L']
                (xa, ya), (xb, yb) = self.g.xy(a), self.g.xy(b)
                r.pos = (xa + (xb - xa) * f, ya + (yb - ya) * f)
                r.heading = math.degrees(math.atan2(yb - ya, xb - xa))
            else:
                r.pos = self.g.xy(a)
            if r.k >= len(r.path) - 1:
                self.arrive(r)
        elif k == 'dock':
            r.timer += dt
            if r.timer >= p.dock_s:
                self.next_step(r)
        elif k == 'wait_ready':                         # 배차됨, 관제 PC 의 ready(OMX 준비 끝) 기다림 — 제자리
            r.timer += dt
            b = s.get('batch')
            if b and b.status == 'assigned' and p.auto_omx and self.t - b.status_t >= p.prep_s:
                self.batch_ready(b)                     # 가상 관제 PC
            if b is None or b.status != 'assigned':
                self.next_step(r)
        elif k == 'load':
            r.timer += dt
            b = s.get('batch')
            if b and b.status == 'at_pharmacy' and p.auto_omx and self.t - b.status_t >= p.load_s:
                self.batch_loaded(b)                    # 가상 관제 PC/OMX 가 적재 완료를 보냄
            if b is None or b.status == 'delivering':
                n = max(0, len(r.assigned) - r.load)
                r.load += n
                r.loaded_done = True
                for o in r.assigned:
                    o.state = 'loaded'
                self.log(f'{r.id}: 적재 {n}개 (실림 {r.load}, 주문 {len(r.assigned)}) → 병실로')
                self.next_step(r)
        elif k == 'spin':
            r.timer += dt
            if r.timer >= p.spin_s:
                self.finish_spin(r, s)
        elif k == 'pause':
            r.timer += dt
            if r.timer >= s['dur']:
                self.next_step(r)
        elif k == 'dwell':
            r.timer += dt
            if r.timer >= p.dwell_s:
                r.contam = 0
                self.log(f'{r.id}: POCKET 5초 → 오염도 0')
                self.next_step(r)
        elif k == 'charge':
            r.timer += dt
            if r.timer >= p.charge_s:
                r.fatigue = 100
                self.log(f'{r.id}: 충전 끝 → 100')
                self.next_step(r)

    # ---- 실제 로봇 (robot_link.HttpLink) — 설계: FMS ↔ Pinky 주행 API 설계 문서 (10-29) ----
    def attach_real(self, r, link):
        """실제 로봇 붙이기: 시작 노드·자세 = 로봇 /status 의 drive.node·pose"""
        prev = (r.fault or {}).get('code')       # 같은 이유로 다시 안 되면 로그를 되풀이하지 않음
        r.link, r.fault = link, None
        if not link.wait_status():
            r.fault = dict(code='unreachable', why=f'{link.url} /status 없음 ({link.err})', t=self.t, node=r.node, edge=None)
            if prev != r.fault['code']:
                self.log(f'{r.id} ({r.name}): 로봇 API 안 됨 — {link.err}', 'violation')
            return
        want = next((row.get('serial') for row in ROBOT_TABLE if row.get('name') == r.name), None)
        got = ((link.st or {}).get('robot') or {}).get('serial')
        if want and got and want != got:          # IP 가 바뀌어 다른 로봇에 붙음
            r.fault = dict(code='wrong_robot', why=f'{link.url} 는 시리얼 {got} (표: {want})', t=self.t, node=r.node, edge=None)
            if prev != r.fault['code']:
                self.log(f'{r.id} ({r.name}): {link.url} 는 다른 로봇 (시리얼 {got}) — robots.yaml url 확인', 'violation')
            return
        if link.st.get('pose_confirmed') is False:   # 재부팅·Nav2 재시작 뒤 /set_pose 안 함 → 초기 위치(A)를 믿으면 안 됨 (10-30)
            r.fault = dict(code='not_localized', why='로봇 위치 확인 안 됨 — 노드에 놓고 로봇 /set_pose', t=self.t, node=r.node, edge=None)
            if prev != r.fault['code']:
                self.log(f'{r.id} ({r.name}): 위치 확인 안 됨 — 노드에 놓고 /set_pose 하면 자동으로 붙음', 'warn')
            return
        r.boot = (link.st.get('robot') or {}).get('boot_id')
        d, pose = link.drive_status(), link.pose()
        node = d and d.get('node')
        if node == PHARMACY_DOCK:
            node, r.at_dock = PHARMACY, True
        if node not in self.g.nodes:
            r.fault = dict(code='not_at_node', why=f'로봇이 노드 위에 있지 않음 (pose {pose})', t=self.t, node=None, edge=None)
            if prev != r.fault['code']:
                self.log(f'{r.id} ({r.name}): 노드 위에 있지 않음 {pose} — 노드에 올리고 다시 시작', 'violation')
            return
        r.node, r.pos = node, self.g.xy(node)
        if pose:
            r.heading = pose['heading'] % 360
        self.log(f'{r.id} = 실제 로봇 {r.name} ({link.url}) at {node}')

    def real_sync_pos(self, r):
        pose = r.link.pose()
        if pose:
            r.pos, r.heading = (pose['x'], pose['y']), pose['heading'] % 360

    def real_fault(self, r, code, why=None):
        """실제 로봇 실패: 그 자리(지나던 엣지 포함)를 계속 차지한 채 멈춤. 관제 PC 에 robot_error, 다른 로봇은 다시 계획"""
        edge = [r.path[r.k], r.path[r.k + 1]] if r.edge_t > 0 and r.path and r.k < len(r.path) - 1 else None
        r.fault = dict(code=code, why=why, t=round(self.t, 1), node=None if edge else r.node, edge=edge)
        r.drive = None
        self.log(f'{r.id} ({r.name}) 실패: {code} {why or ""} @ {edge or r.node}', 'violation')
        self.emit('robot_error', robot=r.num, name=r.name, code=code, why=why, node=r.fault['node'], edge=edge,
                  task=self.task_name(r), batch_id=r.batch.bid if r.batch else None)
        self.replan_all(f'{r.id} 실패')

    def clear_fault(self, r):
        """사람이 로봇을 확인한 뒤: 실패 표시를 지우고 이어서 (엣지 중간이면 다음 /drive 가 "@here" 로 마저 감)"""
        if r.fault:
            self.log(f'{r.id}: 실패 표시 지움 ({r.fault["code"]}) → 이어서')
            r.fault = None
            r.wait_s = r.replan_t = 0.0

    def real_chunk(self, r):
        """CBS 계획을 따르는 실제 로봇이 이번에 보낼 묶음의 끝 index: 다음 대기 지점(계획상 도착보다 늦게 떠나는 노드)까지,
        지금 다른 로봇이 차지한 자리와 부딪히는 엣지 앞까지. 첫 엣지부터 막히면 None (기다림)"""
        g, path, now = self.g, r.path, self.t
        others = [(o, self.occupancy(o)) for o in self.robots if o is not r]
        T, h, j = 0.0, r.heading, r.k
        for i in range(r.k, len(path) - 1):
            a, b = path[i], path[i + 1]
            mine = [Item(g, 'edge', (a, b), 0, 0, r.loaded, r.id), Item(g, 'node', b, 0, 0, r.loaded, r.id)]
            hit = [o for o, occ in others if any(space_conflict(g, X, Y, NEAR_CM) for X in mine for Y in occ)]
            if hit:
                if i == r.k:
                    self.waiting(r, '길 막힘', hit)
                    return None
                break
            T += g.rot_s(h, g.heading(a, b)) + g.edge_s(a, b, self.p.speed)
            h = g.heading(a, b)
            j = i + 1
            if j < len(path) - 1 and r.depart[j] < INF and r.depart[j] > now + T + 2.0:
                break                           # 여기서 기다려야 함 (계획상 늦게 떠남) → 묶음 끝
        r.wait_s, r.wait_why, r.blocked_by = 0.0, '', set()
        return j

    def tick_real_move(self, r):
        L, d = r.link, r.drive
        if not L.alive():
            if not r.link_lost:
                r.link_lost = True
                self.log(f'{r.id} ({r.name}): /status 끊김 — 마지막 자리를 계속 차지한 것으로 봄', 'warn')
            return
        r.link_lost = False
        if d is None:                           # 다음 묶음 보내기
            if r.k >= len(r.path) - 1:
                self.arrive(r)
                return
            if r.depart is not None and self.t < r.depart[r.k] - 1e-9:
                r.plan_wait = True              # CBS 출발 시각까지 기다림
                return
            r.plan_wait = False
            if r.depart is not None:
                j = self.real_chunk(r)
                if j is None:
                    return
                r.res_to = j
                r.extra_nodes = set()
            else:                               # CBS 못 풂 → 예전 방식 (차선 노드까지 예약)
                if r.res_to <= r.k and not self.try_reserve(r):
                    return
                j = r.res_to
            route, extra = list(r.path[r.k:j + 1]), 0
            if r.edge_t > 0:                    # 엣지 중간에 멈췄던 로봇 → 그 엣지 끝까지 마저
                route[0] = '@here'
            elif r.at_dock and route[0] == PHARMACY:
                route, extra = [PHARMACY_DOCK] + route, 1      # 정밀 주차 자리에서 먼저 물러나기
            nxt = r.path[j + 1] if j + 1 < len(r.path) else None
            r.drive = dict(cid=L.drive(route, nxt), kind='drive', k0=r.k, j=j, extra=extra, t=self.t, late=set())
            self.log(f'{r.id} → {r.name}: /drive {route}' + (f' (다음 {nxt})' if nxt else ''))
            return
        res = L.result(d['cid'])
        if res is not None and res[0] not in (200, 202):
            self.real_fault(r, (res[1] or {}).get('error', f'http_{res[0]}'), (res[1] or {}).get('why'))
            return
        st = L.drive_status(d['cid'])
        if st is None:
            if self.t - d['t'] > 10.0:
                self.real_fault(r, 'no_ack', '/drive 를 보냈는데 로봇 상태에 그 명령이 안 보임')
            return
        done = len(st['done_edges']) - d['extra']
        if st['done_edges'] and d['extra']:
            r.at_dock = False
        newk = d['k0'] + max(0, done)
        while r.k < min(newk, d['j']):          # 끝난 엣지만큼 앞으로
            r.prev_node, r.since = r.path[r.k], 0.0
            r.k += 1
            r.node, r.edge_t = r.path[r.k], 0.0
        e = st.get('edge')
        if e and st['state'] == 'driving' and r.k < len(r.path) - 1 and e[1] == r.path[r.k + 1]:
            r.edge_t = (st.get('edge_progress') or 0.0) * self.g.edge[(r.path[r.k], r.path[r.k + 1])]['L']
        self.real_sync_pos(r)
        el, ex = st.get('edge_elapsed_s'), st.get('edge_expected_s')
        if e and el and ex and el > LATE_X * ex + 2.0 and tuple(e) not in d['late']:
            d['late'].add(tuple(e))
            self.log(f'{r.id} ({r.name}) 늦음: {e[0]}→{e[1]} {el:.0f}s (예상 {ex:.0f}s) → 다시 계획', 'warn')
            self.replan_all(f'{r.id} 늦음')
        if st['state'] == 'done':
            r.k, r.edge_t, r.drive = d['j'], 0.0, None
            r.node, r.res_to = r.path[r.k], r.k
            if r.k >= len(r.path) - 1:
                self.arrive(r)
        elif st['state'] in ('failed', 'canceled'):
            err = st.get('error') or {}
            self.real_fault(r, err.get('code', st['state']), err.get('why'))

    def tick_real_act(self, r, k):
        """정밀 주차 (PHARMACY → PHARMACY_DOCK 엣지) · 병실 360° 회전 (/action spin)"""
        L, d = r.link, r.drive
        if not L.alive():
            return
        if d is None:
            cid = L.drive([PHARMACY, PHARMACY_DOCK]) if k == 'dock' else L.action('spin')
            r.drive = dict(cid=cid, kind=k, t=self.t)
            self.log(f'{r.id} → {r.name}: ' + ('정밀 주차' if k == 'dock' else '/action spin'))
            return
        res = L.result(d['cid'])
        if res is not None and res[0] not in (200, 202):
            self.real_fault(r, (res[1] or {}).get('error', f'http_{res[0]}'), (res[1] or {}).get('why'))
            return
        st = L.drive_status(d['cid'])
        r.timer = self.t - d['t']
        self.real_sync_pos(r)
        if st is None:
            if r.timer > 10.0:
                self.real_fault(r, 'no_ack', f'{k} 명령을 보냈는데 로봇 상태에 안 보임')
            return
        if st['state'] == 'done':
            r.drive = None
            if k == 'dock':
                r.at_dock = True
                self.next_step(r)
            else:
                self.finish_spin(r, r.step)
        elif st['state'] in ('failed', 'canceled'):
            err = st.get('error') or {}
            self.real_fault(r, err.get('code', st['state']), err.get('why'))

    def finish_spin(self, r, s):
        """병실 360° 회전 끝 = 배송 완료 (시뮬레이션·실제 로봇 같이)"""
        p = self.p
        done = [o for o in r.assigned if o.room == s['room']]
        for o in done:
            o.state, o.done_t, o.delivered_at = 'delivered', self.t, self.stamp()
            r.assigned.remove(o)
            r.load -= 1
            self.stats['delivered'] += 1
            self.emit('order_delivered', order_id=o.oid, room=room_code(o.room), robot=r.num,
                      batch_id=o.batch.bid if o.batch else None)
        b = r.batch
        if b and b.status != 'completed' and all(o.state == 'delivered' for o in b.orders):
            b.status, b.status_t = 'completed', self.t
            self.emit('batch_completed', batch_id=b.bid, robot=r.num)
        r.fatigue -= p.fatigue_per_room
        if r.load < 0 or r.fatigue < 0:
            self.log(f'{r.id}: 적재 {r.load} / 피로도 {r.fatigue} 음수', 'violation')
        self.log(f'{r.id}: {s["room"]} 배송 완료 {[f"#{o.id}" for o in done]} → 관제 PC (피로도 {r.fatigue})')
        r.step = dict(kind='pause', dur=self.rng.uniform(*p.pause_s))   # 한 바퀴 뒤 1~5초 쉬고 다음 일
        r.timer = 0.0

    def arrive(self, r):
        to = r.step['to']
        r.node, r.pos = to, self.g.xy(to)
        r.path, r.k, r.res_to, r.edge_t = [to], 0, 0, 0.0
        r.dest_zones, r.extra_nodes = set(), set()
        r.wait_s, r.wait_why, r.blocked_by = 0.0, '', set()
        r.depart, r.plan_wait = None, False
        if to == PHARMACY and r.fatigue <= self.p.pharmacy_min_fatigue:
            self.log(f'{r.id}: 피로도 {r.fatigue} 로 약제실 도착', 'violation')
        self.emit('robot_arrived', robot=r.num, node=to, room=room_or_none(to))
        if to in ROOM_CONTAM and r.step.get('visit'):
            if to == SURGERY and r.contam > 0:
                self.log(f'{r.id}: 오염도 {r.contam} 로 수술실 진입', 'violation')
            r.contam += ROOM_CONTAM[to]
            if r.contam > self.p.contam_max:
                self.log(f'{r.id}: 오염도 {r.contam} > 100', 'violation')
        self.next_step(r)

    # ---- 물리 검사 (시뮬레이션 확인용) ----
    def check_bodies(self):
        rs = self.robots
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                d = math.dist(a.pos, b.pos)
                lim = (7.0 if a.loaded else 5.5) + (7.0 if b.loaded else 5.5)
                if d < lim - 0.01:
                    key = ('col', a.id, b.id)
                    if key not in self._touch:
                        self._touch.add(key)
                        self.stats['collisions'] += 1
                        self.log(f'충돌: {a.id}–{b.id} {d:.1f}cm (몸체 합 {lim})', 'violation')
                else:
                    self._touch.discard(('col', a.id, b.id))

    # ---- 시간 진행 ----
    def step_sim(self, dt):
        self._dt = dt
        if not hasattr(self, '_touch'):
            self._touch = set()
        self.t += dt
        if self.auto_rate > 0:
            if self._next_auto is None:
                self._next_auto = self.t + self.rng.expovariate(self.auto_rate / 60.0)
            while self.t >= self._next_auto:
                self.add_order(self.rng.choice(ROOMS))
                self._next_auto += self.rng.expovariate(self.auto_rate / 60.0)
        else:
            self._next_auto = None
        if self.t >= self._next_dispatch:
            self.dispatch()
            self._next_dispatch = self.t + self.p.dispatch_s
        for r in self.robots:
            self.tick_robot(r, dt)
        self.check_bodies()
        self.send_peers()

    PEERS_S = 0.3
    def send_peers(self):
        """실제 로봇마다 다른 실제 로봇의 지금 위치(로봇이 보고한 pose)를 보낸다 → 로봇이 AMCL 스캔에서 지움 (10-29)"""
        if self.t < getattr(self, '_next_peers', 0.0):
            return
        self._next_peers = self.t + self.PEERS_S
        real = [(o, o.link.pose()) for o in self.robots if o.link and o.link.alive()]
        for r, _ in real:
            r.link.set_peers([(p['x'], p['y']) for o, p in real if o is not r and p])

    # ---- 화면용 ----
    def snapshot(self):
        rs = []
        for r in self.robots:
            n, e, z = r.holds()
            rs.append(dict(id=r.id, color=r.color, x=round(r.pos[0], 2), y=round(r.pos[1], 2), node=r.node,
                           state=r.state_name(), task=r.task, fatigue=r.fatigue, contam=r.contam, load=r.load,
                           orders=[o.id for o in r.assigned],
                           step=None if r.step is None else {k: v for k, v in r.step.items() if k in ('kind', 'to', 'room')},
                           queue=[{k: v for k, v in s.items() if k in ('kind', 'to', 'room')} for s in r.queue],
                           path=r.path[r.k:] if r.step and r.step['kind'] == 'move' and r.path else [],
                           res_to=max(0, r.res_to - r.k), wait=r.wait_why if r.wait_s > 0 else '',
                           real=r.link is not None, fault=r.fault, at_dock=r.at_dock,
                           wait_s=round(r.wait_s, 1), timer=round(r.timer, 1),
                           plan=self.last_plans.get(r.id, []) if (r.step and (r.step['kind'] != 'move' or r.step.get('started'))) else [],
                           held=dict(nodes=sorted(n), edges=[list(x) for x in e], zones=sorted(z))))
        done = [o for o in self.orders if o.done_t is not None]
        avg = sum(o.done_t - o.created for o in done) / len(done) if done else 0
        return dict(t=round(self.t, 1), robots=rs, orders=[o.as_dict() for o in self.orders[-40:]],
                    waiting=sum(o.state == 'waiting' for o in self.orders),
                    stats=dict(self.stats, avg_delivery_s=round(avg, 1)), events=self.events[-40:][::-1],
                    planner=dict(self.plan_stats, mode=self.p.planner),
                    auto_rate=self.auto_rate)
