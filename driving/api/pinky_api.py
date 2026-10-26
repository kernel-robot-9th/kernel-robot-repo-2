# Pinky REST API — **로봇에서** 돈다 (관제 PC 는 HTTP 만 보낸다. 와이파이 너머로 ROS/DDS 를 안 씀)
# 좌표는 그림 cm (왼쪽 아래 원점, y 위), 위치 = **라이다 중심**, 방향 deg (0 = +x, 90 = +y, 반시계 +)
# 주행은 주행 그래프(graph/graph.yaml)를 따른다 → api/graph_route.py. 구간 mode: nav = Nav2 FollowPath, wall = 협로 벽 따라가기,
# dock = 카메라 정밀 주차 (precise_dock.py). 교행 복도는 라인트레이싱 전까지 복도 가운데를 Nav2 로 (2026-10-22 사용자 결정).
# 먼저 띄울 것: bringup_robot.launch.xml, nav2_followpath.launch.py, 그리고 /set_pose (또는 tools/set_pose.py)
#   ~/pinky_map_rev3/api/run_api.sh            # 0.0.0.0:8080
#
#   GET  /status                      위치·상태·지금 작업
#   GET  /dests                       목적지 이름 목록
#   GET  /plan?x=60&y=145[&heading=]  경로만 (움직이지 않음). ?dest=PHARMACY, &from=x,y,heading (지금 위치 대신)
#   POST /goto   {"x":60,"y":145,"heading":180} 또는 {"dest":"PHARMACY","dock":false}  → 202 {job}
#   POST /cancel                      지금 작업 멈춤
#   GET  /jobs/<id>                   작업 상태 (GET /jobs = 최근 목록)
#   POST /set_pose {"name":"A"} | {"x":182.7,"y":24,"heading":180} | {"find":true}   AMCL 시작 위치 넣기 (tools/set_pose.py)
#   GET/PUT /notify {"url":..,"dests":["PHARMACY"]}   도착 신호: 그 목적지 작업이 성공하면(dock 이면 정밀 주차 끝) url 로 POST
#   GET  /docs                        Swagger UI (명세 = GET /openapi.json, api/openapi.py 에 손으로 씀)
import argparse
import json
import math
import re
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from flask import Flask, jsonify, request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
from coords import map_to_user  # noqa: E402
from follow_path_client import LIDAR_BEHIND_AXLE, build_poses, densify  # noqa: E402
from graph_route import Graph  # noqa: E402
import openapi  # noqa: E402

LOGS = os.path.join(HERE, 'logs')
DENY_FILE = os.path.expanduser('~/.config/pinky/deny_ips.txt')   # 명령(POST·PUT)을 막을 IP, 한 줄에 하나 (# 주석). 요청마다 다시 읽음
NOTIFY_FILE = os.path.expanduser('~/.config/pinky/notify.json')   # 도착 신호 설정 (PUT /notify 로 등록, 로봇에 남음)


def robot_info():
    serial = ''
    try:
        serial = next((ln.split(':')[1].strip() for ln in open('/proc/cpuinfo') if ln.startswith('Serial')), '')
    except OSError:
        pass
    try:
        ips = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=2).stdout.split()
    except Exception:  # noqa: BLE001
        ips = []
    return dict(serial=serial, hostname=socket.gethostname(), ips=ips)


def wait_future(f, timeout, cancel=None):
    t = time.time()
    while not f.done():
        if time.time() - t > timeout or (cancel is not None and cancel.is_set()):
            return False
        time.sleep(0.02)
    return True


