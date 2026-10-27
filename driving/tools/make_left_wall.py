# 왼쪽 외벽 모양: 라이다 띠 중심(map_rev3_rect)에 왼쪽 보정(left_shift.py)을 적용해 left_wall_measured.json 저장
import json
import os

import numpy as np
from scipy.ndimage import median_filter

import left_shift

HERE = os.path.dirname(os.path.abspath(__file__))
P = left_shift.apply(left_shift.lidar_points())
k = (P[:, 0] > -12) & (P[:, 0] < 6)
pts = []
for y0 in range(15, 186, 5):  # 양 끝 15cm 는 위/아래 벽 셀이 섞여서 제외
    s = k & (np.abs(P[:, 1] - y0) < 3)
    if s.sum() >= 5:
        pts.append((float(np.median(P[s, 0])), float(y0)))
xs = median_filter(np.array([p[0] for p in pts]), 3, mode='nearest')
poly = [[round(float(x), 1), y] for x, (_, y) in zip(xs, pts)]
poly = [[poly[0][0], 0.0]] + poly + [[poly[-1][0], 200.0]]
json.dump({'note': '왼쪽 외벽: map_rev3_rect 라이다 띠 중심 + 왼쪽 보정(left_shift.json). 그림 좌표 cm [x, y], 5cm 간격, '
                   '3점 중앙값, 양 끝 15cm 는 가장 가까운 값으로 연장.', 'polyline': poly},
          open(os.path.join(HERE, 'left_wall_measured.json'), 'w'), ensure_ascii=False, indent=1)
print('왼쪽 외벽 x (y=0..200, 20cm 간격):', ' '.join(f'{np.interp(y, [p[1] for p in poly], [p[0] for p in poly]):+.1f}' for y in range(0, 201, 20)))
