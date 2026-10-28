"""실물 핑키 연결: FMS ← Pinky REST API (driving/api/pinky_api.py, 로봇의 :8080).
로봇마다 스레드 하나가 GET /status 를 읽어 위치·작업 상태를 들고 있는다 (읽기만, 명령은 안 보냄).
HTTP 는 이 스레드에서만 → 시뮬레이션 루프(SIM.lock)를 막지 않는다. 표준 라이브러리만 씀.
"""
import json
import threading
import time
import urllib.error
import urllib.request

STATUS_S = 0.3      # /status 읽는 간격 (초)
STALE_S = 3.0       # 이보다 오래 /status 를 못 읽으면 offline
POSE_AGE_S = 2.0    # /status pose.age_s(TF 나이)가 이보다 크면 위치 없음 — bringup·AMCL 이 멈춘 것 (10-28 ee3e 1253초)


class PinkyLink:
    def __init__(self, name, url):
        self.name, self.url = name, url.rstrip('/')
        self.status, self.status_t = None, 0.0
        self.alive = True
        threading.Thread(target=self.loop, daemon=True).start()

    def fetch(self):
        try:
            with urllib.request.urlopen(self.url + '/status', timeout=1.0) as r:
                self.status, self.status_t = json.loads(r.read()), time.time()
            return True
        except (urllib.error.URLError, OSError, ValueError):   # 연결 실패·시간 초과·JSON 아님
            return False

    def loop(self):
        while self.alive:
            self.fetch()
            time.sleep(STATUS_S)

    @property
    def online(self):
        return time.time() - self.status_t < STALE_S

    def pose(self):
        p = self.status and self.status.get('pose')
        return p if self.online and p and (p.get('age_s') or 0) < POSE_AGE_S else None

    def stop(self):
        self.alive = False
