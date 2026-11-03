"""Printable ChArUco board for the top-camera intrinsics (A4 landscape, 300 dpi, exact size).
  python3 gen_charuco_print.py [squares_x squares_y square_mm marker_mm]     default 7 5 30 22 (the calibration guide)
Dictionary DICT_5X5_100, board markers 0..16 (so table point markers use ids 20 and up). Print at 100 %.
"""
import sys

import cv2
import numpy as np
from PIL import Image

DPI = 300
PAGE_MM = (297.0, 210.0)
sx, sy, square_mm, marker_mm = ((int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
                                if len(sys.argv) > 4 else (7, 5, 30.0, 22.0))
px = lambda mm: int(round(mm * DPI / 25.4))  # noqa: E731
board = cv2.aruco.CharucoBoard((sx, sy), square_mm / 1000, marker_mm / 1000,
                               cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100))
bw, bh = sx * square_mm, sy * square_mm
art = board.generateImage((px(bw), px(bh)), marginSize=0, borderBits=1)
page = np.full((px(PAGE_MM[1]), px(PAGE_MM[0])), 255, np.uint8)
x0, y0 = (PAGE_MM[0] - bw) / 2, 12.0
page[px(y0):px(y0) + art.shape[0], px(x0):px(x0) + art.shape[1]] = art
by = y0 + bh + 10
cv2.rectangle(page, (px(x0), px(by)), (px(x0 + 100), px(by + 1.5)), 0, -1)
for k in range(11):
    cv2.rectangle(page, (px(x0 + 10 * k) - 2, px(by - 3)), (px(x0 + 10 * k) + 2, px(by + 1.5)), 0, -1)
lines = (f'ChArUco {sx}x{sy} squares, square {square_mm:g} mm, marker {marker_mm:g} mm, DICT_5X5_100 ids 0-{board.getIds().max()}.',
         'Bar = 100 mm: print at 100 %, then measure a square and a marker and use those numbers.')
for k, line in enumerate(lines):
    cv2.putText(page, line, (px(x0 + 106), px(by - 1.5 + 5 * k)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 3, cv2.LINE_AA)
stem = f'charuco_{sx}x{sy}_{square_mm:g}mm_{marker_mm:g}mm_A4'
cv2.imwrite(stem + '.png', page)
Image.fromarray(page).save(stem + '.pdf', resolution=DPI)
corners, ids, _, _ = cv2.aruco.CharucoDetector(board).detectBoard(cv2.resize(page, None, fx=0.3, fy=0.3))
print(f'{stem}: board {bw:g} x {bh:g} mm, chessboard corners found {0 if ids is None else len(ids)} of {(sx - 1) * (sy - 1)}')
