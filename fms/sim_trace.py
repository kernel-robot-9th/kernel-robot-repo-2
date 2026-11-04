"""시뮬레이션 기록기 (11-03): 0.5초(시뮬레이션)마다 로봇 상태를 jsonl 한 줄로. detect.py 가 읽어 이상 동작을 찾는다.

  rec = Recorder(f, 'logs/trace_x.jsonl', meta=dict(profile='v4'))   # f = FMS
  매 step_sim 뒤 rec.tick()  ·  끝나면 rec.close()

줄 형식: 첫 줄 {"meta": {...}}, 그 뒤 {"t", "r": [로봇...], "ev": [그 사이 새 로그], "rp": 누적 재계획 수}
로봇: id node x y st(state_name) task kind to path(남은 노드) wait by(막는 로봇) load contam side(비킴) qs(약제실 앞 대기)
"""
import json


class Recorder:
    def __init__(self, f, path, every=0.5, meta=None):
        self.f, self.every = f, every
        self.out = open(path, 'w')
        self.path = path
        self.next_t = 0.0
        self.last_ev = None
        self.out.write(json.dumps(dict(meta=dict(meta or {}, robots=[r.id for r in f.robots], every=every)),
                                  ensure_ascii=False) + '\n')

    def new_events(self):
        ev = self.f.events
        i = len(ev)
        while i > 0 and ev[i - 1] is not self.last_ev:
            i -= 1
        new = ev[i:] if (i > 0 or self.last_ev is None) else ev[-40:]   # 못 찾으면(300개 넘게 밀림) 끝 40개
        if ev:
            self.last_ev = ev[-1]
        return [dict(e) for e in new]

    def tick(self):
        f = self.f
        if f.t + 1e-9 < self.next_t:
            return
        self.next_t = f.t + self.every
        rs = []
        for r in f.robots:
            s = r.step or {}
            mv = s.get('kind') == 'move'
            rs.append(dict(id=r.id, node=r.node, x=round(r.pos[0], 1), y=round(r.pos[1], 1), st=r.state_name(), task=r.task,
                           kind=s.get('kind'), to=s.get('to'), path=r.path[r.k:] if mv and r.path else [],
                           wait=r.wait_why if r.wait_s > 0 else '', by=sorted(o.id for o in r.blocked_by),
                           load=r.load, contam=r.contam, side=bool(s.get('sidestep')), qs=bool(s.get('queue_spot'))))
        self.out.write(json.dumps(dict(t=round(f.t, 2), r=rs, ev=self.new_events(), rp=f.plan_stats['replans']),
                                  ensure_ascii=False) + '\n')

    def close(self):
        self.out.close()
