"""이상 동작 감지기 (11-03): sim_trace.Recorder 가 남긴 jsonl 을 읽어 비효율 장면을 찾고 손실 시간을 잰다.

  python3 detect.py logs/trace_demo.jsonl                 # 표로 출력
  python3 detect.py logs/trace_demo.jsonl --json out.json --md out.md
  python3 detect.py trace.jsonl --video-speed 8 --video-offset 3   # 녹화 영상 시각(배속·시작 지연)도 같이
  python3 detect.py logs/trace_auto_s*.jsonl --md logs/report_auto.md # 여러 실행: 합계 + 손실을 많이 만든 자리 순위
  기록 만들기: run_headless.py --trace 파일 / sim_server.py --trace (logs/ 에 자동)

유형
  backtrack  되돌아감      — 목적지에 닿지 않았는데 지나온 노드로 돌아옴 (비킴·목적지 바뀜·재계획 중 무엇 때문인지)
  detour     경로 바꿈      — 같은 목적지인데 남은 경로가 길어짐. 버린 길 위에 서 있던 로봇 = 원인 후보
  yield_loop 양보 반복      — 같은 복도에서 두 로봇이 차선을 바꿔 가며 비키기만 하고 둘 다 거의 못 나아감
  blocking   길 막는 대기   — 서 있는 로봇이 다른 로봇이 갈 길 위에 있어 그 로봇이 멈춤. 막지 않는 대기 자리 제안
"""
import argparse
import json
import math

from fms_core import PARKING, PHARMACY_QUEUE, Graph, place_of

ACT = ('dock', 'load', 'spin', 'dwell', 'charge')       # 그 자리에서 해야 하는 일 (막아도 정상)
STILL_CM = 0.3                                          # 샘플 사이 이만큼도 안 움직이면 서 있음


def load(path):
    meta, rows = {}, []
    for line in open(path):
        d = json.loads(line)
        if 'meta' in d:
            meta = d['meta']
        else:
            rows.append(d)
    return meta, rows


class Ctx:
    def __init__(self, g, rows):
        self.g, self.rows = g, rows
        self.ids = [r['id'] for r in rows[0]['r']]
        self.dt = rows[1]['t'] - rows[0]['t'] if len(rows) > 1 else 0.5

    def path_time(self, r):
        """남은 경로를 실측 엣지 시간으로 (s). path[0] 은 지금 노드(엣지 위면 뒤쪽 노드)"""
        p, g = r['path'], self.g
        if len(p) < 2:
            return 0.0
        L = g.edge[(p[0], p[1])]['L']
        frac = min(1.0, math.dist((r['x'], r['y']), g.xy(p[1])) / L) if L else 0.0
        return frac * g.edge_s(p[0], p[1], 4.5) + sum(g.edge_s(p[i], p[i + 1], 4.5) for i in range(1, len(p) - 1))

    def corridor(self, node):
        pl = place_of(node)
        return pl if pl in ('위 복도', '아래 복도') else None


def inc(kind, t0, t1, robots, place, what, cause, loss, **kw):
    return dict(kind=kind, t0=round(t0, 1), t1=round(t1, 1), robots=robots, place=place, what=what, cause=cause,
                loss_s=round(loss, 1), **kw)


