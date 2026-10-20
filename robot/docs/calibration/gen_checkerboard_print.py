"""Printable checkerboard for `vla_calibration intrinsics` (real top camera): A4 landscape, 300 dpi, exact size.
  python3 gen_checkerboard_print.py [cols_inner rows_inner square_mm]     default 9 6 25
Writes checkerboard_<c>x<r>_<s>mm_A4.png/.pdf. Print at 100 % ("actual size"), then check the 100 mm bar with a ruler.
"""
import sys

import cv2
import numpy as np
from PIL import Image

DPI = 300
PAGE_MM = (297.0, 210.0)                     # A4 landscape
cols, rows, square_mm = (int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (9, 6, 25.0)
px = lambda mm: int(round(mm * DPI / 25.4))  # noqa: E731
W, H = px(PAGE_MM[0]), px(PAGE_MM[1])
img = np.full((H, W), 255, np.uint8)
nx, ny = cols + 1, rows + 1                  # squares
board_w, board_h = nx * square_mm, ny * square_mm
if board_w > PAGE_MM[0] - 20 or board_h > PAGE_MM[1] - 30:
    sys.exit(f'{board_w:.0f} x {board_h:.0f} mm does not fit A4 with margins')
x0, y0 = (PAGE_MM[0] - board_w) / 2, 10.0
for r in range(ny):
    for c in range(nx):
        if (r + c) % 2 == 0:                 # square edges rounded from mm, so every square is exact to 0.1 mm
            img[px(y0 + r * square_mm):px(y0 + (r + 1) * square_mm), px(x0 + c * square_mm):px(x0 + (c + 1) * square_mm)] = 0
# 100 mm check bar with 10 mm ticks
by = y0 + board_h + 8
cv2.rectangle(img, (px(x0), px(by)), (px(x0 + 100), px(by + 1.5)), 0, -1)
for k in range(11):
    cv2.rectangle(img, (px(x0 + 10 * k) - 2, px(by - 3)), (px(x0 + 10 * k) + 2, px(by + 1.5)), 0, -1)
lines = (f'{cols}x{rows} inner corners, {square_mm:g} mm squares. Bar = 100 mm: print at 100 %.',
         f'ros2 run vla_calibration intrinsics --board {cols}x{rows} --square {square_mm / 1000:g}')
for k, line in enumerate(lines):
    cv2.putText(img, line, (px(x0 + 106), px(by - 1.5 + 5 * k)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 3, cv2.LINE_AA)
stem = f'checkerboard_{cols}x{rows}_{square_mm:g}mm_A4'
cv2.imwrite(stem + '.png', img)
Image.fromarray(img).save(stem + '.pdf', resolution=DPI)
# self-check: OpenCV must find the inner corners in the rendered page
found, corners = cv2.findChessboardCorners(cv2.resize(img, None, fx=0.25, fy=0.25), (cols, rows))
print(f'{stem}: board {board_w:.0f} x {board_h:.0f} mm on A4, corners found: {found}')
