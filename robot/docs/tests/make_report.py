#!/usr/bin/env python3
"""Build the two-arm test report (HTML -> PDF) from run_dual_suite.py results.

  python3 docs/tests/make_report.py docs/test_report   # writes report.html; print with Chrome
"""
import html
import json
import os
import statistics as st
import sys

ACTIONS = [
    ('auto', '① 자동 배정 이동', '닿는 팔 중 가까운 팔이 자동으로 수행'),
    ('named_arm', '② 팔 지정 이동', '"왼팔로/오른팔로" 지정한 팔이 수행'),
    ('stack', '③ 쌓기', '블록을 다른 블록 위에 올림'),
    ('handoff', '④ 팔 간 전달', '한 팔로 안 되는 이동을 공유 지점을 거쳐 2단계로'),
    ('carry', '⑤ 양팔 협동 운반', '그릇(트레이) 양끝 손잡이를 두 팔이 함께 들어 옮김'),
]
NAME = {k: n for k, n, _ in ACTIONS}
ARM = {'left': '왼팔', 'right': '오른팔', 'both': '양팔'}
TOL = 30.0   # planner verify_tolerance [mm]


def load(d, f):
    p = os.path.join(d, f)
    return json.load(open(p)) if os.path.exists(p) else []


def e(s):
    return html.escape(str(s))


def arms(r):
    return ' → '.join(ARM.get(a, a) for a in (['left', 'right'] if r['handoff'] else r['arms']))


def cause(r):
    m = r['message']
    if r['success']:
        return ''
    if 'away from the target' in m or 'not seen' in m:
        return '카메라 검증 실패: ' + ('블록이 튕겨 나감' if r['xy_err_mm'] > 100 else
                                     '트레이가 집게에 걸려 들림' if (r.get('tilt_max_deg') or 0) > 10 else
                                     '놓는 중 미끄러짐')
    if 'grasp check failed' in m:
        return '손목 카메라: 손잡이를 제대로 못 잡음'
    return m[:60]


def per_action(rs):
    out = {}
    for k, _, _ in ACTIONS:
        xs = [r for r in rs if r['action'] == k]
        out[k] = (sum(r['success'] for r in xs), len(xs))
    return out


