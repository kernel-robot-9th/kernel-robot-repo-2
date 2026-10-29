# FMS 가 부르는 구간 주행: POST /drive, POST /action, GET /status 의 drive 칸 (설계: FMS ↔ Pinky 주행 API 설계 문서, 10-29)
# 엣지 주행은 tools/edge_drive.py (edge_run.py 측정과 같은 코드). 작업 스레드 하나, 한 번에 명령 하나.
import json
import math
import os
import threading
import time
import traceback

from edge_drive import DRIVEABLE, Times, face, load_graph

AT_NODE_CM = 5.0                   # 라이다 중심이 노드에서 이만큼 안이면 '그 노드에 있음'
RUNNING = ('rotating', 'driving', 'acting')
OK_STATUS = ('ok', 'already_past')  # already_past = 테이프 따라가기 목표를 이미 지남 (노드 위)


def angdiff(a, b):
    return (a - b + 180) % 360 - 180


class DriveCtl:
    def __init__(self, robot, logs, is_busy_other):
        self.robot, self.logs, self.is_busy_other = robot, logs, is_busy_other
        self.N, self.E = load_graph()
        self.times = Times()
        self.drv = None
        self.cancel_ev = threading.Event()
        self.lock = threading.Lock()
        self.s = dict(cmd_id=None, kind=None, state='idle', node=None, edge=None, edge_index=None, edges_total=0,
                      edge_t0=None, edge_expected_s=None, expected_s=None, done_edges=[], last_mode=None, error=None,
                      t_start=None, t0=None, results=[])

    # ---------- 상태 ----------
    def running(self):
        return self.s['state'] in RUNNING

    def nearest_node(self, p, tol=AT_NODE_CM):
        best = min(self.N, key=lambda k: math.dist((p['x'], p['y']), self.N[k]['xy']))
        return best if math.dist((p['x'], p['y']), self.N[best]['xy']) <= tol else None

    def status(self):
        s = self.s
        p = self.robot.pose()
        node = s['node']
        if node is None and not self.running() and s['edge'] is None and p is not None:
            node = self.nearest_node(p)   # 명령 받기 전(켜진 직후): 가까운 노드
        prog = elapsed = None
        if s['edge'] and p is not None:
            (ax, ay), (bx, by) = self.N[s['edge'][0]]['xy'], self.N[s['edge'][1]]['xy']
            L2 = (bx - ax) ** 2 + (by - ay) ** 2
            prog = 0.0 if s['state'] == 'rotating' or L2 == 0 else \
                round(min(1.0, max(0.0, ((p['x'] - ax) * (bx - ax) + (p['y'] - ay) * (by - ay)) / L2)), 2)
            elapsed = round(time.time() - s['edge_t0'], 1) if s['edge_t0'] and self.running() else None
        return dict(cmd_id=s['cmd_id'], kind=s['kind'], state=s['state'], node=node, edge=s['edge'],
                    edge_index=s['edge_index'], edges_total=s['edges_total'], edge_progress=prog, edge_elapsed_s=elapsed,
                    edge_expected_s=s['edge_expected_s'], expected_s=s['expected_s'], done_edges=s['done_edges'],
                    error=s['error'], t_start=s['t_start'])

    # ---------- 명령 받기 ----------
    def _driver(self):
        if self.drv is None:
            from edge_drive import EdgeDriver
            self.drv = EdgeDriver(self.N, self.E)        # IR · odom · TF 가 5초 안에 안 오면 RuntimeError
            self.drv.should_stop = self.cancel_ev.is_set
        return self.drv

    def _check_common(self, body):
        """반환 (http, err dict) 또는 None"""
        cid = body.get('cmd_id')
        if not isinstance(cid, str) or not cid:
            return 400, dict(error='bad_request', why='cmd_id (문자열) 필요')
        if self.running() or self.is_busy_other():
            return 409, dict(error='busy', why=f'명령 {self.s["cmd_id"]} 실행 중 — 먼저 /cancel' if self.running() else '/goto 작업 중')
        p = self.robot.pose()
        if p is None:
            return 409, dict(error='not_localized', why='map → base_footprint TF 없음 (/set_pose)')
        return None

    def duplicate(self, body):
        if body.get('cmd_id') and body.get('cmd_id') == self.s['cmd_id']:
            return 200, dict(accepted=True, duplicate=True, **self.status())
        return None

    def start_drive(self, body):
        with self.lock:
            d = self.duplicate(body)
            if d:
                return d
            e = self._check_common(body)
            if e:
                return e
            route = body.get('route')
            if not isinstance(route, list) or len(route) < 2 or not all(isinstance(r, str) for r in route):
                return 400, dict(error='bad_request', why='route = 노드 이름 2개 이상')
            p = self.robot.pose()
            resume = route[0] == '@here'
            if resume:   # 엣지 중간에 멈춘 뒤: 그 엣지 끝 노드까지 마저
                pe = self.s['edge']
                if self.s['node'] is not None or not pe or self.s['state'] not in ('canceled', 'failed'):
                    return 409, dict(error='not_at_start', why='"@here" 는 엣지 중간에 멈췄을 때만')
                if route[1] != pe[1]:
                    return 409, dict(error='not_at_start', why=f'"@here" 다음은 멈춘 엣지의 끝 노드 {pe[1]}')
                pairs = [tuple(pe)] + list(zip(route[1:], route[2:]))
            else:
                if route[0] not in self.N:
                    return 400, dict(error='unknown_edge', why=f'노드 {route[0]} 없음')
                at_dock = self.s['last_mode'] == 'dock_in' and self.s['node'] == route[0]   # 정밀 주차 자리 = 마커 기준
                dist = math.dist((p['x'], p['y']), self.N[route[0]]['xy'])
                if dist > AT_NODE_CM and not at_dock:
                    return 409, dict(error='not_at_start', why=f'{route[0]} 에서 {dist:.1f} cm')
                pairs = list(zip(route, route[1:]))
            for a, b in pairs:
                if (a, b) not in self.E or self.E[(a, b)]['mode'] not in DRIVEABLE:
                    return 400, dict(error='unknown_edge', why=f'{a} → {b} 엣지 없음')
            nxt = body.get('next')
            if nxt is not None and (pairs[-1][1], nxt) not in self.E:
                return 400, dict(error='unknown_edge', why=f'next: {pairs[-1][1]} → {nxt} 엣지 없음')
            end_h = body.get('end_heading')
            try:
                self._driver()
            except Exception as ex:  # noqa: BLE001
                return 503, dict(error='not_ready', why=str(ex))
            # 예상 시간
            h, exp = p['heading'], []
            for i, (a, b) in enumerate(pairs):
                f = face(self.N, self.E, a, b)
                rot = 0.0 if (resume and i == 0) else self.times.rot_s(angdiff(f, h))
                exp.append(round(rot + self.times.move_s(self.N, self.E, a, b), 1)); h = f
            if end_h is not None:
                exp[-1] = round(exp[-1] + self.times.rot_s(angdiff(float(end_h), h)), 1)
            self._begin(body['cmd_id'], 'drive', len(pairs), round(sum(exp), 1))
            threading.Thread(target=self._run_drive, args=(pairs, resume, nxt, end_h, exp, body), daemon=True).start()
            return 202, dict(accepted=True, cmd_id=body['cmd_id'], edges=len(pairs), expected_s=self.s['expected_s'])

    def start_action(self, body):
        with self.lock:
            d = self.duplicate(body)
            if d:
                return d
            e = self._check_common(body)
            if e:
                return e
            kind = body.get('kind')
            if kind not in ('spin', 'rotate'):
                return 400, dict(error='bad_request', why='kind = spin | rotate')
            if kind == 'rotate' and body.get('heading') is None:
                return 400, dict(error='bad_request', why='rotate 는 heading (deg) 필요')
            try:
                self._driver()
            except Exception as ex:  # noqa: BLE001
                return 503, dict(error='not_ready', why=str(ex))
            p = self.robot.pose()
            exp = self.times.rot_s(120) * 3 if kind == 'spin' else self.times.rot_s(angdiff(float(body['heading']), p['heading']))
            self._begin(body['cmd_id'], kind, 0, round(exp, 1))
            threading.Thread(target=self._run_action, args=(body,), daemon=True).start()
            return 202, dict(accepted=True, cmd_id=body['cmd_id'], expected_s=self.s['expected_s'])

    def _begin(self, cid, kind, n, exp):
        node = self.s['node']
        if node is None and self.s['edge'] is None:
            p = self.robot.pose()
            node = self.nearest_node(p) if p else None
        self.cancel_ev.clear()
        self.s.update(cmd_id=cid, kind=kind, state='acting' if kind != 'drive' else 'rotating', node=node,
                      edge=self.s['edge'] if kind != 'drive' else None, edge_index=None, edges_total=n, edge_t0=None,
                      edge_expected_s=None, expected_s=exp, done_edges=[], error=None,
                      t_start=time.strftime('%Y-%m-%d %H:%M:%S'), t0=time.time(), results=[])

    # ---------- 실행 (작업 스레드) ----------
    def _fail(self, code, why=None):
        self.s['state'] = 'canceled' if code == 'canceled' else 'failed'
        self.s['error'] = None if code == 'canceled' else dict(code=code, why=why)

    def _run_drive(self, pairs, resume, nxt, end_h, exp, body):
        drv, N, E, s = self.drv, self.N, self.E, self.s
        try:
            drv.dr.spin(0.3)   # 쉬는 동안 낡은 TF·odom 갱신
            for i, (a, b) in enumerate(pairs):
                mode = E[(a, b)]['mode']
                hd = round(face(N, E, a, b)) % 360
                s.update(edge=[a, b], edge_index=i, node=None if (resume and i == 0) else a, edge_expected_s=exp[i],
                         edge_t0=time.time(), state='rotating')
                t0 = time.time()
                st = 'ok'
                if not (resume and i == 0) and abs(angdiff(hd, drv.lidar_pose()[2])) > 1.5:
                    st = drv.rotate(hd)
                t1 = time.time()
                if st == 'ok':
                    if i + 1 < len(pairs):
                        nh = round(face(N, E, *pairs[i + 1])) % 360
                    elif nxt is not None:
                        nh = round(face(N, E, b, nxt)) % 360
                    else:
                        nh = None if end_h is None else round(float(end_h)) % 360
                    s['state'], s['node'] = 'driving', None
                    st, extra = drv.move(a, b, mode, hd, nh)
                else:
                    extra = {}
                drv.dr.spin(0.3)
                x, y, th = drv.lidar_pose()
                s['results'].append(dict(a=a, b=b, mode=mode, status=st, rot_s=round(t1 - t0, 2), move_s=round(time.time() - t1, 2),
                                         end=[round(x, 1), round(y, 1), round(th, 1)], extra=extra))
                if st not in OK_STATUS:
                    if s['state'] == 'rotating':   # 출발 전 회전에서 실패 = 아직 a 노드 위
                        s.update(node=a, edge=None)
                    self._fail(st, extra.get('why') or (drv.dock_log[-1] if mode == 'dock' and drv.dock_log else None))
                    return
                s['done_edges'].append([a, b])
                s['last_mode'] = ('dock_out' if N[a].get('type') == 'dock' else 'dock_in') if mode == 'dock' else mode
                s['node'] = b
            if end_h is not None:
                s['state'] = 'rotating'
                st = drv.rotate(float(end_h))
                if st != 'ok':
                    self._fail(st); return
            s.update(state='done', edge=None, edge_t0=None)
        except Exception as ex:  # noqa: BLE001
            traceback.print_exc()
            drv.stop()
            self._fail('exception', f'{type(ex).__name__}: {ex}')
        finally:
            self._save(body)

    def _run_action(self, body):
        drv, s = self.drv, self.s
        try:
            drv.dr.spin(0.3)
            st = drv.spin360() if body['kind'] == 'spin' else drv.rotate(float(body['heading']))
            s['results'].append(dict(kind=body['kind'], status=st, time_s=round(time.time() - s['t0'], 2)))
            if st != 'ok':
                self._fail(st); return
            s['state'] = 'done'
        except Exception as ex:  # noqa: BLE001
            traceback.print_exc()
            drv.stop()
            self._fail('exception', f'{type(ex).__name__}: {ex}')
        finally:
            self._save(body)

    def _save(self, body):
        s = self.s
        out = dict(request=body, state=s['state'], error=s['error'], node=s['node'], edge=s['edge'],
                   time_s=round(time.time() - s['t0'], 1), expected_s=s['expected_s'], results=s['results'],
                   t_start=s['t_start'], end_pose=self.robot.pose())
        print(f'drive {s["cmd_id"]}: {s["state"]} {s["error"] or ""} {out["time_s"]}s', flush=True)
        try:
            os.makedirs(self.logs, exist_ok=True)
            json.dump(out, open(os.path.join(self.logs, f'drive_{time.strftime("%m%d_%H%M%S")}_{s["cmd_id"]}.json'), 'w'),
                      ensure_ascii=False, indent=1, default=str)
        except OSError:
            pass

    def cancel(self, wait_s=15):
        if not self.running():
            return False
        self.cancel_ev.set()
        t = time.time()
        while self.running() and time.time() - t < wait_s:
            time.sleep(0.05)
        return True
