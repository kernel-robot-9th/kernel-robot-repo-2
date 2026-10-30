# graph_spec.yaml (사람/편집기가 고치는 파일) → graph.yaml (노드·엣지 전부) + graph.png + 엣지별 벽 여유
#   python3 build_graph.py                # graph_spec.yaml 읽어서 만들기
#   python3 graph_editor.py               # 브라우저 편집기 (http://localhost:8765)
import math
import os
import sys

import cv2
import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '../tools')
SPEC = os.path.join(HERE, 'graph_spec.yaml')
sys.path.insert(0, TOOLS)
_argv = sys.argv; sys.argv = [sys.argv[0]]
import scan_fit as sf  # noqa: E402  (map_drawn 벽까지 거리 dmap)
sys.argv = _argv
BODY_R = {'bare': 5.5, 'bowl': 7.0}   # cm: 핑키 몸체 Ø11 / OMX 그릇 Ø14 실은 상태
PANEL_Y = 0.0         # 아래 바깥벽 바닥 패널 앞면 (라이다엔 안 보여 맵에는 y=-1 에 벽) → 여유 계산에 따로 넣는다
MODES = ('line', 'transfer', 'wall', 'nav', 'dock')   # dock = 정밀 주차 자리(type dock)로 들어가기 / 나오기 (10-29)
NODE_TYPES = ('gate', 'way', 'stop', 'dock')

HEADER = """\
# 주행 그래프 요약 (사람·편집기가 고치는 파일) → python3 build_graph.py → graph.yaml (노드·엣지 전부), graph.png
# 편집기: python3 graph_editor.py → http://localhost:8765  (저장하면 이 파일을 다시 쓰고, 이전 것은 backup/ 에 둔다)
# 좌표: 그림 cm (왼쪽 아래 원점, y 위), 위치 = 라이다 중심, 방향 deg (0 = +x, 90 = +y)
# 자동으로 생기는 것: 차선 노드 <차선>_<x> (예: B1_130) 와 차선 엣지(line), 경계점(gate) <-> 같은 x 의 차선들(transfer),
#   같은 갈림목 x 의 이웃 차선끼리 차선 바꾸기(transfer, 예: B1_40-B2_40)
# lane_skip: 못 가는 차선 노드 목록 — 그 노드와 거기 붙는 자동 엣지를 만들지 않음 (예: T2_20 콘센트 자리)
# 노드 type: gate(복도 경계 바로 밖, jct = [복도, x] 갈림목과 연결) / way(경유점) / stop(목적지, heading)
# 엣지 mode
#   line     교행 복도 흰 테이프 따라가기 (IR). 차선 방향 고정 없음 — 관제가 차선을 골라 예약
#   transfer 복도 차선 <-> 경계점, 또는 같은 갈림목의 차선 <-> 차선 (테이프 없음). 들어갈 때: 직진하다 IR 로 테이프 잡고 꺾기 /
#            나올 때: odom 으로 갈림목 x 에서 꺾어 나오고 AMCL 재확인. 차선 바꾸기 = 갈림목 x 에서 90° 돌아 직진, 새 테이프 잡고 꺾기
#            먼 차선으로 갈 때는 가까운 차선을 가로지른다 → 갈림목 구역(jct_*) 예약
#   wall     협로 라이다 벽 따라가기 (corridor_drive.py). wall = 따라갈 벽 선분, 벽 없는 구간은 AMCL
#   nav      Nav2 FollowPath
# zone: 예약 단위. 같은 zone 의 엣지는 한 번에 1대 (corr_* 는 차선마다 따로)
# 2026-10-22 사용자 결정: 목적지 12곳, 차선 2줄(벽에서 7.5cm, 테이프 폭 2.4cm), 우측통행 고집 안 함,
#   왼쪽 협로도 벽 따라가기, 단일차선 협로·왼쪽 1인실은 보류, 계단 통로는 Nav2 대각선 (40,70)-(130,90) 직선
# 로봇 몸체 Ø11, OMX 그릇 Ø14 (그릇 실은 상태). 교행 허용: 빈 로봇끼리, 빈 로봇 + 그릇 로봇. 그릇 로봇끼리는 교행 금지
"""


