# FMS ↔ 실제 핑키 연결 (설계: FMS ↔ Pinky 주행 API 설계 문서, 10-29). 로봇 API (api/pinky_api.py, 포트 8080):
#   POST /drive {cmd_id, route, next}   POST /action {cmd_id, kind}   POST /cancel   GET /status (drive 칸)
# 시뮬레이터 틱(잠금 안)에서 HTTP 를 기다리지 않도록: /status 는 스레드가 0.3초마다 읽어 두고, 명령은 보내는 스레드 큐로.
import json
import queue
import threading
import time
import urllib.error
import urllib.request

POLL_S = 0.3
LOST_S = 2.0          # /status 가 이만큼 안 오면 연결 끊김


class HttpLink:
    def __init__(self, name, url):
        self.name, self.url = name, url.rstrip('/')
        self.st = None              # 마지막 /status 응답
        self.st_t = 0.0             # 받은 시각
        self.err = None             # 마지막 통신 오류
        self.sent = {}              # cmd_id → (http 코드, 응답) 보낸 결과
        self.n = 0
        self.q = queue.Queue()
        threading.Thread(target=self._poll, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()

    def _req(self, path, body=None, timeout=3.0):
        r = urllib.request.Request(self.url + path, method='GET' if body is None else 'POST',
                                   data=None if body is None else json.dumps(body).encode(),
                                   headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(r, timeout=timeout) as f:
                return f.status, json.load(f)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except ValueError:
                return e.code, {'error': f'HTTP {e.code}'}

    def _poll(self):
        while True:
            try:
                code, b = self._req('/status', timeout=2.0)
                if code == 200:
                    self.st, self.st_t, self.err = b, time.time(), None
            except Exception as e:  # noqa: BLE001
                self.err = f'{type(e).__name__}: {e}'
            time.sleep(POLL_S)

    def _send_loop(self):
        while True:
            cid, path, body = self.q.get()
            try:
                self.sent[cid] = self._req(path, body)
            except Exception as e:  # noqa: BLE001
                self.sent[cid] = (None, {'error': 'unreachable', 'why': f'{type(e).__name__}: {e}'})

    # ---- 읽기 ----
    def alive(self):
        return self.st is not None and time.time() - self.st_t < LOST_S

    def drive_status(self, cid=None):
        """로봇이 보고한 drive 칸 (cid 를 주면 그 명령일 때만)"""
        d = (self.st or {}).get('drive')
        if d is None or (cid is not None and d.get('cmd_id') != cid):
            return None
        return d

    def pose(self):
        return (self.st or {}).get('pose')

    def result(self, cid):
        """보낸 명령의 HTTP 결과 (code, body) 또는 None (아직)"""
        return self.sent.get(cid)

    # ---- 명령 ----
    def _cid(self):
        self.n += 1
        return f'{self.name}-{time.strftime("%H%M%S")}-{self.n}'

    def drive(self, route, nxt=None):
        cid = self._cid()
        self.q.put((cid, '/drive', dict(cmd_id=cid, route=list(route), next=nxt)))
        return cid

    def action(self, kind, **kw):
        cid = self._cid()
        self.q.put((cid, '/action', dict(cmd_id=cid, kind=kind, **kw)))
        return cid

    def cancel(self):
        self.q.put((self._cid(), '/cancel', {}))

    def wait_status(self, timeout=6.0):
        t = time.time() + timeout
        while time.time() < t and not self.alive():
            time.sleep(0.1)
        return self.alive()
