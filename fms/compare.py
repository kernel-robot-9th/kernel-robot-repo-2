"""고정 주문으로 단계 비교 (11-03): 시나리오마다 주문 목록·도착 시각을 정해 두고 두 단계를 끝까지 돌려 비교한다.
무작위 주문(run_headless --rate)은 버전마다 주문 자체가 달라져 흔들리므로, 같은 주문을 넣고 '다 끝나는 시각'을 잰다.

  python3 compare.py                         # v4 vs v5, 시나리오 12개 (+ 발표 주문 9건) → logs/fixed/report.md
  python3 compare.py --profiles v4 v5 --n 12 --orders 15 --rate 1.5

시나리오 k: 주문 N건, 도착 간격 지수분포(분당 rate), 병실 무작위 — 난수 씨앗 k 로 고정. 'demo' = 0초에 발표 주문 9건.
지표: 다 끝난 시각, 평균 배송 시간(주문 → 배송), 감지기(detect.py) 이상 동작 손실.
"""
import argparse
import os
import random
import statistics as st
from multiprocessing import Pool

from fms_core import FMS, ROOMS, apply_profile, room_code
from sim_trace import Recorder

HERE = os.path.dirname(os.path.abspath(__file__))


def scenario(k, n, rate):
    if k == 'demo':
        from demo_quad import ROOMS as DEMO
        return [(0.0, r) for r in DEMO]
    rng = random.Random(1000 + k)
    t, out = 0.0, []
    for _ in range(n):
        out.append((round(t, 1), room_code(rng.choice(ROOMS))))
        t += rng.expovariate(rate / 60.0)
    return out


def run(job):
    prof, k, orders, out_dir, max_min = job
    f = FMS(n_robots=3, seed=k if k != 'demo' else 0)
    apply_profile(f, prof)
    path = os.path.join(out_dir, f'trace_{prof}_{k}.jsonl')
    rec = Recorder(f, path, meta=dict(profile=prof, scenario=k, orders=len(orders)))
    todo, dt = list(orders), 0.1
    while f.t < max_min * 60:
        while todo and f.t >= todo[0][0]:
            f.add_order(todo.pop(0)[1])
        f.step_sim(dt)
        rec.tick()
        if not todo and f.orders and all(o.state == 'delivered' for o in f.orders):
            break
    rec.close()
    done = [o for o in f.orders if o.done_t is not None]
    return dict(prof=prof, k=k, trace=path, delivered=len(done), total=len(orders),
                finish=max((o.done_t for o in done), default=None) if len(done) == len(orders) else None,
                avg=st.mean(o.done_t - o.created for o in done) if done else None,
                violations=f.stats['violations'], collisions=f.stats['collisions'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profiles', nargs='+', default=['v4', 'v5'])
    ap.add_argument('--n', type=int, default=12, help='시나리오 수')
    ap.add_argument('--orders', type=int, default=15, help='시나리오당 주문 수')
    ap.add_argument('--rate', type=float, default=1.5, help='분당 주문 도착')
    ap.add_argument('--max-min', type=float, default=60, help='이 시간(분)까지 안 끝나면 멈춤')
    ap.add_argument('--out', default=os.path.join(HERE, 'logs/fixed'))
    ap.add_argument('-j', type=int, default=os.cpu_count())
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    keys = ['demo'] + list(range(1, a.n + 1))
    jobs = [(p, k, scenario(k, a.orders, a.rate), a.out, a.max_min) for k in keys for p in a.profiles]
    with Pool(a.j) as pool:
        res = pool.map(run, jobs)
    import detect
    for r in res:
        found = detect.analyze(r['trace'])[2]
        r['loss'] = sum(d['loss_s'] for d in found)
        r['kinds'] = {nm: sum(d['kind'] == k for d in found) for k, nm in detect.NAMES.items()}
    by = {(r['prof'], r['k']): r for r in res}
    P = a.profiles
    fm = lambda x: '안 끝남' if x is None else f'{int(x // 60)}:{int(x % 60):02d}'
    lines = [f'# 고정 주문 비교 — {" vs ".join(P)}', '',
             f'시나리오 {a.n}개 × 주문 {a.orders}건 (분당 {a.rate}건 도착) + 발표 주문 9건 · 로봇 3대 · 모두 배송될 때까지', '',
             '| 시나리오 | ' + ' | '.join(f'{p} 끝난 시각' for p in P) + ' | ' + ' | '.join(f'{p} 평균 배송 s' for p in P)
             + ' | ' + ' | '.join(f'{p} 이상 손실 s' for p in P) + ' |',
             '|---|' + '---:|' * (3 * len(P))]
    for k in keys:
        rs = [by[(p, k)] for p in P]
        lines.append(f'| {k} | ' + ' | '.join(fm(r['finish']) for r in rs) + ' | '
                     + ' | '.join(f'{r["avg"]:.0f}' if r['avg'] else '-' for r in rs) + ' | '
                     + ' | '.join(f'{r["loss"]:.0f}' for r in rs) + ' |')
    lines += ['', '| 단계 | 끝난 시각 평균 | 평균 배송 평균 s | 이상 손실 합 s | ' + ' | '.join(detect.NAMES.values())
              + ' | 위반 | 충돌 | 안 끝남 |', '|---|---:|---:|---:|' + '---:|' * (len(detect.NAMES) + 3)]
    for p in P:
        rs = [by[(p, k)] for k in keys]
        fin = [r['finish'] for r in rs if r['finish'] is not None]
        lines.append(f'| {p} | {fm(st.mean(fin)) if fin else "-"} | {st.mean(r["avg"] for r in rs if r["avg"]):.0f} | '
                     f'{sum(r["loss"] for r in rs):.0f} | '
                     + ' | '.join(str(sum(r['kinds'][nm] for r in rs)) for nm in detect.NAMES.values())
                     + f' | {sum(r["violations"] for r in rs)} | {sum(r["collisions"] for r in rs)} | {sum(r["finish"] is None for r in rs)} |')
    if len(P) == 2:
        both = [k for k in keys if by[(P[0], k)]['finish'] and by[(P[1], k)]['finish']]
        diff = [by[(P[1], k)]['finish'] - by[(P[0], k)]['finish'] for k in both]
        if diff:
            better = sum(d < 0 for d in diff)
            lines += ['', f'{P[1]} 가 {P[0]} 보다 끝난 시각: 평균 {st.mean(diff):+.0f} s (중앙 {st.median(diff):+.0f} s), '
                          f'빨라진 시나리오 {better}/{len(diff)}']
    text = '\n'.join(lines)
    print(text)
    open(os.path.join(a.out, 'report.md'), 'w').write(text + '\n')


if __name__ == '__main__':
    main()