def load_spec(path=SPEC):
    return yaml.safe_load(open(path))


def _flow(v):
    return yaml.safe_dump(v, allow_unicode=True, default_flow_style=True, width=10000, sort_keys=False).strip()


def dump_spec(spec, path=SPEC):
    """한 줄에 노드/엣지 하나씩 (사람이 읽기 좋게)"""
    out = [HEADER]
    out.append('lanes:            # 교행 복도 차선 = 흰 테이프 중심')
    out += [f'  {k}: {_flow(v)}' for k, v in spec['lanes'].items()]
    out.append('junctions:        # 복도 위 갈림목 x → 차선마다 노드 (예: B1_130, B2_130)')
    out += [f'  {k}: {_flow(sorted(v))}' for k, v in spec['junctions'].items()]
    if spec.get('lane_skip'):
        out.append(f"lane_skip: {_flow(spec['lane_skip'])}   # 못 가는 차선 노드 — 노드·차선 엣지·transfer 를 만들지 않음 (T2_20: 콘센트 자리, 10-28 사용자)")
    if spec.get('junction_info'):
        out.append('junction_info:    # 갈림목(차선 노드)에 붙이는 속성. role: wait = 대기(비켜 주기) 자리')
        for c, d in spec['junction_info'].items():
            out.append(f'  {c}:')
            out += [f"    '{x}': {_flow(v)}" for x, v in sorted(d.items(), key=lambda kv: float(kv[0]))]
    out.append('')
    out.append('nodes:')
    order = {t: i for i, t in enumerate(NODE_TYPES)}
    for k, v in sorted(spec['nodes'].items(), key=lambda kv: order.get(kv[1].get('type'), 9)):
        out.append(f'  {k}: {_flow(v)}')
    out.append('')
    out.append('edges:            # 양방향. 차선 노드(B1_130 등)도 a/b 로 쓸 수 있음')
    out += [f'  - {_flow(e)}' for e in spec['edges']]
    open(path, 'w').write('\n'.join(out) + '\n')


def body_gap(pts, step=0.5):
    """폴리라인을 따라 로봇 중심과 벽 사이 최소 거리 cm 와 그 위치 (여유 = 이 값 - 반경)"""
    P = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        P += [(x0 + (x1 - x0) * t / n, y0 + (y1 - y0) * t / n) for t in range(n + 1)]
    P = np.array(P, float)
    d = np.minimum(sf.dmap(P / 100) * 100, P[:, 1] - PANEL_Y)
    k = int(d.argmin())
    return float(d[k]), [round(float(P[k, 0])), round(float(P[k, 1]))]


