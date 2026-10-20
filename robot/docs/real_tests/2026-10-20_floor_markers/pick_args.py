"""Top view -> one eraser by color -> `teleop pick` arguments in the right-arm frame (floor_to_arm.json).
  python3 pick_args.py <color> [input.jpg]      e.g. python3 pick_args.py blue
Pick z = eraser top measured at the blue spot (-0.034) - 1 cm floor + 0.5 cm + 3 mm sag margin; place on marker 48.
"""
import json
import math
import os
import sys

import cv2
import numpy as np

from erasers_xy import capture, find_erasers, floor_homography

HERE = os.path.dirname(os.path.abspath(__file__))
FLOOR_Z = -0.044            # floor under the blue eraser spot, right-arm frame (eraser top -0.034 touched 10:04)
PICK_Z = FLOOR_Z + 0.005 + 0.003
PLACE_FLOOR_CM, PLACE_Z = (9.5, -4.0), -0.028   # marker 48; release ~8 mm above the floor
ROTATION_DEG = 5.2          # floor axes -> arm axes, from fit_floor_to_arm.py

fit = json.load(open(os.path.join(HERE, 'floor_to_arm.json')))
R, t = np.array(fit['R']), np.array(fit['t'])


def to_arm(fx_cm, fy_cm):
    return R @ np.array([fy_cm / 100, -fx_cm / 100]) + t


color = sys.argv[1].replace('_', ' ')
frame = cv2.imread(sys.argv[2]) if len(sys.argv) > 2 else capture()
try:
    H, _ = floor_homography(frame)
except RuntimeError as error:   # a marker covered (e.g. an eraser placed on 48): the camera is fixed, reuse a full view
    print(f'{error}; using the homography of check2_raw.jpg')
    H, _ = floor_homography(cv2.imread(os.path.join(HERE, 'check2_raw.jpg')))
match = [e for e in find_erasers(frame, H) if e['color'] == color]
if len(match) != 1:
    sys.exit(f'{len(match)} erasers of color {color}')
e = match[0]
x, y = to_arm(*e['floor_cm'])
px, py = to_arm(*PLACE_FLOOR_CM)
closing = e['yaw_deg'] + ROTATION_DEG            # across the short side: floor long-axis yaw - 90 + rotation + 90
closing = (closing + 90) % 180 - 90
print(f"{e['id']}: floor ({e['floor_cm'][0]:+.1f}, {e['floor_cm'][1]:+.1f}) cm, long side {e['yaw_deg']:+.0f} deg, "
      f"size {e['size_cm'][0]:.1f} x {e['size_cm'][1]:.1f} cm -> arm ({x:+.3f}, {y:+.3f}), reach {math.hypot(x, y):.3f} m")
print(f'--x {x:.3f} --y {y:.3f} --z {PICK_Z:.3f} --yaw {closing:.0f} '
      f'--place-x {px:.3f} --place-y {py:.3f} --place-z {PLACE_Z:.3f}')