# ---------------------------------------------------------------------------------------------------------
def find_backtrack(c):
    out = []
    for rid in c.ids:
        hist = []                                   # [노드, 처음 본 t, 마지막 본 t] — 마지막으로 멈춰 일한 뒤부터
        seg = []                                    # 같은 기간의 샘플 (원인 판단용)
        for row in c.rows:
            r = next(x for x in row['r'] if x['id'] == rid)
            if r['kind'] != 'move':
                hist, seg = [], []
                continue
            seg.append((row['t'], r))
            if hist and hist[-1][0] == r['node']:
                hist[-1][2] = row['t']
                continue
            idx = next((i for i in range(len(hist) - 1, -1, -1) if hist[i][0] == r['node']), None)
            if idx is not None and idx < len(hist) - 1:
                t_left, t_back = hist[idx][2], row['t']
                via = [h[0] for h in hist[idx + 1:]]
                far = max(c.g.dist(r['node'], n) for n in via)
                if t_back - t_left >= 3.0 and far >= 10.0:
                    mid = [x for t, x in seg if t_left <= t <= t_back]
                    goals = list(dict.fromkeys(x['to'] for x in mid))
                    if any(x['side'] for x in mid):
                        cause = '비킴 (교착 풀기)'
                    elif any(x['qs'] for x in mid):
                        cause = '약제실 앞 대기 자리로 갔다 돌아옴'
                    elif len(goals) > 1:
                        cause = f'목적지 바뀜 {" → ".join(goals)}'
                    else:
                        cause = '같은 목적지인데 경로를 다시 짬'
                    out.append(inc('backtrack', t_left, t_back, [rid], place_of(r['node']),
                                   f'{rid} 가 {r["node"]} → {" → ".join(via)} → {r["node"]} 로 되돌아옴 ({far:.0f} cm)',
                                   cause, t_back - t_left, via=via, node=r['node'], spot=r['node']))
                hist = hist[:idx + 1]
                hist[-1][2] = row['t']
                continue
            hist.append([r['node'], row['t'], row['t']])
    return out


def find_detour(c):
    out = []
    prev = {}
    pos = {}
    for row in c.rows:
        for r in row['r']:
            pos[r['id']] = r
        for r in row['r']:
            rid = r['id']
            p0 = prev.get(rid)
            prev[rid] = r
            if not (p0 and r['kind'] == 'move' and p0['kind'] == 'move' and r['to'] == p0['to'] and len(r['path']) >= 2
                    and len(p0['path']) >= 2 and not r['side']):
                continue
            old, new = p0['path'], r['path']
            if new[0] in old and old[old.index(new[0]):] == new:
                continue                            # 같은 길을 따라 나아감
            t_new = c.path_time(r)
            if new[0] in old:
                k = old.index(new[0])
                t_old = c.path_time(dict(r, path=old[k:])) if k + 1 < len(old) else 0.0
            else:
                t_old = c.path_time(p0) - c.dt
            extra = t_new - t_old
            if extra < 5.0:
                continue
            ahead = set(old[1:])                    # 원래 가려던 길 위(와 그 가까이)에 있는 로봇 = 원인 후보
            near = ahead | {m for n in ahead for m in c.g.near[n]}
            blockers = sorted((o for o in row['r'] if o['id'] != rid and o['node'] in near),
                              key=lambda o: o['st'] == 'moving')     # 서 있는 로봇이 먼저 (지나가는 로봇은 뒤로)
            cause = ', '.join(f'{o["id"]} 가 {o["node"]} 에 있음 ({o["st"]}{", 약제실 앞 대기 자리" if o["node"] in PHARMACY_QUEUE else ""})'
                              for o in blockers) or '원래 길 위에 로봇 없음'
            out.append(inc('detour', row['t'], row['t'] + extra, [rid] + [o['id'] for o in blockers], place_of(r['node']),
                           f'{rid} → {r["to"]}: 경로 바꿈 {"·".join(old[:6])} ⇒ {"·".join(new[:6])} (+{extra:.0f} s)',
                           cause, extra, old=old, new=new, blockers=[o['id'] for o in blockers],
                           spot=blockers[0]['node'] if blockers and blockers[0]['st'] != 'moving' else None))
    # 같은 로봇·목적지에서 10초 안에 또 바꾼 건 하나로 (왔다 갔다 하는 재계획)
    merged = []
    for d in sorted(out, key=lambda d: (d['robots'][0], d['t0'])):
        m = merged[-1] if merged else None
        if m and m['robots'][0] == d['robots'][0] and d['t0'] - m['t0'] <= 10.0 and m['new'][-1] == d['new'][-1]:
            m['n'] = m.get('n', 1) + 1
            m['loss_s'] = round(m['loss_s'] + d['loss_s'], 1)
            m['t1'] = max(m['t1'], d['t1'])
            m['what'] += f' / 또 바꿈 (+{d["loss_s"]:.0f} s)'
            continue
        merged.append(d)
    return merged


