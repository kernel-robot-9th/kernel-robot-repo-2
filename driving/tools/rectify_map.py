# SLAM 맵 보정: 그림의 특정 외벽(기본: 아래, 오른쪽)을 서로 직각인 직선으로 펴고,
# 나머지 외벽(기본: 위, 왼쪽)은 측정 그대로 고정한 채 맵 전체를 thin-plate spline 으로 부드럽게 휜다.
# 출발점(맵 원점)이 보정 후에도 (0,0)에 오도록 yaml origin 을 맞춘다.
# 사용 (tools 폴더): python3 rectify_map.py ../maps/map_rev3.yaml ../maps/map_rev3_rect
#   (diagram_to_map.json 은 입력 맵 기준이어야 함 -> 먼저 align_map.py 실행)
import json
import os
import sys

import cv2
import numpy as np
import yaml
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
STRAIGHTEN = ('bottom', 'right')  # 직선 + 직각으로 만들 그림 외벽
KEEP = ('top', 'left')            # 측정 모양 그대로 고정할 외벽
BIN = 0.10                        # 벽을 따라 제어점 간격 (m)

src_yaml, out_base = sys.argv[1], sys.argv[2]
my = yaml.safe_load(open(src_yaml)); res = my['resolution']; ox, oy = my['origin'][:2]
m = cv2.imread(os.path.join(os.path.dirname(src_yaml), my['image']), cv2.IMREAD_GRAYSCALE)
H, W = m.shape
r, c = np.where(m < 50)
P = np.c_[ox + (c + 0.5) * res, oy + (H - r - 0.5) * res]
M = np.array(json.load(open(os.path.join(HERE, 'diagram_to_map.json')))['affine_cm_to_world_m'])
f = lambda u, v: np.array([u, v, 1.0]) @ M
EDGES = {'bottom': (f(0, 200), f(210, 200)), 'right': (f(210, 0), f(210, 200)),
         'top': (f(0, 0), f(210, 0)), 'left': (f(0, 0), f(0, 200))}


def wall_samples(name):
    """그림 외벽 근처 점유 셀에서 BIN 간격으로 벽 중심선 위치(월드)를 뽑는다."""
    a, b = EDGES[name]
    L = np.linalg.norm(b - a); d = (b - a) / L; n = np.array([-d[1], d[0]])
    t = (P - a) @ d; s = (P - a) @ n
    sel = (np.abs(s) < 0.08) & (t > 0.06) & (t < L - 0.06)
    t, s = t[sel], s[sel]
    out = []
    for t0 in np.arange(0.06, L - 0.06, BIN):
        k = (t >= t0) & (t < t0 + BIN)
        if k.sum() >= 8:
            tm, sm = np.median(t[k]), np.median(s[k])
            out.append(a + tm * d + sm * n)
    return np.array(out), np.c_[t, s], (a, d, n)


samples = {k: wall_samples(k)[0] for k in STRAIGHTEN + KEEP}
raw = {k: wall_samples(k)[1:] for k in STRAIGHTEN}

# 직각인 두 직선 맞추기: 각도 φ 하나로 두 벽 방향을 함께 정하고 각 벽의 위치는 중앙값으로
pts_b, pts_r = samples[STRAIGHTEN[0]], samples[STRAIGHTEN[1]]


def lines(phi):
    d1 = np.array([np.cos(phi), np.sin(phi)]); n1 = np.array([-d1[1], d1[0]])
    return d1, n1, np.median(pts_b @ n1), np.median(pts_r @ d1)


def cost(phi):
    d1, n1, c1, c2 = lines(phi)
    return ((pts_b @ n1 - c1) ** 2).sum() + ((pts_r @ d1 - c2) ** 2).sum()


a, b = EDGES[STRAIGHTEN[0]]
phi0 = np.arctan2(*(b - a)[::-1])
phi = minimize_scalar(cost, bounds=(phi0 - 0.1, phi0 + 0.1), method='bounded').x
d1, n1, c1, c2 = lines(phi)
ideal_b = pts_b - np.outer(pts_b @ n1 - c1, n1)  # 아래 벽 점 -> 직선 위로 (벽 따라 위치는 유지)
ideal_r = pts_r - np.outer(pts_r @ d1 - c2, d1)  # 오른쪽 벽 점 -> 직각 직선 위로
print(f'직각 기준선 방향 {np.degrees(phi):.2f}° / {np.degrees(phi) + 90:.2f}°')
for nm, p0, p1 in ((STRAIGHTEN[0], pts_b, ideal_b), (STRAIGHTEN[1], pts_r, ideal_r)):
    mv = np.linalg.norm(p1 - p0, axis=1) * 100
    print(f'  {nm} 벽: 제어점 {len(p0)}개, 이동 평균 {mv.mean():.1f}cm 최대 {mv.max():.1f}cm')

# 제어점: (보정 후 위치 -> 보정 전 위치) 로 역변환을 만든다
dst = [ideal_b, ideal_r] + [samples[k] for k in KEEP]
srcp = [pts_b, pts_r] + [samples[k] for k in KEEP]
# 맵 바깥 넓은 영역은 그대로 (아레나 밖 레이저 흔적이 크게 휘지 않게)
x0, y0, x1, y1 = ox, oy, ox + W * res, oy + H * res
frame = np.array([[x, y] for x in np.linspace(x0, x1, 5) for y in np.linspace(y0, y1, 5)
                  if x in (x0, x1) or y in (y0, y1)])
dst.append(frame); srcp.append(frame)
DST, SRC = np.vstack(dst), np.vstack(srcp)
inv = RBFInterpolator(DST, SRC - DST, kernel='thin_plate_spline', smoothing=1e-4)

# 출력 격자(입력과 같은 크기/해상도)에서 역매핑 -> 최근접 샘플 (trinary 값 유지)
cc, rr = np.meshgrid(np.arange(W), np.arange(H))
Xo = np.c_[(ox + (cc + 0.5) * res).ravel(), (oy + (H - rr - 0.5) * res).ravel()]
disp = np.vstack([inv(Xo[i:i + 50000]) for i in range(0, len(Xo), 50000)])
Xi = Xo + disp
ci = np.floor((Xi[:, 0] - ox) / res).astype(int); ri = np.floor(H - (Xi[:, 1] - oy) / res).astype(int)
ok = (ci >= 0) & (ci < W) & (ri >= 0) & (ri < H)
out = np.full(H * W, 205, np.uint8)
out[ok] = m[ri[ok], ci[ok]]
out = out.reshape(H, W)

# 출발점(입력 맵 원점)이 보정 후 어디로 갔는지 -> 그만큼 origin 을 옮겨 다시 (0,0) 에 오게
fwd = RBFInterpolator(SRC, DST - SRC, kernel='thin_plate_spline', smoothing=1e-4)
s0 = fwd(np.zeros((1, 2)))[0]
print(f'출발점 이동 {s0[0] * 100:.1f}, {s0[1] * 100:.1f} cm -> origin 보정')
cv2.imwrite(out_base + '.pgm', out)
yaml.safe_dump({'image': os.path.basename(out_base) + '.pgm', 'mode': my.get('mode', 'trinary'),
                'resolution': res, 'origin': [float(ox - s0[0]), float(oy - s0[1]), 0.0],
                'negate': my.get('negate', 0), 'occupied_thresh': my['occupied_thresh'],
                'free_thresh': my['free_thresh']}, open(out_base + '.yaml', 'w'), sort_keys=False)
print('저장:', out_base + '.pgm/.yaml')
