"""발표 영상용: 같은 주문 9건을 FMS 단계별 시뮬레이터 4개에 동시에 넣고 2×2 화면으로 본다 (11-02).

  python3 demo_quad.py            # 서버 4개 띄움 → 브라우저로 http://localhost:8781/quad.html (F11 전체 화면)
                                  # → 화면 녹화 시작 → 여기서 Enter → 주문 9건이 넷에 동시에 들어가고 시간이 흐름
  python3 demo_quad.py --speed 8 --no-wait

칸 (fms_core.PROFILES): ① naive 로봇 1대 순차 · ② v2 처음 CBS · ③ v3 주차 + 직선 · ④ v4 지금.
Ctrl+C 로 서버 4개를 모두 끈다. 다시 찍으려면 다시 실행.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PANELS = [(8781, 'naive', 1), (8782, 'v2', 3), (8783, 'v3', 3), (8784, 'v4', 3)]   # static/quad.html 과 같은 포트
ROOMS = ['101호', '102호', '103호', '104호', '105호', '106호', '107호', '수술실', '108호']


def call(port, path, body=None):
    r = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method='GET' if body is None else 'POST',
                               data=None if body is None else json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=5) as f:
        return json.load(f)


def main(panels=PANELS, page='quad.html'):
    ap = argparse.ArgumentParser()
    ap.add_argument('--speed', type=float, default=8.0, help='배속 (넷 모두 같음). 8 이면 ④ 약 60초, ① 세척실→수술실 약 70~80초')
    ap.add_argument('--no-wait', action='store_true', help='Enter 기다리지 않고 바로 시작')
    ap.add_argument('--delay', type=float, default=3.0, help='Enter 뒤 시작까지 초 (터미널에서 녹화 화면으로 돌아갈 시간, 11-03)')
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # kill 로 꺼도 아래 finally 가 서버 4개를 끔
    procs = [subprocess.Popen([sys.executable, '-u', os.path.join(HERE, 'sim_server.py'), '--port', str(port),
                               '--profile', prof, '--robots', str(n)], cwd=HERE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for port, prof, n in panels]
    try:
        for port, _, _ in panels:                       # 뜰 때까지
            for _ in range(100):
                try:
                    call(port, '/api/state')
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise SystemExit(f'포트 {port} 서버가 안 뜸')
            call(port, '/api/control', {'paused': True, 'speed': a.speed})
        print(f'서버 {len(panels)}개 준비 (배속 {a.speed:g}). 브라우저로 http://localhost:{panels[0][0]}/{page} 을 열고 F11 (전체 화면).')
        if not a.no_wait:
            input(f'화면 녹화를 시작한 뒤 Enter → {a.delay:g}초 뒤 주문 9건이 모든 칸에 동시에 들어갑니다 ')
            for k in range(int(a.delay), 0, -1):
                print(f'  {k}…', flush=True)
                time.sleep(1)
            time.sleep(a.delay - int(a.delay))
        for port, _, _ in panels:                       # 멈춘 채로 주문 → 한꺼번에 풀기
            for i, room in enumerate(ROOMS):
                call(port, '/api/v1/orders', {'request_id': f'demo-{i + 1}', 'room': room, 'item': '약'})
        for port, _, _ in panels:
            call(port, '/api/control', {'paused': False})
        print(f'시작. 끝내려면 Ctrl+C (서버 {len(panels)}개가 꺼집니다)')
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == '__main__':
    main()
