"""Small table point markers for the 9-point homography (A4, 300 dpi): DICT_5X5_100 ids 20-28 (fit) and 29-32 (check).
  python3 gen_point_markers.py [marker_mm]     default 25
Each marker has a white margin, its id and centre ticks on its four sides; cut along the grey lines. The gripper tip touches the centre.
"""
import sys

import cv2
import numpy as np
from PIL import Image

DPI = 300
mm = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
px = lambda v: int(round(v * DPI / 25.4))  # noqa: E731
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
ids = list(range(20, 33))
cell = mm + 16.0                                  # marker + white margin + label
page = np.full((px(297), px(210)), 255, np.uint8)
cols = int((210 - 20) // cell)
for k, i in enumerate(ids):
    r, c = divmod(k, cols)
    x, y = 10 + c * cell, 14 + r * (cell + 6)
    img = cv2.aruco.generateImageMarker(dictionary, i, px(mm), borderBits=1)
    page[px(y + 4):px(y + 4) + img.shape[0], px(x + 8):px(x + 8) + img.shape[1]] = img
    x1, y1, x2, y2 = px(x + 8), px(y + 4), px(x + 8 + mm), px(y + 4 + mm)      # centre ticks outside the marker
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    for p1, p2 in (((cx, y1 - px(3)), (cx, y1 - px(1))), ((cx, y2 + px(1)), (cx, y2 + px(3))),
                   ((x1 - px(3), cy), (x1 - px(1), cy)), ((x2 + px(1), cy), (x2 + px(3), cy))):
        cv2.line(page, p1, p2, 0, 4)
    cv2.rectangle(page, (px(x), px(y)), (px(x + cell), px(y + cell + 2)), 170, 2)
    label = f'{i} {"fit" if i <= 28 else "check"}'
    cv2.putText(page, label, (px(x + 8), px(y + mm + 11)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3, cv2.LINE_AA)
cv2.putText(page, f'DICT_5X5_100, {mm:g} mm markers. 20-28: 3x3 fit points, 29-32: check points. Print at 100 %.',
            (px(10), px(290)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)
stem = f'point_markers_5x5_id20-32_{mm:g}mm_A4'
cv2.imwrite(stem + '.png', page)
Image.fromarray(page).save(stem + '.pdf', resolution=DPI)
found = cv2.aruco.ArucoDetector(dictionary).detectMarkers(cv2.resize(page, None, fx=0.3, fy=0.3))[1]
print(f'{stem}: ids found {sorted(found.flatten().tolist()) if found is not None else []}')
