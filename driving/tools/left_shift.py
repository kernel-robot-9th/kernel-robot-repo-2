# 왼쪽 라이다 보정: SLAM 맵에서 왼쪽 1인실 오른쪽 벽(실제 x=30)이 위로 갈수록 오른쪽으로 밀려 보인다.
# 그 벽의 라이다 띠 중심 x(y)를 직선으로 맞추고, 왼쪽 점들을 dx(y) = 30 - x_fit(y) 만큼 x 방향으로 옮긴다.
# - y 40~130 에서 맞춘 직선 사용, 그 밖은 끝값 유지
# - x < 40 은 전부 옮기고, 40~50 은 서서히 0 으로 (가운데 벽 x>=50 은 이미 그림과 일치)
import json
import os

import cv2
import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOM_X, Y_FIT = 30.0, (40.0, 130.0)
FULL_X, ZERO_X = 40.0, 50.0


BOTTOM_WALL_Y = -1.0  # 라이다가 보는 아래 벽면 (y=0 은 바닥 패널 앞면)


def lidar_points():
    """map_rev3_rect 점유 셀 -> 그림 좌표 (cm, x, y 위)
    diagram_to_map.json 은 라이다 아래·위 벽을 y=0·200 에 맞춘 변환이라, 아래 벽을 y=-1(패널 뒤)로 다시 늘린다."""
    y = yaml.safe_load(open(os.path.join(HERE, '../maps/map_rev3_rect.yaml'))); res = y['resolution']; ox, oy = y['origin'][:2]
    m = cv2.imread(os.path.join(HERE, '../maps/map_rev3_rect.pgm'), 0); H, W = m.shape
    M = np.array(json.load(open(os.path.join(HERE, 'diagram_to_map.json')))['affine_cm_to_world_m'])
    r, c = np.where(m < 50)
    X = np.c_[ox + (c + .5) * res, oy + (H - r - .5) * res, np.ones(len(r))]
    u, v = np.linalg.solve(np.vstack([M.T, [0, 0, 1]]), X.T)[:2]
    yl = 200 - v
    return np.c_[u, BOTTOM_WALL_Y + yl * (200 - BOTTOM_WALL_Y) / 200]


def fit():
    P = lidar_points()
    k = (P[:, 0] > 23) & (P[:, 0] < 38) & (P[:, 1] > Y_FIT[0]) & (P[:, 1] < Y_FIT[1]) & ~((P[:, 1] > 78) & (P[:, 1] < 92))
    ys = np.arange(Y_FIT[0], Y_FIT[1], 5.0); xs = []
    for y0 in ys:
        s = k & (np.abs(P[:, 1] - y0 - 2.5) < 2.5)
        xs.append(np.median(P[s, 0]) if s.sum() >= 5 else np.nan)
    ys, xs = ys + 2.5, np.array(xs); ok = ~np.isnan(xs)
    a, b = np.polyfit(ys[ok], xs[ok], 1)  # x = a*y + b
    return a, b


A, B = fit() if not os.path.exists(os.path.join(HERE, 'left_shift.json')) else json.load(open(os.path.join(HERE, 'left_shift.json')))['fit']


def dx(y):
    yc = np.clip(y, *Y_FIT)
    return ROOM_X - (A * yc + B)


def apply(P):
    """그림 좌표 점들(N,2)에 왼쪽 보정 적용"""
    P = np.array(P, float).copy()
    w = np.clip((ZERO_X - P[:, 0]) / (ZERO_X - FULL_X), 0, 1)
    P[:, 0] += w * dx(P[:, 1])
    return P


if __name__ == '__main__':
    a, b = fit()
    json.dump({'fit': [a, b], 'note': '왼쪽 1인실 오른쪽 벽 라이다 x = a*y + b (그림 cm). dx(y) = 30 - (a*y+b), y 40~130 밖은 끝값 유지'},
              open(os.path.join(HERE, 'left_shift.json'), 'w'), indent=1, ensure_ascii=False)
    print(f'라이다 1인실 벽: x = {a:.4f}*y + {b:.2f}  (기울기 {np.degrees(np.arctan(a)):.2f}°)')
    for y0 in (0, 40, 60, 80, 100, 120, 130, 160, 200):
        print(f'  y={y0:3d}: 왼쪽으로 {-dx(y0):.1f}cm 이동')
