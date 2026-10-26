# 주행 그래프 편집기 서버:  python3 graph_editor.py [--port 8765]  → 브라우저에서 http://localhost:8765
# graph_spec.yaml 을 읽어 editor.html 에 넘기고, 고칠 때마다 build_graph.build() 로 벽 여유를 다시 계산해 돌려준다.
# 저장: 이전 graph_spec.yaml 을 backup/ 에 두고 새로 쓴 뒤 graph.yaml·graph.png 도 다시 만든다.
import argparse
import json
import os
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

import build_graph as bg

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '../tools')


def walls():
    """실측 벽 (real_walls.yaml + 왼쪽 외벽 측정 polyline) → [{name, pts, invisible}]"""
    W = yaml.safe_load(open(os.path.join(TOOLS, 'real_walls.yaml')))
    out = []
    for g, ws in W.items():
        for n, w in ws.items():
            if g == 'invisible':
                x0, y0, x1, y1 = w
                out.append(dict(name=f'{g}.{n}', pts=[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], invisible=True))
            else:
                p = w if isinstance(w[0], list) else [w[:2], w[2:]]
                out.append(dict(name=f'{g}.{n}', pts=p, invisible=False))
    left = json.load(open(os.path.join(TOOLS, 'left_wall_measured.json')))['polyline']
    out.append(dict(name='outer.left', pts=left, invisible=False))
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8', cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'max-age=3600' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self._send(200, open(os.path.join(HERE, 'editor.html'), 'rb').read(), 'text/html; charset=utf-8')
        if self.path == '/bg.png':
            return self._send(200, open(os.path.join(TOOLS, 'layout_diagram.png'), 'rb').read(), 'image/png', cache=True)
        if self.path == '/api/state':
            return self._send(200, dict(spec=bg.load_spec(), walls=walls()))
        self._send(404, {'error': 'not found'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        try:
            spec = json.loads(self.rfile.read(n))
        except Exception as e:  # noqa: BLE001
            return self._send(400, {'error': f'JSON: {e}'})
        try:
            if self.path == '/api/preview':
                nodes, edges, errors = bg.build(spec)
                return self._send(200, dict(nodes=nodes, edges=edges, errors=errors))
            if self.path == '/api/save':
                os.makedirs(os.path.join(HERE, 'backup'), exist_ok=True)
                bak = os.path.join(HERE, 'backup', time.strftime('graph_spec_%Y%m%d_%H%M%S.yaml'))
                if os.path.exists(bg.SPEC):
                    shutil.copy(bg.SPEC, bak)
                bg.dump_spec(spec)
                nodes, edges, errors = bg.write_outputs(bg.load_spec())
                return self._send(200, dict(ok=True, backup=os.path.relpath(bak, HERE), errors=errors,
                                            summary=f'노드 {len(nodes)}개, 엣지 {len(edges)}개'))
        except Exception as e:  # noqa: BLE001
            return self._send(500, {'error': f'{type(e).__name__}: {e}'})
        self._send(404, {'error': 'not found'})


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    print(f'그래프 편집기: http://localhost:{a.port}  (Ctrl+C 로 끝)')
    ThreadingHTTPServer(('127.0.0.1', a.port), H).serve_forever()
