# 그림(layout_diagram.png, cm) <-> SLAM 맵(m) 좌표 맞추기
# 1) 맵에서 아레나 외벽 4개를 찾아 직선 피팅 -> 모서리 4개
# 2) 그림 210x200 사각형 모서리와 대응 (0/90/180/270° 중 내부 벽이 가장 잘 겹치는 방향)
# 3) diagram_to_map.json(아핀 변환), arena_corners.npy, align_overlay.png 저장
# 사용 (tools 폴더에서): python3 align_map.py ../maps/map_rev3.yaml
import json
import os
import sys

import cv2
import numpy as np
import yaml
from scipy.ndimage import binary_erosion, distance_transform_edt

HERE = os.path.dirname(os.path.abspath(__file__))
DIAGRAM = os.path.join(HERE, 'layout_diagram.png')
DX0, DY0, DS = 76.0, 40.0, 33.9 / 10.0  # 그림 축 보정: 원점 픽셀, px/cm
ARENA_W, ARENA_H = 210.0, 200.0

map_yaml = sys.argv[1]
my = yaml.safe_load(open(map_yaml))
res = my['resolution']; ox, oy = my['origin'][:2]
m = cv2.imread(os.path.join(os.path.dirname(map_yaml), my['image']), cv2.IMREAD_GRAYSCALE)
H, W = m.shape
r, c = np.where(m < 50)
P = np.c_[ox + (c + 0.5) * res, oy + (H - r - 0.5) * res]  # 점유 셀 월드 좌표


def rot(th):
    return np.array([[np.cos(th), np.sin(th)], [-np.sin(th), np.cos(th)]])  # world -> aligned


# 1-a) 벽이 축에 가장 잘 정렬되는 회전각
best = None
for deg in np.arange(-45, 45, 0.1):
    Q = P @ rot(np.radians(deg)).T
    s = sum((np.sort(np.bincount(((Q[:, k] - Q[:, k].min()) / 0.01).astype(int)))[-4:] ** 2).sum() for k in (0, 1))
    if best is None or s > best[0]:
        best = (s, deg)
th = np.radians(best[1])
Q = P @ rot(th).T

# 1-b) 각 축에서 강한 피크 중 바깥쪽 두 개 = 외벽 (간격이 아레나 크기와 비슷한 쌍)
walls = {}
for k, size in ((0, None), (1, None)):
    b = np.round(Q[:, k] / 0.01).astype(int)
    u, cnt = np.unique(b, return_counts=True)
    sm = np.convolve(cnt, np.ones(5), 'same')
    strong = u[sm > 0.35 * sm.max()] * 0.01
    walls[k] = (strong.min(), strong.max())
span = (walls[0][1] - walls[0][0], walls[1][1] - walls[1][0])
print(f'회전 {best[1]:.1f}°, 외벽 간격 {span[0]:.3f} x {span[1]:.3f} m')

# 1-c) 외벽 직선 피팅 (총최소제곱 + 이상치 제거)
lines = {}
for name, k, v in (('xmin', 0, walls[0][0]), ('xmax', 0, walls[0][1]), ('ymin', 1, walls[1][0]), ('ymax', 1, walls[1][1])):
    o = 1 - k
    lo, hi = walls[o][0] + 0.05, walls[o][1] - 0.05  # 모서리 근처 제외
    sel = (np.abs(Q[:, k] - v) < 0.06) & (Q[:, o] > lo) & (Q[:, o] < hi)
    pts = P[sel]
    for _ in range(4):
        mu = pts.mean(0); n = np.linalg.svd(pts - mu)[2][1]
        d = (pts - mu) @ n
        pts = pts[np.abs(d) < 2.5 * max(d.std(), 0.005)]
    mu = pts.mean(0); vt = np.linalg.svd(pts - mu)[2]; n = vt[1]
    lines[name] = (n, n @ mu)
    print(f'  {name}: 점 {len(pts)}개, 흩어짐 {((pts - mu) @ n).std() * 100:.1f}cm, 방향 {np.degrees(np.arctan2(vt[0][1], vt[0][0])):.2f}°')


def inter(a, b):
    return np.linalg.solve(np.array([lines[a][0], lines[b][0]]), [lines[a][1], lines[b][1]])


# 월드 기준 TL, TR, BR, BL (정렬 좌표에서 y 큰 쪽이 위)
C = np.array([inter('ymax', 'xmin'), inter('ymax', 'xmax'), inter('ymin', 'xmax'), inter('ymin', 'xmin')])
for nm, p in zip(('TL', 'TR', 'BR', 'BL'), C):
    print(f'  {nm} ({p[0]:.3f}, {p[1]:.3f})')