def build(spec):
    """반환 (nodes, edges, errors). errors 가 있어도 만들 수 있는 만큼 만든다"""
    nodes, edges, errors = {}, [], []

    def add_edge(a, b, mode, zone, **kw):
        if a not in nodes or b not in nodes:
            errors.append(f'엣지 {a}-{b}: 없는 노드 {[n for n in (a, b) if n not in nodes]}'); return
        pa, pb = nodes[a]['xy'], nodes[b]['xy']
        dist, at = body_gap([pa, pb])
        edges.append(dict(a=a, b=b, mode=mode, zone=zone, length_cm=round(math.hypot(pb[0] - pa[0], pb[1] - pa[1]), 1),
                          gap_bare_cm=round(dist - BODY_R['bare'], 1), gap_bowl_cm=round(dist - BODY_R['bowl'], 1), gap_at=at, **kw))

    skip = set(spec.get('lane_skip') or [])            # 못 가는 차선 노드 (예: T2_20 콘센트 자리, 10-28 사용자)
    for lane, L in spec['lanes'].items():
        xs = [x for x in sorted(spec['junctions'].get(L['corridor'], [])) if f'{lane}_{x:g}' not in skip]
        info = spec.get('junction_info', {}).get(L['corridor'], {})
        for x in xs:
            nodes[f'{lane}_{x:g}'] = dict(xy=[x, L['y']], type='lane', lane=lane, **info.get(f'{x:g}', {}))
        for x0, x1 in zip(xs, xs[1:]):
            add_edge(f'{lane}_{x0:g}', f'{lane}_{x1:g}', 'line', f'corr_{lane}', auto=True)
    for cor, xs in spec['junctions'].items():           # 차선 바꾸기: 같은 갈림목 x 의 이웃 차선끼리 (2026-10-26 사용자)
        lanes = sorted((ln for ln, L in spec['lanes'].items() if L['corridor'] == cor), key=lambda ln: spec['lanes'][ln]['y'])
        for x in sorted(xs):
            for l0, l1 in zip(lanes, lanes[1:]):
                if f'{l0}_{x:g}' in skip or f'{l1}_{x:g}' in skip:
                    continue
                add_edge(f'{l0}_{x:g}', f'{l1}_{x:g}', 'transfer', f'jct_{cor}{x:g}', crosses=[], auto=True)
    for k, n in spec['nodes'].items():
        if k in nodes:
            errors.append(f'노드 이름 {k} 가 차선 노드와 겹침'); continue
        if n.get('type') not in NODE_TYPES:
            errors.append(f'노드 {k}: type 은 {NODE_TYPES} 중 하나'); continue
        nodes[k] = dict(n)
    for k, n in spec['nodes'].items():
        if n.get('type') != 'gate':
            continue
        cor, x = n.get('jct', [None, None])
        lanes = [ln for ln, L in spec['lanes'].items() if L['corridor'] == cor]
        if not lanes or f'{lanes[0]}_{x:g}' not in nodes:
            errors.append(f'경계점 {k}: jct {n.get("jct")} 에 해당하는 갈림목 없음'); continue
        lanes.sort(key=lambda ln: abs(spec['lanes'][ln]['y'] - n['xy'][1]))
        for i, ln in enumerate(lanes):
            if f'{ln}_{x:g}' in skip:
                continue
            add_edge(k, f'{ln}_{x:g}', 'transfer', f'jct_{cor}{x:g}', crosses=lanes[:i], auto=True)
    for e in spec['edges']:
        e = dict(e)
        a, b, mode, zone = e.pop('a'), e.pop('b'), e.pop('mode', 'nav'), e.pop('zone', '')
        if mode not in MODES:
            errors.append(f'엣지 {a}-{b}: mode {mode} 은 {MODES} 중 하나')
        add_edge(a, b, mode, zone, **e)
    return nodes, edges, errors


KFONT = '/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf'   # graph.png 목적지 이름(한글)


def diagram_px(x, y, S=1):
    """그림 cm → layout_diagram.png 픽셀 (원점 76,40 px, 1cm = 3.39px)"""
    return int((76 + 3.39 * x) * S), int((40 + 3.39 * (200 - y)) * S)


