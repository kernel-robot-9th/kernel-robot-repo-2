"""FMS 시뮬레이터 웹 화면 + 관제 PC API v1.
  python3 fms/sim_server.py [--port 8770] [--host 0.0.0.0] [--control-url http://<관제 PC>:8000]
가상 핑키가 FMS 의 배차·예약 규칙대로 움직인다. 주문 버튼 / 자동 주문 / 배속 / 다시 시작.
API v1 (관제 PC ↔ FMS): fms/API.md, Swagger = /docs. --control-url 을 주면 로봇 상태(1초마다)와 이벤트를 그 주소로 POST.
가상 관제 PC(OMX ready·loaded 자동)는 기본 켜짐 — 진짜 관제 PC 를 붙이면 화면에서 끄거나 POST /api/control {"auto_omx": false}.
"""
import argparse
import datetime
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import yaml

import openapi_v1
from fms_core import FMS, PARKING, PHARMACY, ROOM_CONTAM, ROOM_INFO, Conflict, Params, parse_request, room_code

KST = datetime.timezone(datetime.timedelta(hours=9))


def now_iso():
    return datetime.datetime.now(KST).isoformat(timespec='seconds')

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '../driving/tools')   # 벽 그림용 real_walls.yaml, left_wall_measured.json


def load_walls():
    w = yaml.safe_load(open(os.path.join(TOOLS, 'real_walls.yaml')))
    segs, ghost = [], []

    def walk(v, out):
        if isinstance(v, dict):
            for x in v.values():
                walk(x, out)
        elif isinstance(v, list) and len(v) == 4 and all(isinstance(t, (int, float)) for t in v):
            out.append([[v[0], v[1]], [v[2], v[3]]])
        elif isinstance(v, list) and v and all(isinstance(t, list) and len(t) == 2 for t in v):
            out.append(v)
    for k, v in w.items():
        if k == 'invisible':
            for b in v.values():
                x0, y0, x1, y1 = b
                ghost.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
        else:
            walk(v, segs)
    left = json.load(open(os.path.join(TOOLS, 'left_wall_measured.json')))['polyline']
    segs.append(left)
    return segs, ghost


class Sim:
    def __init__(self, control_url=None, links=None, n_robots=3):
        self.lock = threading.Lock()
        self.speed = 1.0
        self.paused = False
        self.f = None
        self.links = links or {}      # 이름 → robot_link.HttpLink (실제 로봇). 다시 시작해도 연결은 그대로
        self.reset(n_robots)
        self.push = Pusher(self, control_url)
        threading.Thread(target=self.loop, daemon=True).start()

    def reset(self, n, auto=0.0, planner='cbs', auto_omx=None):
        with self.lock:
            old = self.f
            self.f = FMS(n_robots=n, params=Params(planner=planner), links=self.links)
            if self.links:
                self.speed = 1.0                           # 실제 로봇이 있으면 실시간만
            self.f.auto_rate = auto
            self.f.clock = now_iso
            if old is not None:
                self.f._seq = old._seq                     # 이벤트 번호는 다시 시작해도 이어간다
                self.f.p.auto_omx = old.p.auto_omx if auto_omx is None else auto_omx

    def loop(self):
        dt, last = 0.05, time.time()
        while True:
            time.sleep(0.02)
            now = time.time()
            real = min(now - last, 0.2)
            last = now
            if self.paused:
                continue
            sim = real * self.speed
            with self.lock:
                while sim > 1e-9:
                    h = min(dt, sim)
                    self.f.step_sim(h)
                    sim -= h


class Pusher:
    """FMS → 관제 PC: 로봇 상태 1초마다 (실패하면 버림), 이벤트는 나오는 대로 (연결 실패·5xx 면 1, 2, 4초 뒤 다시)"""
    def __init__(self, sim, url):
        self.sim, self.url = sim, (url or '').rstrip('/') or None
        self.sent_seq = 0
        self.q = queue.Queue()
        self.last = dict(status=None, event=None)          # 마지막 보내기 결과 (화면·디버그용)
        threading.Thread(target=self.status_loop, daemon=True).start()
        threading.Thread(target=self.event_loop, daemon=True).start()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=1.0) as r:
                return r.status, None
        except urllib.error.HTTPError as e:
            return e.code, str(e)
        except Exception as e:  # noqa: BLE001  연결 실패·시간 초과
            return None, str(e)

    def status_loop(self):
        while True:
            time.sleep(1.0)
            with self.sim.lock:
                f = self.sim.f
                body = dict(time=now_iso(), robots=[f.robot_status(r) for r in f.robots])
                new = [e for e in f.outbox if e['seq'] > self.sent_seq]
                if new:
                    self.sent_seq = new[-1]['seq']
            for e in new:
                self.q.put(e)
            if self.url:
                code, err = self.post('/api/v1/fms/robot-status', body)
                self.last['status'] = dict(code=code, error=err, time=body['time'])

    def event_loop(self):
        while True:
            e = self.q.get()
            if not self.url:
                continue
            for wait in (0, 1, 2, 4):
                time.sleep(wait)
                code, err = self.post('/api/v1/fms/events', e)
                self.last['event'] = dict(code=code, error=err, event_id=e['event_id'])
                if code is not None and code < 500:
                    break


