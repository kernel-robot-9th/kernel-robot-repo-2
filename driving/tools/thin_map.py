# 그림 기준 세선화: 라이다 벽 띠(5~8cm)를 1셀 두께 선으로 바꾼다.
# - 벽의 방향·범위: diagram_walls.yaml (그림 cm)
# - 벽의 위치: 각 벽 주변 띠의 중심선(2cm 구간별 중앙값 → 10cm 이동중앙값으로 매끈하게)
# - 라이다가 실제로 본 구간에만 선을 그림 (4cm 이하 빈틈은 메우고, 그보다 긴 빈틈 = 문/미설치 구간)
# - 아레나 안의 띠 셀은 빈 곳으로, 아레나 밖은 모름(회색)으로. 어느 벽에도 속하지 않는 아레나 안 덩어리는
#   KEEP_BLOB 셀 이상이면 그대로 두고(실제 물체일 수 있음) 작은 점은 지운다.
# 사용 (tools 폴더): python3 thin_map.py ../maps/map_rev3_rect.yaml ../maps/map_rev3_thin
#   (diagram_to_map.json 은 입력 맵 기준이어야 함)
import json
import os
import sys

import cv2
import numpy as np
import yaml
from scipy.ndimage import median_filter

HERE = os.path.dirname(os.path.abspath(__file__))
BAND = 0.07       # 그림 벽에서 이 거리(m) 안의 점유 셀을 그 벽의 띠로 본다
STEP = 0.02       # 벽을 따라 구간 길이 (m)
FILL_GAP = 2      # 이 구간 수 이하의 빈틈은 메움 (2 x 2cm = 4cm)
SMOOTH = 5        # 이동중앙값 창 (구간 수, 5 x 2cm = 10cm)
KEEP_BLOB = 15    # 벽에 속하지 않는 아레나 안 덩어리를 남길 최소 셀 수
MIN_RUN = 3       # 이보다 짧은 토막(구간 수, 3 x 2cm = 6cm)은 그리지 않음
ARENA_MARGIN = 0.06  # 아레나 바깥 판정 여유 (m)

src_yaml, out_base = sys.argv[1], sys.argv[2]
my = yaml.safe_load(open(src_yaml)); res = my['resolution']; ox, oy = my['origin'][:2]
m = cv2.imread(os.path.join(os.path.dirname(src_yaml), my['image']), cv2.IMREAD_GRAYSCALE)
H, W = m.shape
M = np.array(json.load(open(os.path.join(HERE, 'diagram_to_map.json')))['affine_cm_to_world_m'])
walls = yaml.safe_load(open(os.path.join(HERE, 'diagram_walls.yaml')))


def u2w(x, y):  # 그림 좌표(cm, y 위) -> 월드(m)
    return np.array([x, 200 - y, 1.0]) @ M


def w2px(p):  # 월드 -> (col, row) 실수
    return np.array([(p[0] - ox) / res - 0.5, H - (p[1] - oy) / res - 0.5])


occ = m < 50
r, c = np.where(occ)
P = np.c_[ox + (c + 0.5) * res, oy + (H - r - 0.5) * res]
lines_px, report = [], []
SEGS = [(g, tuple(sg)) for g, ss in walls.items() for sg in ss]
# 각 점유 셀을 가장 가까운 벽 하나에만 배정 (모서리에서 두 벽이 같은 셀을 나눠 갖지 않게)
best_d = np.full(len(P), np.inf); owner = np.full(len(P), -1)
geo = []
for si, (g, (x1, y1, x2, y2)) in enumerate(SEGS):
    a, b = u2w(x1, y1), u2w(x2, y2)
    L = np.linalg.norm(b - a); d = (b - a) / L; n = np.array([-d[1], d[0]])
    t = (P - a) @ d; s = (P - a) @ n
    ok = (np.abs(s) < BAND) & (t > -0.03) & (t < L + 0.03)
    dd = np.where(ok, np.abs(s), np.inf)
    if g == 'outer':
        dd = dd - 1.0  # 바깥 벽 우선: 바깥 벽 띠의 셀을 안쪽 벽이 가져가 짧은 토막이 생기지 않게
    win = dd < best_d; best_d[win] = dd[win]; owner[win] = si
    geo.append((a, d, n, L, t, s))
claimed = owner >= 0