def draw(nodes, edges, out):
    img = cv2.imread(os.path.join(TOOLS, 'layout_diagram.png'))
    img = cv2.addWeighted(img, 0.4, np.full_like(img, 255), 0.6, 0)
    S = 2; img = cv2.resize(img, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)

    def px(x, y):
        return diagram_px(x, y, S)
    COL = {'line': (0, 150, 240), 'transfer': (200, 120, 200), 'wall': (40, 40, 220), 'nav': (50, 160, 50), 'dock': (200, 0, 200)}
    W = {'line': 5, 'transfer': 2, 'wall': 5, 'nav': 3, 'dock': 3}
    for e in edges:
        c = (170, 170, 170) if e.get('deferred') else COL.get(e['mode'], (0, 0, 0))
        cv2.line(img, px(*nodes[e['a']]['xy']), px(*nodes[e['b']]['xy']), c, W.get(e['mode'], 2), cv2.LINE_AA)
    stop_labels = []
    for k, n in nodes.items():
        p = px(*n['xy']); t = n['type']
        dim = n.get('deferred')
        if t == 'stop':
            cv2.circle(img, p, 12, (170, 170, 170) if dim else ((200, 0, 200) if n.get('dock') else (30, 30, 30)), -1, cv2.LINE_AA)
            h = math.radians(n.get('heading', 0))
            cv2.arrowedLine(img, p, (int(p[0] + 28 * math.cos(h)), int(p[1] - 28 * math.sin(h))), (255, 255, 255), 3, tipLength=0.4)
        else:
            if n.get('role') == 'wait':
                cv2.circle(img, p, 13, (0, 150, 240), 3, cv2.LINE_AA)
            cv2.circle(img, p, {'lane': 6, 'gate': 7, 'way': 6, 'dock': 7}[t], (170, 170, 170) if dim else {'lane': (0, 90, 160), 'gate': (120, 0, 120), 'way': (60, 60, 60), 'dock': (200, 0, 200)}[t], -1, cv2.LINE_AA)
        if t == 'stop':   # 목적지: 방 번호(101호…)·수술실·약제실 + 노드 이름 — 한글이라 아래에서 PIL 로 씀
            nm = n.get('name', '')
            code = nm.split()[0] if nm[:3].isdigit() or nm.startswith('수술실') else ('약제실' if k == 'PHARMACY' else '')
            stop_labels.append(((p[0] + 16, p[1] - 30), f'{code}  {k}' if code else k))
            continue
        if t != 'lane' or n['lane'] in ('B1', 'T2'):
            lab = k if t != 'lane' else k.split('_')[1]
            off = (10, -10) if t != 'lane' else ((-14, 34) if n['lane'] == 'B1' else (-14, -14))
            for col, th in (((0, 0, 0), 4), ((255, 255, 255), 2)):
                cv2.putText(img, lab, (p[0] + off[0], p[1] + off[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, th, cv2.LINE_AA)
    y0 = 28
    for m, lab in (('line', 'line: white tape lanes'), ('transfer', 'transfer: lane <-> gate'), ('wall', 'wall follow'), ('nav', 'Nav2')):
        cv2.line(img, (img.shape[1] - 400, y0), (img.shape[1] - 340, y0), COL[m], 6)
        cv2.putText(img, lab, (img.shape[1] - 330, y0 + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2); y0 += 32
    cv2.line(img, (img.shape[1] - 400, y0), (img.shape[1] - 340, y0), (170, 170, 170), 6)
    cv2.putText(img, 'deferred', (img.shape[1] - 330, y0 + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2)
    if stop_labels:
        from PIL import Image, ImageDraw, ImageFont
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        try:
            font = ImageFont.truetype(KFONT, 26)
        except OSError:
            font = ImageFont.load_default()
        for xy, lab in stop_labels:
            d.text(xy, lab, font=font, fill=(0, 0, 0), stroke_width=3, stroke_fill=(255, 255, 255))
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    cv2.imwrite(out, img)


def write_outputs(spec):
    """graph.yaml + graph.png 쓰기. 반환 (nodes, edges, errors)"""
    nodes, edges, errors = build(spec)
    hdr = ('# 자동 생성: python3 build_graph.py (graph_spec.yaml 에서). 직접 고치지 말 것.\n'
           '# gap_bare_cm / gap_bowl_cm = 엣지를 따라 빈 로봇(Ø11) / 그릇 실은 로봇(Ø14) 과 실측 벽(map_drawn + 바닥 패널) 사이 최소 여유\n')
    with open(os.path.join(HERE, 'graph.yaml'), 'w') as f:
        f.write(hdr)
        yaml.safe_dump(dict(nodes=nodes, edges=edges), f, allow_unicode=True, sort_keys=False, default_flow_style=None, width=200)
    draw(nodes, edges, os.path.join(HERE, 'graph.png'))
    return nodes, edges, errors


if __name__ == '__main__':
    spec = load_spec()
    nodes, edges, errors = write_outputs(spec)
    for e in errors:
        print('⚠️', e)
    act = [e for e in edges if not e.get('deferred')]
    print(f'노드 {len(nodes)}개, 엣지 {len(edges)}개 (보류 {len(edges) - len(act)})')
    from collections import Counter
    print('  모드별:', dict(Counter(e['mode'] for e in act)))
    print('여유 좁은 엣지 (그릇 실은 로봇 기준 < 3cm)       빈 로봇  그릇 로봇')
    for e in sorted(act, key=lambda e: e['gap_bowl_cm']):
        if e['gap_bowl_cm'] < 3:
            print(f"  {e['a']:>7} - {e['b']:<9} {e['mode']:8}   {e['gap_bare_cm']:5.1f}cm  {e['gap_bowl_cm']:5.1f}cm  @{e['gap_at']}")