# 2) 그림 모서리 (u 오른쪽, v 아래): TL, TR, BR, BL
D = np.array([[0, 0], [ARENA_W, 0], [ARENA_W, ARENA_H], [0, ARENA_H]])
g = cv2.imread(DIAGRAM, cv2.IMREAD_GRAYSCALE).astype(int)
dark = g < 110
py, px = np.where(dark & ~binary_erosion(dark))
uu, vv = (px - DX0) / DS, (py - DY0) / DS
inner = (uu > 5) & (uu < ARENA_W - 5) & (vv > 5) & (vv < ARENA_H - 5)
UV = np.c_[uu[inner], vv[inner], np.ones(inner.sum())]
dist = distance_transform_edt(m >= 50) * res
results = []
for k in range(4):
    dst = np.roll(C, -k, axis=0)
    M = np.linalg.lstsq(np.c_[D, np.ones(4)], dst, rcond=None)[0]
    resid = np.linalg.norm(np.c_[D, np.ones(4)] @ M - dst, axis=1).max()
    w = UV @ M
    rr = (H - (w[:, 1] - oy) / res).astype(int); cc = ((w[:, 0] - ox) / res).astype(int)
    ok = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
    hit = (dist[rr[ok], cc[ok]] < 0.04).mean()
    results.append((hit, k, M, resid))
    print(f'  그림 회전 {90 * k:3d}°: 모서리 오차 {resid * 100:.1f}cm, 내부 벽 일치 {hit * 100:.1f}%')
hit, k, M, resid = max(results, key=lambda z: z[0])
print(f'선택: {90 * k}° (일치 {hit * 100:.1f}%)')

json.dump({'map': os.path.basename(map_yaml), 'diagram': 'layout_diagram.png',
           'diagram_px_to_cm': {'x0': DX0, 'y0': DY0, 'px_per_cm': DS},
           'rotation_deg_index': 90 * k, 'corner_residual_m': float(resid),
           'affine_cm_to_world_m': M.tolist(),
           'note': 'world = [u, v, 1] @ M  (u: 그림 가로 cm, v: 그림 세로 cm 아래로 증가 = 200 - y)'},
          open(os.path.join(HERE, 'diagram_to_map.json'), 'w'), indent=2, ensure_ascii=False)
np.save(os.path.join(HERE, 'arena_corners.npy'), C)

# 3) 확인 그림: 그림을 맵 위에 겹치고, 그림과 같은 방향으로 돌려 저장
S = 2 if res <= 0.01 else 4  # 약 0.5cm/px 로 확대
A1 = np.array([[1 / DS, 0, -DX0 / DS], [0, 1 / DS, -DY0 / DS], [0, 0, 1]])
A2 = np.vstack([M.T, [0, 0, 1]])
A3 = np.array([[S / res, 0, -ox * S / res], [0, -S / res, (H + oy / res) * S], [0, 0, 1]])
warp = cv2.warpAffine(cv2.imread(DIAGRAM), (A3 @ A2 @ A1)[:2], (W * S, H * S), borderValue=(255, 255, 255))
base = cv2.cvtColor(cv2.resize(m, (W * S, H * S), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
out = cv2.addWeighted(warp, 0.55, base, 0.45, 0)
out[cv2.resize((m < 50).astype(np.uint8), (W * S, H * S), interpolation=cv2.INTER_NEAREST) > 0] = (0, 0, 220)
p0 = (A3 @ [0, 0, 1])[:2].astype(int)
cv2.circle(out, tuple(p0), 6, (255, 0, 255), -1)  # 맵 원점(SLAM 출발점)
cp = (np.c_[C, np.ones(4)] @ A3.T)[:, :2]
x0, y0 = (cp.min(0) - 30).astype(int).clip(0); x1, y1 = (cp.max(0) + 30).astype(int)
crop = out[y0:y1, x0:x1]
# 그림과 같은 방향으로 보기: 그림의 위쪽(-v) 방향이 화면 위(월드 +y)로 오게 90° 단위 회전
up = -M[1]
ang = np.degrees(np.arctan2(up[1], up[0]))
for _ in range(int(round((90 - ang) / 90)) % 4):
    crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
cv2.imwrite(os.path.join(HERE, 'align_overlay.png'), crop)

# 맵 원점(SLAM 출발점)의 그림 좌표
u0, v0, _ = np.linalg.solve(np.vstack([M.T, [0, 0, 1]]), [0, 0, 1])
print(f'맵 원점(출발점) = 그림 좌표 x={u0:.1f}, y={200 - v0:.1f} cm')
