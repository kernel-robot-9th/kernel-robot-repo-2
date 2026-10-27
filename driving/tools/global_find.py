# 스캔만으로 map_drawn 전체에서 현재 위치 찾기 (AMCL 과 무관). 결과 = 라이다 중심 좌표(그림 cm)와 방향
# 사용: python3 global_find.py marker_logs/NOW_*.npz
#       (다른 스크립트에서) import global_find as gf; gf.search(gf.lidar_points(ranges, angle, range_lim, laser_tf))
import math
import sys
import warnings

import numpy as np

_argv = sys.argv; sys.argv = [sys.argv[0]]  # scan_fit 은 import 때 sys.argv 의 파일을 처리하므로 비워 둔다
import scan_fit as sf  # noqa: E402
sys.argv = _argv
from scipy.optimize import minimize  # noqa: E402


def lidar_points(ranges, angle, range_lim, laser_tf):
    """여러 장 스캔(ranges: (N, 빔)) 중앙값 → 라이다 중심 기준 점 (x 로봇 앞, m)"""
    a0, a1, inc = angle; lo, hi = range_lim
    with np.errstate(all='ignore'), warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)   # 한 번도 안 맞은 빔(All-NaN)
        R = np.nanmedian(np.where(np.isfinite(ranges), ranges, np.nan), axis=0)
    ang = a0 + np.arange(len(R)) * inc
    ok = np.isfinite(R) & (R > max(lo, 0.068)) & (R < 2.5)   # 0.068 m 안 = 로봇 자기 부품
    lyaw = laser_tf[2]
    return np.c_[R[ok] * np.cos(ang[ok] + lyaw), R[ok] * np.sin(ang[ok] + lyaw)][::2]


def score(L, x, y, th):
    """라이다 중심 (x, y, th) 일 때 벽 3cm 안에 든 점 비율"""
    c, s = math.cos(th), math.sin(th)
    P = np.c_[x + L[:, 0] * c - L[:, 1] * s, y + L[:, 0] * s + L[:, 1] * c]
    return (sf.dmap(P) < 0.03).mean()


def refine(L, x, y, th):
    """(x, y, th) 근처에서 score 최대 자세. 반환 (score, x, y, th)"""
    r = minimize(lambda d: -score(L, d[0], d[1], d[2]), [x, y, th], method='Nelder-Mead',
                 options={'xatol': 1e-3, 'fatol': 1e-4, 'initial_simplex': [[x, y, th], [x + .03, y, th], [x, y + .03, th], [x, y, th + .05]]})
    return (-r.fun, *r.x)


def fit(L, x, y, th, near=0.06):
    """(x, y, th) 근처에서 벽까지 거리 제곱 평균(먼 점은 near 로 자름)이 가장 작은 자세 — cm 단위 확인용 (scan_fit 과 같은 비용).
    반환 (x, y, th, 평균 거리 m)"""
    def cost(d):
        c, s = math.cos(d[2]), math.sin(d[2])
        P = np.c_[d[0] + L[:, 0] * c - L[:, 1] * s, d[1] + L[:, 0] * s + L[:, 1] * c]
        return np.mean(np.minimum(sf.dmap(P), near) ** 2)
    r = minimize(cost, [x, y, th], method='Nelder-Mead',
                 options={'xatol': 2e-4, 'fatol': 1e-8, 'initial_simplex': [[x, y, th], [x + .01, y, th], [x, y + .01, th], [x, y, th + .02]]})
    return (*r.x, math.sqrt(r.fun))


def search(L, top=4):
    """맵 전체 격자 탐색 → 상위 후보 다듬기. 반환 [(score, x, y, th), ...] (라이다 중심, m·rad)"""
    cands = []
    for th in np.radians(np.arange(0, 360, 4)):
        c, s = math.cos(th), math.sin(th)
        Lr = np.c_[L[:, 0] * c - L[:, 1] * s, L[:, 0] * s + L[:, 1] * c]
        for x in np.arange(0.08, 2.03, 0.04):
            for y in np.arange(0.08, 1.93, 0.04):
                if sf.dmap(np.array([[x, y]]))[0] < 0.07:
                    continue
                cands.append(((sf.dmap(Lr + [x, y]) < 0.03).mean(), x, y, th))
    cands.sort(key=lambda t: -t[0])
    res = sorted((refine(L, x, y, th) for _, x, y, th in cands[:40]), key=lambda t: -t[0])
    seen = []
    for sc, x, y, th in res:
        if any(math.hypot(x - a, y - b) < 0.06 and abs((th - c + math.pi) % (2 * math.pi) - math.pi) < 0.2 for _, a, b, c in seen):
            continue
        seen.append((sc, x, y, th))
        if len(seen) == top:
            break
    return seen


if __name__ == '__main__':
    z = np.load(sys.argv[1])
    L = lidar_points(z['ranges'], z['angle'], z['range_lim'], z['laser_tf'])
    for i, (sc, x, y, th) in enumerate(search(L)):
        print(f'{"★" if i == 0 else " "} 라이다 중심 ({x * 100:6.1f}, {y * 100:6.1f}) cm, {math.degrees(th) % 360:5.1f}°  — 벽 3cm 안 점 {sc * 100:4.1f}%')