def error_chart(rs):
    """Bar per trial: placement error (log-ish capped scale), tolerance line, failures marked."""
    W, H, L, B, T = 760, 250, 56, 200, 28
    cap = 80.0
    bw = (W - L - 20) / len(rs)
    y = lambda v: B - (min(v, cap) / cap) * (B - T)   # noqa: E731
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             'font-family="Noto Sans CJK KR" font-size="11">']
    for v in (0, 20, 40, 60, 80):
        parts.append(f'<line x1="{L}" x2="{W - 20}" y1="{y(v)}" y2="{y(v)}" stroke="#e3e6ec"/>'
                     f'<text x="{L - 6}" y="{y(v) + 4}" text-anchor="end" fill="#5b6475">{v}</text>')
    parts.append(f'<line x1="{L}" x2="{W - 20}" y1="{y(TOL)}" y2="{y(TOL)}" stroke="#d64545" stroke-dasharray="5 4"/>'
                 f'<text x="{W - 22}" y="{y(TOL) - 5}" text-anchor="end" fill="#d64545">검증 기준 30 mm</text>')
    colors = {'auto': '#2f6fed', 'named_arm': '#7a5af5', 'stack': '#1f9d63', 'handoff': '#e0a106', 'carry': '#c2410c'}
    for i, r in enumerate(rs):
        x = L + i * bw + bw * 0.18
        w = bw * 0.64
        v = r['xy_err_mm']
        c = colors[r['action']] if r['success'] else '#9aa1ad'
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{w:.1f}" height="{B - y(v):.1f}" rx="3" fill="{c}"/>')
        label = f'{v:.0f}' + ('+' if v > cap else '')
        parts.append(f'<text x="{x + w / 2:.1f}" y="{y(v) - 4:.1f}" text-anchor="middle" fill="#1d2433">{label}</text>')
        parts.append(f'<text x="{x + w / 2:.1f}" y="{B + 15}" text-anchor="middle" fill="#1d2433">#{r["trial"]}</text>')
        if not r['success']:
            parts.append(f'<text x="{x + w / 2:.1f}" y="{B + 29}" text-anchor="middle" fill="#d64545" font-weight="700">실패</text>')
    parts.append(f'<text x="{L}" y="16" fill="#5b6475">목표와의 거리 [mm] (Gazebo 실제 위치, 80 mm 이상은 잘라서 표시)</text>')
    parts.append('</svg>')
    return ''.join(parts)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else 'docs/test_report'
    first, fix, final = load(d, 'results.json'), load(d, 'results_fix.json'), load(d, 'results_final.json')
    ok = [r for r in final if r['success']]
    pa = {name: per_action(rs) for name, rs in (('1차', first), ('수정 후 ⑤', fix), ('최종', final))}
    llm = [r['llm_s'] for r in final if r['llm_s']]
    every = first + fix + final
    n_plan = sum(1 for r in every if r['success'] and r['plan'])
    n_fail = sum(1 for r in every if not r['success'])

    rows = ''.join(
        f"<tr><td>#{r['trial']}</td><td>{e(NAME[r['action']])}</td><td>{e(r['command'])}</td><td>{e(arms(r))}</td>"
        f"<td class='{'ok' if r['success'] else 'ng'}'>{'성공' if r['success'] else '실패'}</td>"
        f"<td>{r['xy_err_mm']:.1f}</td><td>{'' if r['tilt_max_deg'] is None else r['tilt_max_deg']}</td>"
        f"<td>{r['llm_s']}</td><td>{r['duration_s']}</td><td class='small'>{e(cause(r))}</td></tr>"
        for r in final)
    design = ''.join(
        f"<tr><td>{e(n)}</td><td>{e(desc)}</td><td>{'<br>'.join(e(r['command']) for r in final if r['action'] == k)}</td></tr>"
        for k, n, desc in ACTIONS)
    prog = ''.join(
        f"<tr><td>{e(n)}</td>" + ''.join(
            f"<td>{pa[c][k][0]}/{pa[c][k][1]}</td>" if pa[c][k][1] else '<td>–</td>' for c in pa) + '</tr>'
        for k, n, _ in ACTIONS)
    totals = ''.join(f"<td><b>{sum(v[0] for v in pa[c].values())}/{sum(v[1] for v in pa[c].values())}</b></td>" for c in pa)
    pairs = [(r['trial'], NAME[r['action']], r) for r in final]
    gallery = ''.join(
        f"<figure><div class='pair'><img src='{e(r['images'][0])}'><img src='{e(r['images'][1])}'></div>"
        f"<figcaption>#{t} {e(n)} — {e(r['command'])} → "
        f"<b class='{'ok' if r['success'] else 'ng'}'>{'성공' if r['success'] else '실패'}</b> "
        f"({r['xy_err_mm']:.0f} mm)</figcaption></figure>"
        for t, n, r in pairs if r['images'][0] and r['images'][1])

    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>2팔 시험 보고서</title>
