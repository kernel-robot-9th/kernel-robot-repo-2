# 직접 그린 맵(real_walls.yaml)과 SLAM 맵(map_rev3_rect) 비교
# - 벽마다: 라이다 띠 중심이 그린 선에서 얼마나 떨어졌나(cm), 라이다가 그 벽을 본 비율(%)
# - 그린 벽 근처에 없는 라이다 점 덩어리(그리지 않은 물체/벽 후보). 약제실 개방부 밖 노이즈는 제외
# - 라이다 점에는 왼쪽 보정(left_shift.py)을 먼저 적용
# - 확인 그림 drawn_compare.png (그림 방향 그대로)
# 사용 (tools 폴더): python3 compare_drawn.py
import json
import os

import cv2
import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BAND = 7.0  # cm

# SLAM 점유 셀 -> 그림 좌표 (cm, y 위)
import left_shift  # noqa: E402
P = left_shift.apply(left_shift.lidar_points())  # 아래 벽 y=-1 보정 + 왼쪽 라이다 보정 적용 후 비교
NOISE = (P[:, 0] > 60) & (P[:, 0] < 130) & (P[:, 1] > 190)  # 약제실 개방부 밖 OMX 팔·카메라 스탠드 노이즈

walls = yaml.safe_load(open(os.path.join(HERE, 'real_walls.yaml')))
left = np.array(json.load(open(os.path.join(HERE, 'left_wall_measured.json')))['polyline'], float)
SEG = []  # (이름, 시작, 끝)
for i, (a, b) in enumerate(zip(left, left[1:])):
    SEG.append(('outer.left', a, b))
for g, ws in walls.items():
    if g == 'invisible':
        continue
    for n, w in ws.items():
        p = np.array(w, float).reshape(-1, 2)
        for a, b in zip(p, p[1:]):
            SEG.append((f'{g}.{n}', a, b))

best = np.full(len(P), np.inf); owner = np.full(len(P), -1); sgn = np.zeros(len(P))
for i, (n, a, b) in enumerate(SEG):
    L = np.linalg.norm(b - a); d = (b - a) / L; nv = np.array([-d[1], d[0]])
    t = (P - a) @ d; s = (P - a) @ nv
    dd = np.where((t > -2) & (t < L + 2) & (np.abs(s) < BAND), np.abs(s), np.inf)
    if n.startswith('outer'):
        dd = dd - 100  # 바깥 벽 우선
    w = dd < best; best[w] = dd[w]; owner[w] = i; sgn[w] = s[w]

rows = {}
for i, (n, a, b) in enumerate(SEG):
    L = np.linalg.norm(b - a); d = (b - a) / L
    k = owner == i
    t = (P[k] - a) @ d
    cov = len(np.unique(np.clip(t, 0, L - 1e-6).astype(int))) / max(1, int(np.ceil(L))) if k.any() else 0
    R = rows.setdefault(n, [0.0, 0.0, []])
    R[0] += L; R[1] += cov * L; R[2] += list(sgn[k])
print(f'{"벽":30s} {"길이":>6s} {"라이다가 본 비율":>14s} {"띠 중심 - 그린 선":>16s}')
for n, (L, seen, ss) in rows.items():
    off = f'{np.median(ss):+5.1f}cm' if len(ss) else '   -  '
    flag = '  ← 확인' if (len(ss) and abs(np.median(ss)) > 2.5) or seen / L < 0.5 else ''
    print(f'{n:30s} {L:5.0f}cm {seen / L * 100:12.0f}%     {off}{flag}')

inside = (P[:, 0] > 3) & (P[:, 0] < 207) & (P[:, 1] > 3) & (P[:, 1] < 197)
stray = inside & (owner < 0) & ~NOISE
print(f'\n그린 벽 근처에 없는 아레나 안 라이다 셀: {stray.sum()}개')
if stray.any():
    S = P[stray]
    grid = np.zeros((210, 220), np.uint8)
    gi = np.clip(S.astype(int), 0, [219, 209])
    grid[gi[:, 1], gi[:, 0]] = 1
    n, lab, st, cen = cv2.connectedComponentsWithStats(cv2.dilate(grid, np.ones((3, 3), np.uint8)), connectivity=8)
    big = sorted([(st[i, 4], cen[i]) for i in range(1, n)], key=lambda z: -z[0])[:8]
    print('  큰 덩어리(셀 수 @ 그림 좌표):', ', '.join(f'{a}@({c[0]:.0f},{c[1]:.0f})' for a, c in big))

# 확인 그림: 3px/cm, 그림 방향
S3 = 3; Wc, Hc = 230 * S3, 220 * S3
g = cv2.imread(os.path.join(HERE, 'layout_diagram.png'))
k = json.load(open(os.path.join(HERE, 'diagram_to_map.json')))['diagram_px_to_cm']
A = np.array([[S3 / k['px_per_cm'], 0, (-k['x0'] / k['px_per_cm'] + 10) * S3],
              [0, S3 / k['px_per_cm'], (-k['y0'] / k['px_per_cm'] + 10) * S3]])
img = cv2.warpAffine(g, A, (Wc, Hc), borderValue=(255, 255, 255))
img = cv2.addWeighted(img, 0.4, np.full_like(img, 255), 0.6, 0)
q = np.round(np.c_[(P[:, 0] + 10) * S3, (210 - P[:, 1]) * S3]).astype(int)
ok = (q[:, 0] >= 0) & (q[:, 0] < Wc) & (q[:, 1] >= 0) & (q[:, 1] < Hc)
for (x, yy), st in zip(q[ok], stray[ok]):
    cv2.rectangle(img, (x - 1, yy - 1), (x + 1, yy + 1), (0, 140, 255) if st else (150, 150, 255), -1)
for n, a, b in SEG:
    pa = (int((a[0] + 10) * S3), int((210 - a[1]) * S3)); pb = (int((b[0] + 10) * S3), int((210 - b[1]) * S3))
    cv2.line(img, pa, pb, (0, 0, 0), 2)
cv2.putText(img, 'black: drawn walls   pink: lidar (SLAM)   orange: lidar not near any drawn wall',
            (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
cv2.imwrite(os.path.join(HERE, 'drawn_compare.png'), img)
print('saved drawn_compare.png')