for si, (group, (x1, y1, x2, y2)) in enumerate(SEGS):
    if True:
        a, d, n, L, t, s = geo[si]
        sel = owner == si
        nb = int(np.ceil((L + 0.06) / STEP))
        k = np.clip(((t[sel] + 0.03) / STEP).astype(int), 0, nb - 1)
        off = np.full(nb, np.nan)
        for i in range(nb):
            v = s[sel][k == i]
            if len(v) >= 2:
                off[i] = np.median(v)
        have = ~np.isnan(off)
        # 짧은 빈틈 메우기
        idx = np.where(have)[0]
        for i0, i1 in zip(idx, idx[1:]):
            if 1 < i1 - i0 <= FILL_GAP + 1:
                off[i0 + 1:i1] = np.interp(range(i0 + 1, i1), [i0, i1], [off[i0], off[i1]]); have[i0 + 1:i1] = True
        # 연속 구간별로 매끈하게 해서 선 그리기
        runs, i = [], 0
        while i < nb:
            if have[i]:
                j = i
                while j < nb and have[j]:
                    j += 1
                runs.append((i, j)); i = j
            else:
                i += 1
        drawn = 0.0
        for i0, i1 in runs:
            if i1 - i0 < MIN_RUN:
                continue
            o = median_filter(off[i0:i1], size=min(SMOOTH, i1 - i0), mode='nearest')
            tt = -0.03 + (np.arange(i0, i1) + 0.5) * STEP
            tt[0], tt[-1] = -0.03 + i0 * STEP, -0.03 + i1 * STEP
            tt = np.clip(tt, 0.0, L)  # 선 끝은 그림의 벽 범위까지만 (협로 쪽으로 튀어나오지 않게)
            pts = np.array([w2px(a + ti * d + oi * n) for ti, oi in zip(tt, o)])
            lines_px.append(np.round(pts).astype(np.int32))
            drawn += tt[-1] - tt[0]
        meas = np.nanmedian(off) * 100 if have.any() else float('nan')
        report.append((group, (x1, y1, x2, y2), L, drawn, meas))

# 아레나 영역 (그림 사각형 + 여유)
arena = np.array([w2px(p) for p in (u2w(0, 0), u2w(210, 0), u2w(210, 200), u2w(0, 200))])
cen = arena.mean(0)
arena_big = cen + (arena - cen) * (1 + ARENA_MARGIN / (np.linalg.norm(arena - cen, axis=1).mean() * res))
inside = np.zeros((H, W), np.uint8)
cv2.fillPoly(inside, [np.round(arena_big).astype(np.int32)], 1)
inside = inside.astype(bool)

out = m.copy()
out[~inside] = 205                         # 아레나 밖 = 모름
band_px = np.zeros((H, W), bool); band_px[r[claimed], c[claimed]] = True
out[inside & band_px] = 254                # 벽 띠 = 빈 곳 (선으로 다시 그림)
# 벽에 속하지 않는 아레나 안 점유 덩어리: 작으면 지움
left = (out < 50) & inside
nlab, lab, stats, _ = cv2.connectedComponentsWithStats(left.astype(np.uint8), connectivity=8)
kept_blobs = []
for i in range(1, nlab):
    if stats[i, cv2.CC_STAT_AREA] < KEEP_BLOB:
        out[lab == i] = 254
    else:
        kept_blobs.append((stats[i, cv2.CC_STAT_AREA], stats[i, :4]))
for pts in lines_px:
    cv2.polylines(out, [pts], False, 0, 1, lineType=cv2.LINE_8)

cv2.imwrite(out_base + '.pgm', out)
yaml.safe_dump({'image': os.path.basename(out_base) + '.pgm', 'mode': my.get('mode', 'trinary'),
                'resolution': res, 'origin': [float(ox), float(oy), 0.0], 'negate': my.get('negate', 0),
                'occupied_thresh': my['occupied_thresh'], 'free_thresh': my['free_thresh']},
               open(out_base + '.yaml', 'w'), sort_keys=False)

print(f'{"벽":32s} {"길이":>6s} {"그린 길이":>8s} {"그림 대비 위치":>12s}')
for g, seg, L, drawn, meas in report:
    print(f'{g:15s} {str(seg):17s} {L * 100:5.0f}cm {drawn * 100:6.0f}cm   ' +
          ('  (데이터 없음)' if np.isnan(meas) else f'{meas:+6.1f}cm'))
print(f'벽에 속하지 않고 남긴 덩어리 {len(kept_blobs)}개:',
      ', '.join(f'{a}셀@px({s[0]},{s[1]})' for a, s in kept_blobs) or '없음')
print('저장:', out_base + '.pgm/.yaml')