<style>
@page {{ size: A4; margin: 14mm 13mm 15mm; }}
body {{ font-family: "Noto Sans CJK KR", sans-serif; color: #1d2433; font-size: 9.6pt; line-height: 1.5; margin: 0; }}
h1 {{ font-size: 20pt; margin: 0 0 4px; }} h2 {{ font-size: 13pt; margin: 18px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #1d2433; page-break-after: avoid; }}
.sub {{ color: #5b6475; }} .small {{ font-size: 8.4pt; }}
.band {{ background: linear-gradient(120deg,#1d2433,#2f4a7a); color: #fff; border-radius: 12px; padding: 18px 22px; margin-bottom: 14px; }}
.band .sub {{ color: #c9d3e6; }}
.kpis {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; margin: 10px 0 6px; }}
.kpi {{ background: #f6f7fa; border: 1px solid #e3e6ec; border-radius: 10px; padding: 10px; }}
.kpi .v {{ font-size: 18pt; font-weight: 700; line-height: 1.15; }} .kpi .l {{ font-size: 8.3pt; color: #5b6475; }}
table {{ border-collapse: collapse; width: 100%; font-size: 8.8pt; margin: 6px 0 10px; page-break-inside: avoid; }}
th, td {{ border-bottom: 1px solid #e3e6ec; padding: 4px 5px; text-align: left; vertical-align: top; }} th {{ background: #f3f5f9; }}
.res td:nth-child(5) {{ white-space: nowrap; }}
.ok {{ color: #1f9d63; font-weight: 700; }} .ng {{ color: #d64545; font-weight: 700; }}
.callout {{ background: #fff8e6; border: 1px solid #f3d995; border-radius: 10px; padding: 9px 12px; margin: 8px 0; }}
.callout.blue {{ background: #eef4ff; border-color: #c9dafc; }}
.gallery {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }}
figure {{ margin: 0; page-break-inside: avoid; }} .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3px; }}
.pair img {{ width: 100%; border-radius: 4px; border: 1px solid #e3e6ec; aspect-ratio: 4 / 3; object-fit: cover; object-position: center 62%; }}
figcaption {{ font-size: 8pt; color: #5b6475; margin-top: 2px; }}
.pb {{ page-break-before: always; }}
</style></head><body>
<div class="band"><div class="sub small">시험 보고서 · 2026-10-16 · Gazebo 시뮬레이션 · ROS_DOMAIN_ID 77</div>
<h1>2팔(left/right) 자연어 Pick &amp; Place 시험</h1>
<div class="sub">OMX-F 2대 · 7.5 cm 보드 위, 바닥 작업면 · 탑뷰 카메라 + ArUco 4개 · Ollama gemma4:e2b · 동작 5가지 × 2회 = 10회</div></div>

<div class="kpis">
<div class="kpi"><div class="v">{len(ok)} / {len(final)}</div><div class="l">최종 시험 성공<br>(실패 2건 모두 카메라 검증이 감지)</div></div>
<div class="kpi"><div class="v">{st.mean(r['xy_err_mm'] for r in ok):.1f} mm</div><div class="l">성공 시 평균 위치 오차<br>(중앙값 {st.median(r['xy_err_mm'] for r in ok):.1f} mm)</div></div>
<div class="kpi"><div class="v">{st.mean(llm):.1f} s</div><div class="l">LLM 명령 해석 평균<br>({min(llm)}–{max(llm)} s)</div></div>
<div class="kpi"><div class="v">{min(r['duration_s'] for r in final):.0f}–{max(r['duration_s'] for r in final):.0f} s</div><div class="l">명령 1개 처리 시간<br>(전달·협동 운반은 약 40–50 s)</div></div>
</div>
<p><b>결론</b>: 다섯 동작 모두 실제로 수행됩니다. 1차 시험에서 협동 운반이 2/2 실패해 원인 2가지를 고쳤고, 수정 후 운반은 4/4(재시험 2 + 최종 2) 성공했습니다.
최종 시험의 실패 2건(#3, #7)은 시뮬 집게에서 블록이 미끄러지거나 튕겨 나간 경우이고, 둘 다 카메라 검증이 잡아 실패로 보고했습니다(거짓 성공 0건).</p>

<h2>1. 시험 설계</h2>
<table><tr><th>동작</th><th>내용</th><th>명령 (2회)</th></tr>{design}</table>
<p class="small sub">매 회차 시작 전에 블록·트레이를 초기 위치로 되돌림(④는 트레이를 작업 영역 밖으로, ⑤-2는 트레이를 뒤쪽 x = 0.10에서 시작).
판정: 플래너 결과(손목 카메라 집기 확인 + 탑뷰 카메라로 목표 30 mm 이내 확인)와 Gazebo 실제 위치. 쌓기는 위 블록 높이 0.0375 m로 확인.</p>

<h2>2. 최종 결과 (10회)</h2>
<table class="res"><colgroup><col style="width:4%"><col style="width:12%"><col style="width:24%"><col style="width:9%"><col style="width:6%"><col style="width:6%"><col style="width:7%"><col style="width:5%"><col style="width:5%"><col style="width:22%"></colgroup>
<tr><th>#</th><th>동작</th><th>명령</th><th>팔</th><th>결과</th><th>오차<br>[mm]</th><th>최대<br>기울기 [°]</th><th>LLM<br>[s]</th><th>전체<br>[s]</th><th>실패 원인</th></tr>{rows}</table>
{error_chart(final)}

<h2 class="pb">3. 시험 경과와 수정</h2>
<table><tr><th>동작</th><th>1차 시험</th><th>수정 후 ⑤ 재시험</th><th>최종 시험</th></tr>{prog}<tr><td><b>합계</b></td>{totals}</tr></table>
<div class="callout"><b>1차 시험의 협동 운반 실패 2건과 수정</b><br>
• #10(트레이가 x = 0.10): 인식 영역이 마커 중심을 이은 사각형(x ≥ 0.10)이라 트레이 절반이 잘려, 폭 0.029 m(실제 0.06)·중심 17.8 mm 오차로 인식 → 손잡이를 잘못 잡음(손목 카메라 19 %).
→ <b>인식 영역을 바깥으로 넓힘</b>(<code>roi_margin 0.12</code>): 같은 위치에서 2.6 mm, 폭 0.059 m. 보드가 블록으로 잘못 잡히지 않음을 확인.<br>
• #9(트레이를 뒤로): 놓은 뒤 물러날 때 반만 열린 집게(0.35 rad)에 손잡이가 걸려 트레이가 들림(높이 0.096 m, 기울기 21.7°).
→ <b>협동 운반에서는 놓을 때 집게를 끝까지 염</b>(<code>carry_release 1.0</code>). 블록 쌓기용 부분 열림은 그대로.</div>
<div class="callout blue"><b>최종 시험의 실패 2건</b><br>
• #3 왼팔 지정 이동: 노란 블록이 목표에서 41 mm 떨어진 빨간 블록 옆에 놓임(놓는 중 미끄러짐).<br>
• #7 팔 간 전달: 오른팔이 이어받아 옮기는 도중 빨간 블록이 마커 영역 밖 (0.425, −0.157)으로 튕겨 나감.<br>
둘 다 시뮬 물리(집게가 블록을 깊게 조이는 접촉)에서 가끔 생기는 현상으로, 같은 명령이 1차 시험에서는 성공했습니다(#3 6.0 mm, #7 18.6 mm).</div>

<h2>4. 시험 전후 화면 (최종 시험, 탑뷰 카메라 + 인식 결과)</h2>
<div class="gallery">{gallery}</div>

<h2>5. 판단과 다음 단계</h2>
<table><tr><th>항목</th><th>판단</th></tr>
<tr><td>명령 해석 (LLM)</td><td>계획이 저장된 성공 {n_plan}건 모두 의도대로 해석(팔 지정·쌓기·전달 분할·트레이 운반 포함). 실패 {n_fail}건도 기록된 팔 배정·단계 수가 의도와 같아, 실패는 해석이 아닌 동작 단계에서 발생. 평균 {st.mean(llm):.1f} s</td></tr>
<tr><td>안전·검증</td><td>실패 {n_fail}건(1차 2, 최종 2) 모두 손목/탑뷰 카메라 검증이 감지. 거짓 성공 없음</td></tr>
<tr><td>위치 정확도</td><td>성공 시 대부분 4–9 mm, 전달·최종 단계는 최대 22 mm(누적)</td></tr>
<tr><td>주요 위험</td><td>시뮬 집게의 미끄러짐/튕김(최종 10회 중 2회). 실물에서는 그리퍼 전류 제한으로 다시 측정 필요</td></tr>
</table>
<p class="small">다음 단계: ① 실패 시 자동 재시도(카메라로 블록을 다시 찾아 1회 재집기) ② 시험 횟수를 늘려(동작당 10회) 통계 확보 ③ 실물 두 팔에서 같은 시험 세트 실행.<br>
재현: <code>python3 docs/tests/run_dual_suite.py docs/test_report all final</code> → <code>python3 docs/tests/make_report.py docs/test_report</code></p>
</body></html>"""
    out = os.path.join(d, 'report.html')
    open(out, 'w').write(page)
    print('written', out)


if __name__ == '__main__':
    main()
