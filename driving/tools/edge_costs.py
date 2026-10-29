# edge_run.py 측정 기록(edge_logs/edges_*.csv)을 모아 엣지 비용 표를 만든다 (PC 나 로봇 어디서나).
#   python3 edge_costs.py                         # edge_logs/edges_*.csv 전부
#   python3 edge_costs.py edge_logs/edges_1027_*.csv --skip 1027_180501:1,2   # 그 기록의 1·2 번 줄 뺌 (중간 출발 등)
#   python3 edge_costs.py --write                 # graph/edge_times.yaml 로 저장 (FMS 가 읽음)
#   ... --rot edge_logs/rot_1029_*.csv            # 회전 식은 rot_test.py 기록만으로 (회전 속도 바꾼 뒤)
# - 이동 시간: (a→b) 방향별 중앙값, 몇 번 쟀는지, 최소~최대. status ok 만.
# - 회전 시간: 모든 엣지 시작 회전을 모아 t = r0 + |각도| / w 로 맞춤 (90° 와 180° 를 따로도 보여 줌).
import argparse
import csv
import glob
import os
import statistics as st
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'graph', 'edge_times.yaml')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*')
    ap.add_argument('--skip', nargs='*', default=[], help='<기록 이름 일부>:<i,i,..> 이 줄들은 뺌')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--rot', nargs='*', default=None, help='회전 식은 이 rot_test.py 기록(rot_*.csv)만으로 맞춤 (회전 속도를 바꾼 뒤)')
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(os.path.join(HERE, 'edge_logs', 'edges_*[0-9].csv')))
    skip = []
    for s in a.skip:
        k, ii = s.split(':')
        skip.append((k, {int(x) for x in ii.split(',')}))
    move, rot, bad = {}, [], []
    for fn in files:
        for r in csv.DictReader(open(fn)):
            if any(k in fn and int(r['i']) in ii for k, ii in skip):
                continue
            key = (r['a'], r['b'])
            if r['status'] != 'ok':
                bad.append((os.path.basename(fn), r['i'], key, r['status']))
            else:
                move.setdefault(key, []).append((float(r['move_s']), float(r['len_cm']), r['mode'], float(r['err_cm'])))
            ang = abs(float(r['rot_deg']))
            if ang > 1.5:
                rot.append((ang, float(r['rot_s'])))
    print(f'기록 {len(files)}개, 엣지 {len(move)}개 (방향별), 실패 {len(bad)}')
    for b in bad:
        print('  실패', *b)
    print(f'\n{"a → b":22s} {"mode":8s} {"L cm":>5s} {"n":>2s} {"중앙 s":>6s} {"최소~최대":>11s} {"cm/s":>5s} {"L/5":>5s} {"끝 오차":>6s}')
    rows = {}
    for (x, y), v in sorted(move.items(), key=lambda kv: (kv[1][0][2], kv[0])):
        ts = [t for t, *_ in v]
        L, mode = v[0][1], v[0][2]
        med = st.median(ts)
        rows[f'{x}>{y}'] = dict(a=x, b=y, mode=mode, len_cm=L, n=len(ts), move_s=round(med, 2),
                               min_s=round(min(ts), 2), max_s=round(max(ts), 2))
        print(f'{x + " → " + y:22s} {mode:8s} {L:5.1f} {len(ts):2d} {med:6.1f} {min(ts):5.1f}~{max(ts):5.1f} '
              f'{L / med:5.2f} {L / 5:5.1f} {st.median(e for *_, e in v):5.1f}')
    if a.rot:   # 회전 속도를 바꾼 뒤엔 엣지 기록의 예전 회전 대신 rot_test 기록만 (10-29: 0.3 → 0.6 rad/s)
        rot = [(abs(float(r['rot_deg'])), float(r['rot_s'])) for fn in a.rot for r in csv.DictReader(open(fn))
               if r['status'] == 'ok' and abs(float(r['rot_deg'])) > 1.5]
        print(f'회전 식: {len(a.rot)}개 rot_test 기록만 씀')
    fit = None
    if len(rot) >= 2:
        n = len(rot); mx = sum(r[0] for r in rot) / n; my = sum(r[1] for r in rot) / n
        sxx = sum((r[0] - mx) ** 2 for r in rot)
        if sxx > 0:
            k = sum((r[0] - mx) * (r[1] - my) for r in rot) / sxx
            fit = dict(r0_s=round(my - k * mx, 2), s_per_deg=round(k, 4), n=n, src=[os.path.basename(f) for f in a.rot] if a.rot else 'edges')
        print(f'\n회전 {n}번: ' + (f't ≈ {fit["r0_s"]:.1f} s + {fit["s_per_deg"] * 90:.1f} s/90°' if fit else ''))
        for lo, hi in ((60, 120), (150, 210)):
            ts = [t for g, t in rot if lo <= g <= hi]
            if ts:
                print(f'  {lo}~{hi}°: {len(ts)}번, 중앙 {st.median(ts):.1f} s ({min(ts):.1f}~{max(ts):.1f})')
    if a.write:
        doc = dict(note='edge_run.py 실측 (tools/edge_costs.py --write). move_s = 노드에서 멈춰 있다가 다음 노드에 멈출 때까지 (회전 뺌)',
                   made=time.strftime('%Y-%m-%d %H:%M'), files=[os.path.basename(f) for f in files],
                   rotate=fit, edges=rows)
        with open(OUT, 'w') as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        print(f'\n저장: {os.path.normpath(OUT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
