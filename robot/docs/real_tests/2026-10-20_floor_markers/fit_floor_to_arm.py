"""Fit floor (cm, marker frame) -> right arm (m) as a 2D rotation + translation from points touched with the leader.
  python3 fit_floor_to_arm.py points.csv   -> prints the fit and writes floor_to_arm.json
"""
import csv
import json
import math
import sys

import numpy as np

FLOOR_CM = {'marker47': (9.5, 4.0), 'marker48': (9.5, -4.0),
            'blue_eraser_top': (19.1, -0.4)}   # eraser centre from erasers_xy.py on check2_raw.jpg
rows = {r['label']: r for r in csv.DictReader(open(sys.argv[1]))}
names = [n for n in FLOOR_CM if n in rows]
F = np.array([FLOOR_CM[n] for n in names]) / 100.0
A = np.array([(float(rows[n]['x_m']), float(rows[n]['y_m'])) for n in names])
# arm axes are nominally floor (+Y, -X): pre-rotate, then fit the small extra rotation + translation (Kabsch, no scale)
P = np.column_stack([F[:, 1], -F[:, 0]])
pc, ac = P.mean(0), A.mean(0)
U, _, Vt = np.linalg.svd((P - pc).T @ (A - ac))
R = (U @ Vt).T
if np.linalg.det(R) < 0:
    Vt[-1] *= -1; R = (U @ Vt).T
t = ac - R @ pc
res = A - (P @ R.T + t)
print(f'points: {names}')
print(f'extra rotation {math.degrees(math.atan2(R[1, 0], R[0, 0])):+.1f} deg, translation ({t[0]:+.4f}, {t[1]:+.4f}) m')
for n, r, z in zip(names, res, [float(rows[n]['z_m']) for n in names]):
    print(f'   {n:16s} residual ({r[0] * 1000:+5.1f}, {r[1] * 1000:+5.1f}) mm   z {z:+.4f}  tilt {rows[n]["tilt_deg"]}')
json.dump({'R': R.tolist(), 't': t.tolist(), 'points': names}, open('floor_to_arm.json', 'w'), indent=2)