SIM = None
MAP = None
ROOMS_V1 = [dict(room=str(v.get('code', k)), name=v['name'], contamination=v['contam'], orderable=True)
            for k, v in sorted(ROOM_INFO.items(), key=lambda kv: str(kv[1].get('code', kv[0])))] + \
           [dict(room='약제실', name='약제실 OMX', contamination=None, orderable=False)]


def err(code, error, message, **kw):
    return code, dict(error=error, message=message, **kw)


def v1_get(path, qs):
    f = SIM.f
    if path == '/api/v1/state':
        return 200, f.state_v1()
    if path == '/api/v1/rooms':
        return 200, dict(rooms=ROOMS_V1)
    if path == '/api/v1/map':
        return 200, MAP
    if path == '/api/v1/events':                       # 디버그·관제 PC 없이 시험할 때: ?after=<seq>
        after = int((qs.get('after') or ['0'])[0])
        return 200, dict(events=[e for e in f.outbox if e['seq'] > after][:500], last_seq=f._seq)
    parts = path.strip('/').split('/')
    if len(parts) == 4 and parts[2] == 'orders':
        o = f.find_order(parts[3])
        return (200, f.order_api(o)) if o else err(404, 'not_found', f'주문 {parts[3]} 없음')
    if len(parts) == 4 and parts[2] == 'batches':
        b = f.find_batch(parts[3])
        return (200, f.batch_api(b)) if b else err(404, 'not_found', f'묶음 {parts[3]} 없음')
    return err(404, 'not_found', f'없는 경로 {path}')


def v1_post(path, body):
    f = SIM.f
    if path == '/api/v1/orders':
        if not isinstance(body, dict):
            return err(400, 'bad_json', '본문은 JSON 객체 하나')
        miss = [k for k in ('request_id', 'room', 'item') if body.get(k) in (None, '')]
        if miss:
            return err(400, 'missing_field', f'빠진 필드: {", ".join(miss)}', fields=miss)
        rid = str(body['request_id'])
        dup = rid in f.by_request
        try:
            o = f.add_order(str(body['room']), str(body['item']), rid)
        except ValueError as e:
            return err(400, 'unknown_room', str(e), rooms=[r['room'] for r in ROOMS_V1 if r['orderable']])
        return (200 if dup else 202), f.order_api(o)
    parts = path.strip('/').split('/')
    if len(parts) == 5 and parts[2] == 'batches' and parts[4] in ('ready', 'loaded'):
        b = f.find_batch(parts[3])
        if b is None:
            return err(404, 'not_found', f'묶음 {parts[3]} 없음')
        if parts[4] == 'ready':
            eta = f.batch_ready(b)
            return 200, dict(batch_id=b.bid, status=b.status, robot=b.robot.num, name=b.robot.name, eta_s=eta)
        f.batch_loaded(b)
        return 200, dict(batch_id=b.bid, status=b.status)
    return err(404, 'not_found', f'없는 경로 {path}')


def v1_delete(path):
    f = SIM.f
    parts = path.strip('/').split('/')
    if len(parts) == 4 and parts[2] == 'orders':
        o = f.find_order(parts[3])
        if o is None:
            return err(404, 'not_found', f'주문 {parts[3]} 없음')
        f.cancel_order(o)
        return 200, f.order_api(o)
    return err(404, 'not_found', f'없는 경로 {path}')


