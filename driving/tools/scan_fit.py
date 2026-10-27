# 표시점 기록(marker_logs/*.npz)의 스캔을 map_drawn 벽에 직접 맞춰 본다 (AMCL 과 별개)
# - 실제 좌표에 놓았을 때 스캔이 벽에서 얼마나 떨어지나 (벽별 평균, cm)
# - 스캔이 벽에 가장 잘 붙는 자세 = 실제 좌표 + (dx, dy, dyaw)  → 맵이 그 자리에서 어긋난 정도
# 사용: python3 scan_fit.py marker_logs/A_*.npz [...]     (여러 개면 모두)
import json
import math
import os
import sys

import numpy as np
import yaml
from scipy.ndimage import distance_transform_edt
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
NEAR = 0.06  # m, 이 거리 안의 스캔 점만 '벽에 맞은 점'으로 본다

my = yaml.safe_load(open(os.path.join(HERE, '../maps/map_drawn.yaml'))); res = my['resolution']; ox, oy = my['origin'][:2]
import cv2  # noqa: E402
m = cv2.imread(os.path.join(HERE, '../maps/map_drawn.pgm'), 0); H, W = m.shape
dist = distance_transform_edt(m >= 50) * res  # m

walls = yaml.safe_load(open(os.path.join(HERE, 'real_walls.yaml')))
left = np.array(json.load(open(os.path.join(HERE, 'left_wall_measured.json')))['polyline'], float)
SEG = [('outer.left', a / 100, b / 100) for a, b in zip(left, left[1:])]
for g, ws in walls.items():
    if g == 'invisible':
        continue
    for n, w in ws.items():
        p = np.array(w, float).reshape(-1, 2) / 100
        SEG += [(f'{g}.{n}', a, b) for a, b in zip(p, p[1:])]


def dmap(P):
    c = np.clip(((P[:, 0] - ox) / res).astype(int), 0, W - 1)
    r = np.clip((H - (P[:, 1] - oy) / res).astype(int), 0, H - 1)
    return dist[r, c]


def scan_points(z, pose):
    a0, a1, inc = z['angle']; lo, hi = z['range_lim']
    R = np.nanmedian(np.where(np.isfinite(z['ranges']), z['ranges'], np.nan), axis=0)  # 20장 중앙값
    ang = a0 + np.arange(len(R)) * inc
    ok = np.isfinite(R) & (R > max(lo, 0.06)) & (R < 2.5)
    lx, ly, lyaw = z['laser_tf']
    x, y, yaw = pose
    bx, by = R[ok] * np.cos(ang[ok] + lyaw) + lx, R[ok] * np.sin(ang[ok] + lyaw) + ly
    return np.c_[x + bx * math.cos(yaw) - by * math.sin(yaw), y + bx * math.sin(yaw) + by * math.cos(yaw)]


for f in sys.argv[1:]:
    z = np.load(f)
    tx, ty, tyaw = z['truth']
    P0 = scan_points(z, (tx, ty, tyaw))

    def cost(d):
        P = scan_points(z, (tx + d[0], ty + d[1], tyaw + d[2]))
        e = dmap(P)
        return np.mean(np.minimum(e, NEAR) ** 2)  # 먼 점(사람·노이즈)은 영향 제한

    best = min((minimize(cost, x0, method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-9, 'maxiter': 400})
                for x0 in ([0, 0, 0], [0.02, 0, 0], [-0.02, 0, 0], [0, 0.02, 0], [0, -0.02, 0])), key=lambda r: r.fun)
    dx, dy, dyaw = best.x
    e0 = dmap(P0); e1 = dmap(scan_points(z, (tx + dx, ty + dy, tyaw + dyaw)))
    hit0 = e0 < NEAR
    print(f'[{str(z["marker"])}] 스캔 점 {len(P0)}개, 벽에 맞은 점 {hit0.mean() * 100:.0f}%')
    print(f'    실제 자세에서 벽까지 평균 {np.mean(e0[hit0]) * 100:.1f}cm → 최적 자세에서 {np.mean(e1[e1 < NEAR]) * 100:.1f}cm')
    print(f'    스캔이 가장 잘 맞는 자세 = 실제 + dx {dx * 100:+.1f} dy {dy * 100:+.1f} cm, 방향 {math.degrees(dyaw):+.1f}°'
          f'   (AMCL 은 dx {(z["amcl"][0] - tx) * 100:+.1f} dy {(z["amcl"][1] - ty) * 100:+.1f})')
    # 벽별: 실제 자세에서 스캔 점이 벽 선의 어느 쪽으로 얼마나 (부호: 벽의 법선 방향, 아레나 좌표 기준 x 또는 y)
    rows = {}
    for n, a, b in SEG:
        L = np.linalg.norm(b - a); d = (b - a) / L; nv = np.array([-d[1], d[0]])
        t = (P0 - a) @ d; s = (P0 - a) @ nv
        k = (t > 0.01) & (t < L - 0.01) & (np.abs(s) < NEAR)
        if k.sum() >= 5:
            axis = 'x' if abs(d[1]) > abs(d[0]) else 'y'
            off = -np.median(s[k]) if axis == 'x' else np.median(s[k])  # 아레나 축 방향 (+x / +y)
            if axis == 'x' and d[1] < 0:
                off = -off
            if axis == 'y' and d[0] < 0:
                off = -off
            R = rows.setdefault(n, [axis, [], 0]); R[1].append(off); R[2] += int(k.sum())
    for n, (axis, offs, cnt) in rows.items():
        print(f'      {n:28s} 스캔 점 {cnt:3d}개, 벽보다 {axis} 방향 {np.median(offs) * 100:+.1f}cm')
