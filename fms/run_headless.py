"""FMS 시뮬레이션을 화면 없이 돌려 규칙 위반·충돌·교착을 센다.
  python3 run_headless.py --minutes 60 --rate 2 --robots 3 --seed 1
"""
import argparse
import collections

from fms_core import FMS


def lane_of(f, r):
    """로봇이 교행통로 차선 위에 있으면 차선 이름"""
    g = r.g
    if r.step and r.step['kind'] == 'move' and r.path and r.k < len(r.path) - 1 and r.edge_t > 0:
        return g.edge[(r.path[r.k], r.path[r.k + 1])]['lane']
    return g.nodes[r.node].get('lane')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=60)
    ap.add_argument('--rate', type=float, default=2.0, help='분당 주문 수')
    ap.add_argument('--robots', type=int, default=3)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--dt', type=float, default=0.1)
    ap.add_argument('--planner', default='cbs', choices=['cbs', 'reserve'], help='cbs = A*+CBS, reserve = 최단 경로+예약')
    ap.add_argument('--legs', type=int, default=None, help='CBS 가 내다보는 목적지 수 (기본 FMS.PLAN_LEGS)')
    a = ap.parse_args()

    f = FMS(n_robots=a.robots, seed=a.seed)
    f.p.planner = a.planner
    if a.legs:
        f.PLAN_LEGS = a.legs
    f.auto_rate = a.rate
    steps = int(a.minutes * 60 / a.dt)
    max_wait = collections.defaultdict(float)
    passing = set()
    n_pass = 0
    ms = []
    last_seen = None
    diag, diag_seen = 0, set()               # 계단 통로 대각선 L70–R90 을 지난 횟수
    for _ in range(steps):
        f.step_sim(a.dt)
        for r in f.robots:
            if r.path and r.k < len(r.path) - 1 and r.edge_t > 0 and {r.path[r.k], r.path[r.k + 1]} == {'L70', 'R90'}:
                key = (r.id, id(r.step))
                if key not in diag_seen:
                    diag_seen.add(key)
                    diag += 1
        L = f.plan_stats.get('last')
        if L is not None and L is not last_seen:
            ms.append(L['ms'])
            last_seen = L
        for r in f.robots:
            max_wait[r.id] = max(max_wait[r.id], r.wait_s)
        rs = f.robots
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                x, y = rs[i], rs[j]
                lx, ly = lane_of(f, x), lane_of(f, y)
                bad = (x.loaded and y.loaded and lx and ly and lx != ly and lx[0] == ly[0]
                       and abs(x.pos[0] - y.pos[0]) < 14.0)
                key = (x.id, y.id)
                if bad and key not in passing:
                    n_pass += 1
                    f.log(f'실은 로봇끼리 나란히: {x.id} {lx} / {y.id} {ly} x {x.pos[0]:.0f}/{y.pos[0]:.0f}', 'violation')
                    passing.add(key)
                elif not bad:
                    passing.discard(key)
    ev = [e for e in f.events if e['kind'] in ('violation', 'warn')]
    s = f.snapshot()
    print(f'시간 {a.minutes:.0f}분, 로봇 {a.robots}대, 주문 {len(f.orders)}건 (분당 {a.rate}), 경로 {a.planner}, seed {a.seed}')
    print(f"배송 완료 {s['stats']['delivered']}, 대기 주문 {s['waiting']}, 평균 배송 시간 {s['stats']['avg_delivery_s']}s")
    print(f"위반 {s['stats']['violations']}, 충돌 {s['stats']['collisions']}, 실은 로봇 나란히 {n_pass}")
    print('로봇별 가장 오래 기다림(s):', {k: round(v, 1) for k, v in max_wait.items()})
    print(f'계단 통로 대각선(L70–R90) 지남 {diag}번')
    ps = f.plan_stats
    ms.sort()
    tail = f", 계산 중앙 {ms[len(ms) // 2]}ms · 95% {ms[int(len(ms) * 0.95)]}ms · 최대 {ms[-1]}ms" if ms else ''
    print(f"계획: {ps['replans']}번 (CBS {ps['cbs']}, 우선순위 {ps['prioritized']}, 못 풂 {ps['failed']}){tail}")
    for r in f.robots:
        print(f'  {r.id}: {r.state_name():9s} node {r.node:10s} 피로도 {r.fatigue:3d} 오염 {r.contam:3d} 적재 {r.load} 주문 {len(r.assigned)} '
              f'{("기다림 " + r.wait_why) if r.wait_s else ""}')
    kinds = collections.Counter(e['msg'].split(':')[0] for e in ev)
    print('경고·위반 종류:', dict(kinds))
    for e in ev[-15:]:
        print(f"  [{e['t']:7.1f}] {e['kind']}: {e['msg']}")


if __name__ == '__main__':
    main()