class Robot:
    """ROS 쪽: TF 로 위치, FollowPath 액션, 벽 따라가기, 정밀 주차"""

    def __init__(self):
        import rclpy
        from geometry_msgs.msg import Twist
        from nav2_msgs.action import FollowPath
        from rclpy.action import ActionClient
        from rclpy.executors import MultiThreadedExecutor
        from tf2_ros import Buffer, TransformListener
        self.rclpy, self.FollowPath, self.Twist = rclpy, FollowPath, Twist
        rclpy.init()
        self.node = rclpy.create_node('pinky_api')
        self.tfb = Buffer(); self.tfl = TransformListener(self.tfb, self.node)
        self.fp = ActionClient(self.node, FollowPath, 'follow_path')
        self.cmd = self.node.create_publisher(Twist, 'cmd_vel_nav', 10)
        self.ex = MultiThreadedExecutor(); self.ex.add_node(self.node)
        threading.Thread(target=self.ex.spin, daemon=True).start()
        self.cd = None   # CorridorDrive: 자기 노드를 작업 스레드에서 spin_once 로 돌림 (위 executor 와 따로)

    def pose(self):
        """라이다 중심 dict(x, y cm, heading deg, age_s) 또는 None (map → base_footprint TF 없음 = AMCL/Nav2 안 뜸)"""
        try:
            t = self.tfb.lookup_transform('map', 'base_footprint', self.rclpy.time.Time())
        except Exception:  # noqa: BLE001
            return None
        tr, q = t.transform.translation, t.transform.rotation
        th = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        lx, ly = tr.x - LIDAR_BEHIND_AXLE * math.cos(th), tr.y - LIDAR_BEHIND_AXLE * math.sin(th)
        x, y = map_to_user(lx, ly)
        hx, hy = map_to_user(lx + 0.1 * math.cos(th), ly + 0.1 * math.sin(th))
        stamp = t.header.stamp.sec + t.header.stamp.nanosec * 1e-9
        now = self.node.get_clock().now().nanoseconds * 1e-9
        return dict(x=round(x, 1), y=round(y, 1), heading=round(math.degrees(math.atan2(hy - y, hx - x)), 1),
                    age_s=round(now - stamp, 2))

    def nav_ready(self):
        return self.fp.server_is_ready()

    def halt(self):
        for _ in range(5):
            self.cmd.publish(self.Twist()); time.sleep(0.02)

    # --- 구간 실행: 반환 dict(status=ok|fail|canceled, ...) ---
    def follow(self, pts, final_heading, cancel, job):
        from geometry_msgs.msg import PoseStamped
        from nav_msgs.msg import Path
        if not self.fp.wait_for_server(timeout_sec=3.0):
            return dict(status='fail', why='follow_path 액션 서버 없음 — nav2_followpath 가 떠 있는지 확인')
        path = Path(); path.header.frame_id = 'map'; path.header.stamp = self.node.get_clock().now().to_msg()
        for x, y, yaw in build_poses(densify([tuple(p) for p in pts], 2.0), final_heading):
            p = PoseStamped(); p.header = path.header
            p.pose.position.x, p.pose.position.y = x, y
            p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            path.poses.append(p)
        goal = self.FollowPath.Goal(path=path, controller_id='FollowPath', goal_checker_id='general_goal_checker',
                                    progress_checker_id='progress_checker')

        P = [tuple(p) for p in pts]
        seg_len = [math.dist(a, b) for a, b in zip(P, P[1:])]

        def fb(f):   # FollowPath 피드백의 distance_to_goal 은 남은 거리가 아님 (10-22 확인) → 위치를 경로에 내려서 직접 계산
            p = self.pose()
            if p is None:
                return
            best = None
            for i, (a, b) in enumerate(zip(P, P[1:])):
                L = seg_len[i] or 1e-6
                t = max(0.0, min(1.0, ((p['x'] - a[0]) * (b[0] - a[0]) + (p['y'] - a[1]) * (b[1] - a[1])) / L ** 2))
                d = math.dist((p['x'], p['y']), (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
                if best is None or d < best[0]:
                    best = (d, (1 - t) * L + sum(seg_len[i + 1:]))
            job['progress'] = dict(remaining_cm=round(best[1], 1), speed=round(f.feedback.speed, 3))
        fs = self.fp.send_goal_async(goal, feedback_callback=fb)
        if not wait_future(fs, 10):
            return dict(status='fail', why='FollowPath 보내기 시간 초과')
        gh = fs.result()
        if not gh.accepted:
            return dict(status='fail', why='FollowPath 거부됨')
        fr = gh.get_result_async()
        if not wait_future(fr, 600, cancel):
            wait_future(gh.cancel_goal_async(), 5); wait_future(fr, 5); self.halt()
            return dict(status='canceled' if cancel.is_set() else 'fail', why='취소' if cancel.is_set() else '시간 초과')
        r = fr.result()
        out = dict(status='ok' if r.status == 4 else 'fail', action_status=r.status, error_code=r.result.error_code)
        if getattr(r.result, 'error_msg', ''):
            out['why'] = r.result.error_msg
        return out

    def _corridor(self):
        if self.cd is None:
            from corridor_drive import CorridorDrive
            # TF 는 늘 도는 메인 노드의 버퍼를 같이 씀 (이 노드는 벽 따라가기 동안만 spin → 자기 TF 는 쉬는 동안 낡음, 10-22 실패 원인)
            self.cd = CorridorDrive(self.rclpy.create_node('pinky_api_corridor'), tf_buffer=self.tfb)
        return self.cd

    def wall(self, sg, cancel):
        cd = self._corridor()
        cd.side, cd.d_ref = sg['side'], sg['offset'] / 100
        os.makedirs(LOGS, exist_ok=True)
        log = os.path.join(LOGS, f'corridor_{time.strftime("%m%d_%H%M%S")}.npz')
        r = cd.run(sg['points'][0], sg['points'][-1], sg['final_heading'], log, should_stop=cancel.is_set)
        r['log'] = log
        return r

    def rotate(self, heading, cancel):
        cd = self._corridor()
        if not cd.wait_ready():
            return dict(status='fail', why='scan/TF 없음')
        ok = cd.rotate_to(math.radians(heading))
        return dict(status='ok' if ok else 'fail')

    def dock(self, cancel, job):
        p = subprocess.Popen([sys.executable, os.path.join(TOOLS, 'precise_dock.py')], cwd=TOOLS,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []

        def read():
            for ln in p.stdout:
                ln = ln.rstrip()
                if not (ln.startswith('[') and ('INFO' in ln or 'WARN' in ln)):   # libcamera 로그 빼고
                    lines.append(ln); job['progress'] = dict(dock=ln)
        th = threading.Thread(target=read, daemon=True); th.start()
        while p.poll() is None:
            if cancel.is_set():
                p.send_signal(signal.SIGINT)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                self.halt()
                return dict(status='canceled', lines=lines[-6:])
            time.sleep(0.1)
        th.join(2)
        out = dict(status='ok' if p.returncode == 0 else 'fail', exit=p.returncode, lines=lines[-6:])
        for ln in reversed(lines):   # "최종: 앞뒤 -0.4mm, 좌우 +1.7mm, 방향 +0.40°  (...)" → 마커 기준 자세와의 어긋남
            m = re.search(r'최종: 앞뒤 ([-+\d.]+)mm, 좌우 ([-+\d.]+)mm, 방향 ([-+\d.]+)°', ln)
            if m:
                out['final'] = dict(fwd_mm=float(m[1]), left_mm=float(m[2]), heading_deg=float(m[3])); break
        return out


class Api:
    def __init__(self, robot):
        self.robot, self.graph = robot, Graph()
        self.jobs, self.order = {}, []
        self.job = None              # 지금 도는 작업
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.info = robot_info()
        self.notify_cfg = self.load_notify()

    def plan(self, body, start=None):
        if start is None:
            p = self.robot.pose()
            if p is None:
                raise LookupError('지금 위치 없음 (map → base_footprint TF 없음): bringup·nav2_followpath 를 띄우고 /set_pose')
            start = (p['x'], p['y'], p['heading'])
        if body.get('dest'):
            goal = str(body['dest'])
        elif body.get('x') is not None and body.get('y') is not None:
            h = body.get('heading')
            goal = (float(body['x']), float(body['y']), None if h in (None, '') else float(h))
        else:
            raise ValueError('목적지 필요: {"x":..,"y":..[,"heading":..]} 또는 {"dest":"PHARMACY"}')
        dock = body.get('dock')
        if dock is None:   # 정밀 주차가 되는 목적지(PHARMACY)는 따로 말 안 하면 정밀 주차까지 (10-22 사용자: 정밀 주차 뒤 도착 신호)
            node = self.graph.alias.get(goal) or self.graph.alias.get(goal.upper()) if isinstance(goal, str) else None
            dock = bool(node and self.graph.nodes[node].get('dock'))
        return self.graph.plan(start, goal, dock=bool(dock))

    def start(self, body):
        with self.lock:
            if self.job and self.job['state'] == 'running':
                return None, f'작업 {self.job["id"]} 가 도는 중 — 먼저 /cancel'
            plan = self.plan(body)
            job = dict(id=uuid.uuid4().hex[:8], request=body, plan=plan, state='running', segment=0,
                       segments_total=len(plan['segments']), results=[], progress=None,
                       start_pose=self.robot.pose(), t_start=time.strftime('%Y-%m-%d %H:%M:%S'), t0=time.time())
            self.jobs[job['id']] = job; self.order.append(job['id'])
            self.order[:] = self.order[-50:]
            self.cancel.clear(); self.job = job
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
            return job, None

    def _run(self, job):
        r = self.robot
        try:
            for i, sg in enumerate(job['plan']['segments']):
                if self.cancel.is_set():
                    job['state'] = 'canceled'; break
                job['segment'], job['progress'] = i + 1, None
                t0 = time.time()
                if sg['mode'] == 'nav':
                    res = r.follow(sg['points'], sg['final_heading'], self.cancel, job)
                elif sg['mode'] == 'wall':
                    res = r.wall(sg, self.cancel)
                elif sg['mode'] == 'rotate':
                    res = r.rotate(sg['heading'], self.cancel)
                elif sg['mode'] == 'dock':
                    res = r.dock(self.cancel, job)
                else:
                    res = dict(status='fail', why=f'모르는 mode {sg["mode"]}')
                res.update(segment=i + 1, mode=sg['mode'], time_s=round(time.time() - t0, 1), pose=r.pose())
                job['results'].append(res)
                if res['status'] != 'ok':
                    job['state'] = 'canceled' if res['status'] == 'canceled' or self.cancel.is_set() else 'failed'
                    job['error'] = res.get('why') or res['status']
                    break
            else:
                job['state'] = 'succeeded'
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()   # journalctl --user -u pinky-api
            job['state'], job['error'] = 'failed', f'{type(e).__name__}: {e}'
            r.halt()
        job['time_s'] = round(time.time() - job['t0'], 1)
        job['end_pose'] = r.pose()
        g = job['plan']['goal']
        last = job['results'][-1] if job['results'] else {}
        if job['state'] == 'succeeded' and last.get('mode') == 'dock':
            # 정밀 주차는 Nav2 정차점보다 ~10cm 더 들어가 마커 기준 자세에 선다 → 정차점과의 거리 대신 주차 결과 (10-22)
            job['dock_error'] = last.get('final')
        elif job['end_pose'] and job['state'] == 'succeeded':
            job['end_error_cm'] = round(math.dist((job['end_pose']['x'], job['end_pose']['y']), g['xy']), 1)
        job['progress'] = None
        if job['state'] == 'succeeded' and g.get('node') in self.notify_cfg.get('dests', []) and self.notify_cfg.get('url'):
            docked = any(x.get('mode') == 'dock' and x.get('status') == 'ok' for x in job['results'])
            if self.graph.nodes[g['node']].get('dock') and not docked:
                # 정밀 주차가 되는 목적지는 정밀 주차까지 끝나야 '도착' (OMX 가 박스를 내려놓는 자세)
                job['notify'] = dict(url=self.notify_cfg['url'], status=None, error='안 보냄: 정밀 주차를 안 함 ("dock": false)')
            else:
                job['notify'] = self.send_arrived(job)
        os.makedirs(LOGS, exist_ok=True)
        json.dump(job, open(os.path.join(LOGS, f'job_{time.strftime("%m%d_%H%M%S")}_{job["id"]}.json'), 'w'),
                  ensure_ascii=False, indent=1, default=str)

    def load_notify(self):
        try:
            return json.load(open(NOTIFY_FILE))
        except (OSError, ValueError):
            return dict(url=None, dests=['PHARMACY'])

    def save_notify(self, cfg):
        os.makedirs(os.path.dirname(NOTIFY_FILE), exist_ok=True)
        json.dump(cfg, open(NOTIFY_FILE, 'w'), ensure_ascii=False, indent=1)
        self.notify_cfg = cfg

    def send_arrived(self, job):
        """도착 신호 POST (3번까지 다시 시도). 반환 dict(url, status | error) — 작업 기록에 남김"""
        import urllib.error
        import urllib.request
        g = job['plan']['goal']
        body = dict(event='arrived', dest=g['node'], robot=dict(serial=self.info['serial'], ips=self.info['ips']),
                    job_id=job['id'], time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), pose=job.get('end_pose'),
                    dock_error=job.get('dock_error'))
        url = self.notify_cfg['url']
        out = dict(url=url)
        for i in range(3):
            try:
                req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                             headers={'Content-Type': 'application/json', **(self.notify_cfg.get('headers') or {})})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    out.update(status=resp.status, error=None, response=resp.read(500).decode('utf-8', 'replace')); break
            except urllib.error.HTTPError as e:   # 서버가 답은 함 (4xx 는 다시 보내도 같음 → 그만, 5xx 만 다시)
                out.update(status=e.code, error=f'HTTP {e.code}', response=e.read(500).decode('utf-8', 'replace'))
                if e.code < 500:
                    break
                time.sleep(1)
            except Exception as e:  # noqa: BLE001   연결 실패·시간 초과 → 다시
                out.update(status=None, error=f'{type(e).__name__}: {e}')
                time.sleep(1)
        print(f'도착 신호 {body["dest"]} → {url}: {out}', flush=True)
        return out

    def status(self):
        p = self.robot.pose()
        j = self.job
        return dict(robot=self.info, frame='diagram cm, lidar center, heading deg (0=+x, 90=+y)',
                    pose=p, localized=p is not None, nav2_ready=self.robot.nav_ready(),
                    state=(j['state'] if j and j['state'] == 'running' else 'idle'),
                    job=summary(j) if j else None)


def summary(j):
    return {k: j.get(k) for k in ('id', 'state', 'request', 'segment', 'segments_total', 'progress', 'error', 't_start',
                                   'time_s', 'end_pose', 'end_error_cm', 'dock_error', 'notify')}


def make_app(api):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    def err(code, msg):
        return jsonify(error=msg), code

    @app.before_request
    def deny_commands():
        """차단 목록의 PC 가 보낸 명령(POST·PUT)은 거절 (조회 GET 은 허용). 10-22 사용자 요청"""
        if request.method in ('POST', 'PUT'):
            try:
                deny = {ln.split('#')[0].strip() for ln in open(DENY_FILE)} - {''}
            except OSError:
                return None
            if request.remote_addr in deny:
                return err(403, f'{request.remote_addr} 의 명령은 지금 막혀 있음 (로봇 {DENY_FILE})')
        return None

    @app.get('/')
    def index():
        return jsonify(api='pinky', robot=api.info, endpoints=['GET /status', 'GET /dests', 'GET /plan?x=&y=[&heading=]|?dest=',
                       'POST /goto {x,y[,heading]} | {dest[,dock]}', 'POST /cancel', 'GET /jobs', 'GET /jobs/<id>',
                       'POST /set_pose {name} | {x,y,heading} | {find:true}', 'GET|PUT /notify'],
                       docs='/docs', openapi='/openapi.json')

    @app.get('/openapi.json')
    def openapi_json():
        return jsonify(openapi.spec())

    @app.get('/docs')
    def docs():
        return openapi.SWAGGER_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

    @app.get('/status')
    def status():
        return jsonify(api.status())

    @app.get('/dests')
    def dests():
        return jsonify({k: dict(xy=n['xy'], heading=n.get('heading'), name=n.get('name'), dock=n.get('dock'))
                        for k, n in api.graph.stops().items()})

    @app.get('/plan')
    def plan():
        a = request.args
        start = None
        if a.get('from'):
            v = [float(s) for s in a['from'].split(',')]
            start = (v[0], v[1], v[2] if len(v) > 2 else 0.0)
        body = dict(dest=a.get('dest'), x=a.get('x', type=float), y=a.get('y', type=float),
                    heading=a.get('heading', type=float), dock=(a.get('dock') in ('1', 'true')) if a.get('dock') else None)
        try:
            return jsonify(api.plan(body, start))
        except LookupError as e:
            return err(503, str(e))
        except ValueError as e:
            return err(400, str(e))

    @app.post('/goto')
    def goto():
        body = request.get_json(silent=True) or {}
        try:
            job, busy = api.start(body)
        except LookupError as e:
            return err(503, str(e))
        except ValueError as e:
            return err(400, str(e))
        if busy:
            return err(409, busy)
        return jsonify(job=summary(job), plan=job['plan']), 202

    @app.post('/cancel')
    def cancel():
        j = api.job
        if not j or j['state'] != 'running':
            api.robot.halt()
            return jsonify(canceled=None, state='idle')
        api.cancel.set()
        t = time.time()
        while j['state'] == 'running' and time.time() - t < 15:
            time.sleep(0.05)
        return jsonify(canceled=j['id'], state=j['state'])

    @app.get('/notify')
    def notify_get():   # 헤더 값(키)은 가려서 보여 줌
        c = dict(api.notify_cfg)
        c['headers'] = {k: (v[:4] + '…' if len(str(v)) > 4 else '…') for k, v in (c.get('headers') or {}).items()}
        return jsonify(c)

    @app.put('/notify')
    def notify_put():
        """도착 신호 받을 주소 등록. {"url": "http://..." | null(끄기), "dests": ["PHARMACY"]}"""
        b = request.get_json(silent=True) or {}
        url = b.get('url', api.notify_cfg.get('url'))
        if url is not None and not (isinstance(url, str) and url.startswith(('http://', 'https://'))):
            return err(400, 'url 은 http:// 또는 https:// 로 시작하는 주소, 끄려면 null')
        dests = b.get('dests', api.notify_cfg.get('dests', ['PHARMACY']))
        headers = b.get('headers', api.notify_cfg.get('headers') or {})   # 예: {"X-Robot-Api-Key": "..."} (관제 서버가 키를 요구하면)
        if not isinstance(headers, dict):
            return err(400, 'headers 는 {"이름": "값"}')
        unknown = [d for d in dests if d not in api.graph.alias]
        if unknown:
            return err(400, f'모르는 목적지 {unknown}. GET /dests 참고')
        api.save_notify(dict(url=url, dests=dests, headers=headers))
        return notify_get()

    @app.get('/jobs')
    def jobs():
        return jsonify([summary(api.jobs[i]) for i in reversed(api.order)])

    @app.get('/jobs/<jid>')
    def job(jid):
        j = api.jobs.get(jid)
        if not j:
            return err(404, f'작업 {jid} 없음')
        return jsonify({k: v for k, v in j.items() if k != 't0'})

    @app.post('/set_pose')
    def set_pose():
        if api.job and api.job['state'] == 'running':
            return err(409, '주행 중에는 못 넣음 — 먼저 /cancel')
        b = request.get_json(silent=True) or {}
        if b.get('find'):
            args = ['--find']
        elif b.get('name'):
            args = [str(b['name'])]
        elif b.get('x') is not None and b.get('y') is not None and b.get('heading') is not None:
            args = [f'{float(b["x"])},{float(b["y"])}', str(float(b['heading']))]
        else:
            return err(400, '{"name":"A"} | {"x":..,"y":..,"heading":..} | {"find":true}')
        try:
            p = subprocess.run([sys.executable, os.path.join(TOOLS, 'set_pose.py'), *args], cwd=TOOLS,
                               capture_output=True, text=True, timeout=150)
        except subprocess.TimeoutExpired:
            return err(504, 'set_pose.py 시간 초과')
        lines = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
        return jsonify(ok=p.returncode == 0, output=lines[-8:], pose=api.robot.pose()), (200 if p.returncode == 0 else 422)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8080)
    a = ap.parse_args()
    api = Api(Robot())

    def bye(sig, _):   # rclpy 가 신호를 먹어 Flask 만 반쯤 살아남는 것 방지 (10-22): 멈추고 바로 끝냄
        if api.job and api.job['state'] == 'running':
            api.cancel.set(); time.sleep(1)
        api.robot.halt()
        os._exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    print(f'Pinky API {api.info} → http://{a.host}:{a.port}', flush=True)
    make_app(api).run(host=a.host, port=a.port, threaded=True)


if __name__ == '__main__':
    main()
