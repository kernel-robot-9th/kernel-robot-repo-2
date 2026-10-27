# 외벽 4개의 곧음/각도 점검: 각 벽 점유 셀에 직선을 맞추고 20cm 구간별 벽 위치(직선 기준, cm)를 출력
# 사용: python3 check_walls.py ../maps/<맵>.yaml   (diagram_to_map.json 은 같은 맵 기준)
import json, os, sys
import cv2, numpy as np, yaml
HERE = os.path.dirname(os.path.abspath(__file__))
my = yaml.safe_load(open(sys.argv[1])); res = my['resolution']; ox, oy = my['origin'][:2]
m = cv2.imread(os.path.join(os.path.dirname(sys.argv[1]), my['image']), 0); H, W = m.shape
r, c = np.where(m < 50); P = np.c_[ox + (c + .5) * res, oy + (H - r - .5) * res]
M = np.array(json.load(open(os.path.join(HERE, 'diagram_to_map.json')))['affine_cm_to_world_m'])
f = lambda u, v: np.array([u, v, 1.]) @ M
dirs = {}
for name, a, b in (('아래', f(0, 200), f(210, 200)), ('오른쪽', f(210, 0), f(210, 200)),
                   ('왼쪽', f(0, 0), f(0, 200)), ('위', f(0, 0), f(210, 0))):
    L = np.linalg.norm(b - a); d = (b - a) / L; n = np.array([-d[1], d[0]])
    t = (P - a) @ d; s = (P - a) @ n
    sel = (np.abs(s) < 0.08) & (t > 0.06) & (t < L - 0.06); t, s = t[sel], s[sel]
    p = np.polyfit(t, s, 1); dirs[name] = np.degrees(np.arctan2(d[1], d[0]) + np.arctan(p[0]))
    prof = []
    for t0 in np.arange(0.06, L - 0.06, 0.2):
        k = (t >= t0) & (t < t0 + 0.2)
        prof.append(np.median(s[k] - np.polyval(p, t[k])) * 100 if k.sum() > 5 else np.nan)
    pr = np.array(prof)
    print(f'{name:4s} 벽: 직선에서 벗어남 최대 {np.nanmax(np.abs(pr)):.1f}cm |', ' '.join(' -- ' if np.isnan(x) else f'{x:4.1f}' for x in pr))
print(f'아래-오른쪽 사이 각도: {abs((dirs["오른쪽"] - dirs["아래"] + 180) % 360 - 180):.2f}°')