def find_yield_loop(c):
    out = []
    open_ = {}                                       # (a, b) → 진행 중인 장면
    for row in c.rows:
        rs = {r['id']: r for r in row['r']}
        for i, a in enumerate(c.ids):
            for b in c.ids[i + 1:]:
                ra, rb = rs[a], rs[b]
                ca, cb = c.corridor(ra['node']), c.corridor(rb['node'])
                on = (ca and ca == cb and abs(ra['x'] - rb['x']) < 60 and ra['kind'] == rb['kind'] == 'move')
                key = (a, b)
                e = open_.get(key)
                if on:
                    if e is None:
                        e = open_[key] = dict(t0=row['t'], last=row['t'], place=ca, s0={a: ra, b: rb}, s1={},
                                              lanes={a: [], b: []}, moved={a: 0.0, b: 0.0}, prev={a: ra, b: rb})
                    e['last'] = row['t']
                    for rid, r in ((a, ra), (b, rb)):
                        ln = c.g.nodes[r['node']].get('lane')
                        if ln and (not e['lanes'][rid] or e['lanes'][rid][-1] != ln):
                            e['lanes'][rid].append(ln)
                        e['moved'][rid] += math.dist((r['x'], r['y']), (e['prev'][rid]['x'], e['prev'][rid]['y']))
                        e['prev'][rid] = r
                        e['s1'][rid] = r
                elif e is not None and row['t'] - e['last'] > 3.0:
                    del open_[key]
                    x = judge_yield(c, a, b, e)
                    if x:
                        out.append(x)
    for (a, b), e in open_.items():
        x = judge_yield(c, a, b, e)
        if x:
            out.append(x)
    merged = []
    for d in sorted(out, key=lambda d: d['t0']):
        m = next((m for m in merged if m['place'] == d['place'] and d['t0'] <= m['t1'] and set(d['robots']) & set(m['robots'])), None)
        if m is None:
            merged.append(d)
            continue
        m['robots'] = sorted(set(m['robots']) | set(d['robots']))
        m['t1'] = max(m['t1'], d['t1'])
        m['loss_s'] = round(m['t1'] - m['t0'], 1)
        m['what'] = f'{"·".join(m["robots"])} 가 {m["place"]} 에서 {m["loss_s"]:.0f} s 동안 비키기 반복'
        m['cause'] += ' / ' + d['cause']
    return merged


def judge_yield(c, a, b, e):
    dur = e['last'] - e['t0']
    if dur < 8.0:
        return None
    prog = {}
    for rid in (a, b):
        r0, r1 = e['s0'][rid], e['s1'][rid]
        goal = r1['to']
        prog[rid] = c.g.dist(r0['node'], goal) - c.g.dist(r1['node'], goal) if goal == r0['to'] else 0.0
    switches = {rid: max(0, len(e['lanes'][rid]) - 1) for rid in (a, b)}
    # 둘 다 나아간 거리보다 훨씬 많이 움직였거나(제자리에서 비키기), 차선을 위아래로 2번 넘게 바꿈
    stuck = all(e['moved'][r] >= 15.0 and e['moved'][r] >= 2 * (max(prog[r], 0) + 10) for r in (a, b))
    if not (stuck or sum(switches.values()) >= 2):
        return None
    lanes = '; '.join(f'{rid} {"→".join(e["lanes"][rid])}' for rid in (a, b))
    return inc('yield_loop', e['t0'], e['last'], [a, b], e['place'],
               f'{a}·{b} 가 {e["place"]} 에서 {dur:.0f} s 동안 비키기 반복 (차선: {lanes})',
               f'나아간 거리 {a} {prog[a]:.0f} cm · {b} {prog[b]:.0f} cm, 움직인 거리 {e["moved"][a]:.0f} / {e["moved"][b]:.0f} cm',
               dur, switches=switches, progress=prog, spot=e['place'])


