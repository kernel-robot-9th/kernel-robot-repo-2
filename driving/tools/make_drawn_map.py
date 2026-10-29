# 실측 벽 목록(real_walls.yaml)으로 맵을 직접 만든다. 맵 좌표 = 그림 좌표 / 100 (m)
#   map x = 그림 x / 100, map y = 그림 y / 100  (왼쪽 아래 = (0,0), 회전 없음)
# 사용 (tools 폴더): python3 make_drawn_map.py ../maps/map_drawn
import json
import os
import sys

import cv2
import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
RES = 0.01                 # m/px
MARGIN = 10.0              # cm, 아레나 둘레 여백
X0, Y0 = -MARGIN, -MARGIN  # 맵 왼쪽 아래 (cm)
WCM, HCM = 210 + 2 * MARGIN, 200 + 2 * MARGIN
W, H = int(round(WCM / (RES * 100))), int(round(HCM / (RES * 100)))

out_base = sys.argv[1]
walls = yaml.safe_load(open(os.path.join(HERE, 'real_walls.yaml')))
left = np.array(json.load(open(os.path.join(HERE, 'left_wall_measured.json')))['polyline'], float)
left = left[np.argsort(left[:, 1])]


def px(pts):  # 그림 cm -> 픽셀 (col, row)
    p = np.asarray(pts, float).reshape(-1, 2)
    return np.round(np.c_[(p[:, 0] - X0) / (RES * 100) - 0.5, H - (p[:, 1] - Y0) / (RES * 100) - 0.5]).astype(np.int32)


def left_x(y):  # 왼쪽 외벽의 x (라이다 실측)
    return float(np.interp(y, left[:, 1], left[:, 0]))


# 바깥 벽 끝을 실측 왼쪽 외벽에 맞춤 (왼쪽 외벽 밖으로 튀어나오지 않게)
invisible = walls.pop('invisible', {})  # 라이다에 안 보이는 장애물은 AMCL 맵에 그리지 않음
YB = walls['outer']['bottom'][1]      # 라이다가 보는 아래 벽면 y
walls['outer']['bottom'][0] = left_x(YB)
walls['outer']['top_left'][0] = left_x(200)

img = np.full((H, W), 205, np.uint8)                       # 모름
arena = np.vstack([[left_x(YB), YB], [210, YB], [210, 200], [left_x(200), 200], left[::-1]])
cv2.fillPoly(img, [px(arena)], 254)                        # 아레나 안 = 빈 곳
segs = [np.vstack([[left_x(YB), YB], left])]
for group in walls.values():
    for w in group.values():
        segs.append(np.array(w, float).reshape(-1, 2))
for s in segs:
    cv2.polylines(img, [px(s)], False, 0, 1, lineType=cv2.LINE_8)  # 벽 = 1셀(1cm)

cv2.imwrite(out_base + '.pgm', img)
yaml.safe_dump({'image': os.path.basename(out_base) + '.pgm', 'mode': 'trinary', 'resolution': RES,
                'origin': [X0 / 100, Y0 / 100, 0.0], 'negate': 0,
                'occupied_thresh': 0.65, 'free_thresh': 0.196},
               open(out_base + '.yaml', 'w'), sort_keys=False)
# 이 맵용 좌표 변환 (coords.py 형식): world = [u, v, 1] @ M, v = 200 - y
M = [[RES, 0.0], [0.0, -RES], [0.0, 200 * RES]]
json.dump({'map': os.path.basename(out_base) + '.yaml', 'affine_cm_to_world_m': M,
           'note': '직접 그린 맵: map 좌표(m) = 그림 좌표(cm) / 100, 왼쪽 아래 원점'},
          open(out_base + '_diagram_to_map.json', 'w'), indent=2, ensure_ascii=False)
print(f'저장: {out_base}.pgm ({W}x{H}, {RES} m/px, origin [{X0 / 100}, {Y0 / 100}]), 벽 {len(segs)}개')