def v1(method, path, qs=None, body=None):
    """API v1 처리 (SIM.lock 안에서). 반환 (HTTP 코드, 본문)"""
    try:
        with SIM.lock:
            if method == 'GET':
                return v1_get(path, qs or {})
            if method == 'POST':
                return v1_post(path, body)
            return v1_delete(path)
    except Conflict as e:
        return err(409, e.code, str(e))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if 'json' in ctype or 'html' in ctype else ''))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path.startswith('/api/v1/'):
            return self.send(*v1('DELETE', u.path))
        self.send(404, {'error': 'not_found', 'message': self.path})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith('/api/v1/') and u.path != '/api/v1/openapi.json':
            return self.send(*v1('GET', u.path, parse_qs(u.query)))
        if u.path == '/api/v1/openapi.json':
            return self.send(200, openapi_v1.SPEC)
        if u.path == '/docs':
            return self.send(200, openapi_v1.SWAGGER_HTML.encode(), 'text/html')
        if self.path in ('/', '/index.html'):
            return self.send(200, open(os.path.join(HERE, 'static/index.html'), 'rb').read(), 'text/html')
        if self.path == '/api/map':
            return self.send(200, MAP)
        if self.path == '/api/state':
            with SIM.lock:
                s = SIM.f.snapshot()
                s.update(speed=SIM.speed, paused=SIM.paused, n_robots=len(SIM.f.robots),
                         planner_mode=SIM.f.p.planner, auto_omx=SIM.f.p.auto_omx, control_url=SIM.push.url,
                         push=SIM.push.last,
                         batches=[SIM.f.batch_api(b) for b in SIM.f.batches if b.status not in ('completed', 'failed')])
            return self.send(200, s)
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        try:
            b = self.body()
        except ValueError:
            return self.send(400, {'error': 'bad_json', 'message': 'JSON 이 아님'})
        try:
            if self.path.startswith('/api/v1/'):
                return self.send(*v1('POST', urlparse(self.path).path, body=b))
            if self.path == '/api/orders':                    # 시뮬레이터 화면 버튼 (관제 PC 는 /api/v1/orders)
                reqs = parse_request(b)
                with SIM.lock:
                    made = [SIM.f.add_order(room, item).as_dict() for room, item in reqs]
                return self.send(200, made[0] if isinstance(b, dict) and 'orders' not in b else made)
            if self.path == '/api/control':
                if 'speed' in b and not SIM.links:              # 실제 로봇이 있으면 실시간만
                    SIM.speed = max(0.1, min(50.0, float(b['speed'])))
                if 'clear_fault' in b:                           # 실제 로봇 실패 표시 지우고 이어서 {"clear_fault": "R1"}
                    with SIM.lock:
                        for rr in SIM.f.robots:
                            if rr.id == b['clear_fault'] or rr.name == b['clear_fault']:
                                SIM.f.clear_fault(rr)
                if 'paused' in b:
                    SIM.paused = bool(b['paused'])
                if 'auto_rate' in b:
                    with SIM.lock:
                        SIM.f.auto_rate = max(0.0, float(b['auto_rate']))
                if 'auto_omx' in b:
                    with SIM.lock:
                        SIM.f.p.auto_omx = bool(b['auto_omx'])
                if 'control_url' in b:
                    SIM.push.url = (b['control_url'] or '').rstrip('/') or None
                if 'reset' in b:
                    r = b['reset']
                    SIM.reset(int(r.get('robots', 3)), SIM.f.auto_rate,
                              r.get('planner', SIM.f.p.planner))
                return self.send(200, {'ok': True})
            self.send(404, {'error': 'not found'})
        except (KeyError, ValueError) as e:
            self.send(400, {'error': str(e)})


def main():
    global SIM, MAP
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8770)
    ap.add_argument('--host', default='127.0.0.1', help='다른 PC 에서 붙으려면 0.0.0.0')
    ap.add_argument('--control-url', default=None, help='관제 PC 주소 (예: http://192.168.129.135:8000). 로봇 상태·이벤트를 여기로 POST')
    ap.add_argument('--no-auto-omx', action='store_true', help='가상 관제 PC 끔: ready·loaded 를 진짜 관제 PC 가 보냄')
    ap.add_argument('--real', action='append', default=[], metavar='이름=URL',
                    help='실제 로봇 (robots.yaml 이름). 예: --real pinky_6364=http://192.168.129.68:8080 — 나머지 로봇은 가상')
    ap.add_argument('--real-table', action='store_true', help='robots.yaml 에 url 이 있는 로봇은 모두 실제 로봇으로')
    ap.add_argument('--robots', type=int, default=3, help='로봇 수 (실제 + 가상)')
    a = ap.parse_args()
    from robot_link import HttpLink
    links = {}
    reals = [x.split('=', 1) for x in a.real]
    if a.real_table:
        from fms_core import ROBOT_TABLE
        reals += [(row['name'], row['url']) for row in ROBOT_TABLE if row.get('url')]
    for name, url in reals:
        links[name] = HttpLink(name, url)
    SIM = Sim(a.control_url, links, a.robots)
    SIM.f.p.auto_omx = not a.no_auto_omx
    g = SIM.f.g
    segs, ghost = load_walls()
    MAP = dict(walls=segs, invisible=ghost, size=[210, 200],
               nodes={k: dict(xy=n['xy'], type=n['type'], name=n.get('name')) for k, n in g.nodes.items()},
               edges=[dict(a=e['a'], b=e['b'], mode=e['mode'], zone=e['zone'])
                      for (a, b), e in g.edge.items() if (a, b) == (e['a'], e['b'])],
               rooms={k: v for k, v in ROOM_CONTAM.items()}, room_names={k: v['name'] for k, v in ROOM_INFO.items()},
               room_codes={**{k: room_code(k) for k in ROOM_INFO}, PHARMACY: '약제실'},
               parking=PARKING)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f'FMS 시뮬레이터: http://{a.host}:{a.port}  (API v1 Swagger: /docs, 관제 PC 로 보내기: {SIM.push.url or "끔"}, '
          f'가상 OMX {"켬" if SIM.f.p.auto_omx else "끔"}, 실제 로봇 {list(links) or "없음"})')
    srv.serve_forever()


if __name__ == '__main__':
    main()