def find_blocking(c):
    out, open_ = [], {}
    prev = {}
    for row in c.rows:
        rs = {r['id']: r for r in row['r']}
        still = {rid: (rid in prev and math.dist((r['x'], r['y']), (prev[rid]['x'], prev[rid]['y'])) < STILL_CM)
                 for rid, r in rs.items()}
        seen = set()
        for y in rs.values():                       # y = 막힌 로봇: 갈 길이 남았는데 서 있음
            if not (y['kind'] == 'move' and len(y['path']) >= 2 and still[y['id']]):
                continue
            ahead = set(y['path'][1:])
            ahead |= {m for n in ahead for m in c.g.near[n]}
            for x in rs.values():                   # x = 서서 그 길을 막는 로봇
                if x['id'] == y['id'] or not still[x['id']] or x['kind'] in ACT:
                    continue
                if x['node'] not in ahead and x['id'] not in y['by']:
                    continue
                key = (x['id'], y['id'], x['node'])
                seen.add(key)
                e = open_.setdefault(key, dict(t0=row['t'], x=x, y=y))
                e['t1'], e['xl'], e['yl'] = row['t'], x, y
        for key in list(open_):
            if key not in seen and row['t'] - open_[key]['t1'] > 1.0:
                e = open_.pop(key)
                o = judge_block(c, key, e, rs)
                if o:
                    out.append(o)
        prev = rs
    for key, e in open_.items():
        o = judge_block(c, key, e, {r['id']: r for r in c.rows[-1]['r']})
        if o:
            out.append(o)
    return out


def judge_block(c, key, e, rs):
    xid, yid, node = key
    dur = e['t1'] - e['t0']
    x, y = e['xl'], e['yl']
    spot = x['qs'] or x['kind'] in (None, 'wait_ready') or (x['kind'] == 'move' and x['wait'])
    if dur < (4.0 if spot else 8.0):            # 가는 길 중간 CBS 출발 시각 대기는 8초부터
        return None
    if x['qs'] or x['node'] in PHARMACY_QUEUE:
        why = '약제실 앞 대기 자리에서 기다림'
    elif x['kind'] == 'move' and x['wait']:
        why = f'차례 기다림 ({x["wait"]})'
    elif x['kind'] == 'move':
        why = f'출발 시각 기다림 → {x["to"]}'
    elif x['kind'] == 'wait_ready':
        why = 'OMX 준비 기다림 (배차됨)'
    elif x['node'] in PARKING:
        why = '주차 자리에 서 있음'
    else:
        why = f'서 있음 ({x["st"]})'
    # 막지 않는 다른 대기 자리: 주차 9곳 + 약제실 앞 2곳 중 y 길(과 가까운 곳)에 없고 비어 있는 곳
    ahead = set(y['path'])
    ahead |= {m for n in ahead for m in c.g.near[n]}
    occ = {r['node'] for r in rs.values() if r['id'] != xid}
    goal = x['to'] if x['kind'] == 'move' and x['to'] else None
    cands = [s for s in PARKING + PHARMACY_QUEUE if s not in ahead and s not in occ and s != node]
    if not spot:
        cands = []                                  # 가는 길 중간에 CBS 출발 시각을 기다림: 대기 자리 문제가 아님
    best = min(cands, key=lambda s: c.g.dist(node, s) + (c.g.dist(s, goal) - c.g.dist(node, goal) if goal else 0)) if cands else None
    return inc('blocking', e['t0'], e['t1'], [xid, yid], place_of(node),
               f'{xid} 가 {node} 에 서 있어 {yid} ({y["to"]} 로 가는 중) 가 {dur:.0f} s 멈춤',
               why, dur, node=node, suggest=best, spot=node,
               suggest_txt=f'{best} ({place_of(best)}) 에서 기다렸으면 {yid} 길을 안 막음' if best else '')


# ---------------------------------------------------------------------------------------------------------
NAMES = dict(backtrack='되돌아감', detour='경로 바꿈', yield_loop='양보 반복', blocking='길 막는 대기')


def mmss(t):
    return f'{int(t // 60)}:{t % 60:04.1f}'


def analyze(path):
    meta, rows = load(path)
    c = Ctx(Graph(), rows)
    found = find_backtrack(c) + find_detour(c) + find_yield_loop(c) + find_blocking(c)
    found.sort(key=lambda d: d['t0'])
    return meta, rows, found


