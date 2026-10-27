"""FMS 시뮬레이터 웹 화면.
  python3 fms/sim_server.py [--port 8770]   → http://localhost:8770
가상 핑키가 FMS 의 배차·예약 규칙대로 움직인다. 주문 버튼 / 자동 주문 / 배속 / 다시 시작.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

from fms_core import FMS, PARKING, ROOM_CONTAM, ROOM_INFO, Params, parse_request

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
    def __init__(self):
        self.lock = threading.Lock()
        self.speed = 1.0
        self.paused = False
        self.reset(3, True)
        threading.Thread(target=self.loop, daemon=True).start()

    def reset(self, n, spares, auto=0.0, planner='cbs'):
        with self.lock:
            self.f = FMS(n_robots=n, params=Params(fill_spares=spares, planner=planner))
            self.f.auto_rate = auto

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


SIM = None
MAP = None


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

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self.send(200, open(os.path.join(HERE, 'static/index.html'), 'rb').read(), 'text/html')
        if self.path == '/api/map':
            return self.send(200, MAP)
        if self.path == '/api/state':
            with SIM.lock:
                s = SIM.f.snapshot()
                s.update(speed=SIM.speed, paused=SIM.paused, fill_spares=SIM.f.p.fill_spares, n_robots=len(SIM.f.robots),
                         planner_mode=SIM.f.p.planner)
            return self.send(200, s)
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        try:
            b = self.body()
            if self.path == '/api/orders':                    # 관제 PC 요청 (형식 미정: fms_core.parse_request)
                reqs = parse_request(b)
                with SIM.lock:
                    made = [SIM.f.add_order(room, item).as_dict() for room, item in reqs]
                return self.send(200, made[0] if isinstance(b, dict) and 'orders' not in b else made)
            if self.path == '/api/control':
                if 'speed' in b:
                    SIM.speed = max(0.1, min(50.0, float(b['speed'])))
                if 'paused' in b:
                    SIM.paused = bool(b['paused'])
                if 'auto_rate' in b:
                    with SIM.lock:
                        SIM.f.auto_rate = max(0.0, float(b['auto_rate']))
                if 'reset' in b:
                    r = b['reset']
                    SIM.reset(int(r.get('robots', 3)), bool(r.get('spares', True)), SIM.f.auto_rate,
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
    a = ap.parse_args()
    SIM = Sim()
    g = SIM.f.g
    segs, ghost = load_walls()
    MAP = dict(walls=segs, invisible=ghost, size=[210, 200],
               nodes={k: dict(xy=n['xy'], type=n['type'], name=n.get('name')) for k, n in g.nodes.items()},
               edges=[dict(a=e['a'], b=e['b'], mode=e['mode'], zone=e['zone'])
                      for (a, b), e in g.edge.items() if (a, b) == (e['a'], e['b'])],
               rooms={k: v for k, v in ROOM_CONTAM.items()}, room_names={k: v['name'] for k, v in ROOM_INFO.items()},
               parking=PARKING)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f'FMS 시뮬레이터: http://{a.host}:{a.port}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
