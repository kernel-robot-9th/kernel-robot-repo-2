# 세선화 확인 그림: 그림(흐리게) + 원래 라이다 띠(연한 빨강) + 세선화 선(검정), 그림과 같은 방향
# 사용: python3 thin_overlay.py ../maps/map_rev3_rect.yaml ../maps/map_rev3_thin.yaml thin_overlay.png
import json
import os
import sys

import cv2
import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
src_yaml, thin_yaml, out_png = sys.argv[1:4]


def load(p):
    y = yaml.safe_load(open(p))
    return cv2.imread(os.path.join(os.path.dirname(p), y['image']), cv2.IMREAD_GRAYSCALE), y['resolution'], y['origin'][:2]


a, res, (ox, oy) = load(src_yaml)
b, _, _ = load(thin_yaml)
H, W = a.shape
T = json.load(open(os.path.join(HERE, 'diagram_to_map.json')))
M = np.array(T['affine_cm_to_world_m']); k = T['diagram_px_to_cm']
S = 3  # 출력 확대 (1cm 맵이면 3px/cm)
A1 = np.array([[1 / k['px_per_cm'], 0, -k['x0'] / k['px_per_cm']], [0, 1 / k['px_per_cm'], -k['y0'] / k['px_per_cm']], [0, 0, 1]])
A2 = np.vstack([M.T, [0, 0, 1]])
A3 = np.array([[S / res, 0, -ox * S / res], [0, -S / res, (H + oy / res) * S], [0, 0, 1]])
diag = cv2.warpAffine(cv2.imread(os.path.join(HERE, 'layout_diagram.png')), (A3 @ A2 @ A1)[:2], (W * S, H * S),
                      borderValue=(255, 255, 255))
out = cv2.addWeighted(diag, 0.45, np.full_like(diag, 255), 0.55, 0)
up = lambda g: cv2.resize(g, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
out[up(a) < 50] = (150, 150, 255)   # 원래 띠: 연한 빨강
out[up(b) < 50] = (0, 0, 0)         # 세선화 선: 검정
C = np.array([np.array([u, v, 1.0]) @ M for u, v in ((0, 0), (210, 0), (210, 200), (0, 200))])
cp = (np.c_[C, np.ones(4)] @ A3.T)[:, :2]
x0, y0 = (cp.min(0) - 25).astype(int).clip(0); x1, y1 = (cp.max(0) + 25).astype(int)
crop = out[y0:y1, x0:x1]
upv = -M[1]; ang = np.degrees(np.arctan2(upv[1], upv[0]))
for _ in range(int(round((90 - ang) / 90)) % 4):
    crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
cv2.imwrite(out_png, crop)
print('saved', out_png, crop.shape)