def summary(found):
    lines = ['| 유형 | 건수 | 손실 합 (s) |', '|---|---:|---:|']
    for k, nm in NAMES.items():
        ds = [d for d in found if d['kind'] == k]
        lines.append(f'| {nm} | {len(ds)} | {sum(d["loss_s"] for d in ds):.0f} |')
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace', nargs='+', help='여러 개면 실행별 요약 + 합계 + 손실을 많이 만든 자리 순위')
    ap.add_argument('--json', default=None)
    ap.add_argument('--md', default=None)
    ap.add_argument('--video-speed', type=float, default=None, help='녹화 배속 (예: 8) → 영상 시각도 표시')
    ap.add_argument('--video-offset', type=float, default=0.0, help='영상에서 시뮬레이션 0초가 나오는 시각 s')
    a = ap.parse_args()

    def when(d):
        s = f'{mmss(d["t0"])}–{mmss(d["t1"])}'
        if a.video_speed:
            s += f' (영상 {a.video_offset + d["t0"] / a.video_speed:.0f}–{a.video_offset + d["t1"] / a.video_speed:.0f}s)'
        return s

    runs = [(p,) + analyze(p) for p in a.trace]
    if len(runs) == 1:
        path, meta, rows, found = runs[0]
        lines = [f'# 이상 동작 리포트 — {path}', '',
                 f'조건: {json.dumps(meta, ensure_ascii=False)} · 기록 {mmss(rows[-1]["t"])}', ''] + summary(found)
        lines += ['', '| 시각 (시뮬레이션) | 유형 | 로봇 | 위치 | 무엇 | 원인 | 손실 s |', '|---|---|---|---|---|---|---:|']
        for d in found:
            what = d['what'] + (f' → 제안: {d["suggest_txt"]}' if d.get('suggest_txt') else '')
            lines.append(f'| {when(d)} | {NAMES[d["kind"]]} | {"·".join(d["robots"])} | {d["place"]} | {what} | {d["cause"]} | {d["loss_s"]:.0f} |')
    else:
        allf = [d for r in runs for d in r[3]]
        mins = sum(r[2][-1]['t'] for r in runs) / 60
        lines = [f'# 이상 동작 리포트 — 실행 {len(runs)}개 (합 {mins:.0f}분)', '',
                 '| 실행 | ' + ' | '.join(NAMES.values()) + ' | 손실 합 (s) |', '|---|' + '---:|' * (len(NAMES) + 1)]
        for path, meta, rows, found in runs:
            cnt = [sum(d['kind'] == k for d in found) for k in NAMES]
            lines.append(f'| {path} | ' + ' | '.join(map(str, cnt)) + f' | {sum(d["loss_s"] for d in found):.0f} |')
        lines += ['', '## 합계'] + summary(allf)
        spots = {}
        for d in allf:
            if d.get('spot'):
                e = spots.setdefault(d['spot'], dict(n=0, loss=0.0, kinds=set()))
                e['n'] += 1
                e['loss'] += d['loss_s']
                e['kinds'].add(NAMES[d['kind']])
        lines += ['', '## 손실을 많이 만든 자리', '| 자리 | 위치 | 건수 | 손실 합 (s) | 유형 |', '|---|---|---:|---:|---|']
        for k, e in sorted(spots.items(), key=lambda kv: -kv[1]['loss'])[:10]:
            tag = ' (약제실 앞 대기 자리)' if k in PHARMACY_QUEUE else (' (주차 자리)' if k in PARKING else '')
            lines.append(f'| {k}{tag} | {place_of(k) if k in Graph().nodes else k} | {e["n"]} | {e["loss"]:.0f} | {", ".join(sorted(e["kinds"]))} |')
    text = '\n'.join(lines)
    print(text)
    if a.md:
        open(a.md, 'w').write(text + '\n')
    if a.json:
        json.dump([dict(trace=p, meta=m, incidents=f) for p, m, _, f in runs], open(a.json, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
