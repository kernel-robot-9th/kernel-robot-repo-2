# 그림 좌표(아레나 왼쪽 아래 = (0,0), x 오른쪽, y 위쪽, cm) <-> 맵 좌표(m)
# 기본 맵 = map_drawn (맵 좌표 = 그림 좌표 / 100). SLAM 맵(map_rev3_rect/thin)용은  COORDS_MAP=rect python3 coords.py ...
# 사용: python3 coords.py 105 180 90     -> 맵 좌표 x, y, yaw(rad, deg)
#       heading: 사용자 좌표 기준 로봇 정면 각도(0 = +x, 90 = +y)
import json
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_T = json.load(open(os.path.join(_HERE, 'diagram_to_map.json') if os.environ.get('COORDS_MAP') == 'rect'
                    else os.path.join(_HERE, '..', 'maps', 'map_drawn_diagram_to_map.json')))
_M = np.array(_T['affine_cm_to_world_m'])  # [u, v, 1] @ M = world, v = 200 - y


def user_to_map(x_cm, y_cm, heading_deg=None):
    p = np.array([x_cm, 200 - y_cm, 1.0]) @ _M
    if heading_deg is None:
        return float(p[0]), float(p[1])
    h = math.radians(heading_deg)
    q = np.array([x_cm + 10 * math.cos(h), 200 - (y_cm + 10 * math.sin(h)), 1.0]) @ _M
    return float(p[0]), float(p[1]), math.atan2(q[1] - p[1], q[0] - p[0])


def map_to_user(x_m, y_m):
    A = np.vstack([_M.T, [0, 0, 1]])
    u, v, _ = np.linalg.solve(A, [x_m, y_m, 1.0])
    return float(u), float(200 - v)


if __name__ == '__main__':
    x, y = float(sys.argv[1]), float(sys.argv[2])
    if len(sys.argv) > 3:
        mx, my, yaw = user_to_map(x, y, float(sys.argv[3]))
        print(f'map x={mx:.3f} y={my:.3f} yaw={yaw:.3f} rad ({math.degrees(yaw):.1f} deg)')
    else:
        mx, my = user_to_map(x, y)
        print(f'map x={mx:.3f} y={my:.3f}')
