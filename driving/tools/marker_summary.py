# 표시점 기록 전체 요약
# 1) 표시점별: AMCL 오차, 스캔 최적 자세와의 차이 (월드 / 로봇 기준 앞·왼쪽)
# 2) 벽별: 각 표시점의 '스캔 최적 자세'에서 스캔이 벽 선에서 떨어진 값 → 놓은 위치 오차를 뺀 맵 오차 추정
# 사용: python3 marker_summary.py   (marker_logs 의 표시점별 최신 기록 사용)
import glob
import math
import os
import sys

import numpy as np

sys.argv = [sys.argv[0]]
import scan_fit as sf  # noqa: E402  (맵·벽·함수 재사용; 인자 없이 import 하면 출력 없음)
from scipy.optimize import minimize  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
files = {}
for f in sorted(glob.glob(os.path.join(HERE, 'marker_logs', '*.npz'))):
    files[os.path.basename(f).split('_')[0]] = f  # 표시점별 최신
wall_obs = {}
print(f'{"표시점":6s}{"실제 (cm, °)":>22s}{"AMCL 차이":>22s}{"스캔 최적 차이":>24s}{"로봇기준 앞/왼":>18s}')
for name, f in files.items():
    z = np.load(f); tx, ty, tyaw = z['truth']

    def cost(d):
        return np.mean(np.minimum(sf.dmap(sf.scan_points(z, (tx + d[0], ty + d[1], tyaw + d[2]))), sf.NEAR) ** 2)
    best = min((minimize(cost, x0, method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-9, 'maxiter': 400})
                for x0 in ([0, 0, 0], [0.02, 0, 0], [-0.02, 0, 0], [0, 0.02, 0], [0, -0.02, 0])), key=lambda r: r.fun)
    dx, dy, dth = best.x
    fwd = dx * math.cos(tyaw) + dy * math.sin(tyaw); lft = -dx * math.sin(tyaw) + dy * math.cos(tyaw)
    ax, ay, ath = z['amcl'] - z['truth']
    print(f'{name:6s}({tx * 100:6.1f},{ty * 100:6.1f},{math.degrees(tyaw) % 360:4.0f})'
          f'   {ax * 100:+5.1f},{ay * 100:+5.1f},{math.degrees(ath):+5.1f}°'
          f'   {dx * 100:+5.1f},{dy * 100:+5.1f},{math.degrees(dth):+5.1f}°   {fwd * 100:+5.1f} / {lft * 100:+5.1f}')
    P = sf.scan_points(z, (tx + dx, ty + dy, tyaw + dth))
    for n, a, b in sf.SEG:
        L = np.linalg.norm(b - a); d = (b - a) / L; nv = np.array([-d[1], d[0]])
        t = (P - a) @ d; s = (P - a) @ nv
        k = (t > 0.01) & (t < L - 0.01) & (np.abs(s) < sf.NEAR)
        if k.sum() >= 8:
            axis = 'x' if abs(d[1]) > abs(d[0]) else 'y'
            off = -np.median(s[k]) if axis == 'x' else np.median(s[k])
            if (axis == 'x' and d[1] < 0) or (axis == 'y' and d[0] < 0):
                off = -off
            wall_obs.setdefault(n, (axis, []))[1].append((name, off * 100, int(k.sum())))
print('\n벽별 (각 표시점의 스캔 최적 자세 기준, 스캔 점이 그린 선보다 +x/+y 쪽으로 몇 cm)')
for n, (axis, obs) in sorted(wall_obs.items()):
    w = np.array([o[2] for o in obs], float); v = np.array([o[1] for o in obs])
    mean = (w * v).sum() / w.sum()
    print(f'  {n:28s} {axis}  가중평균 {mean:+5.1f}cm   ' + ', '.join(f'{o[0]}:{o[1]:+.1f}({o[2]})' for o in obs))
