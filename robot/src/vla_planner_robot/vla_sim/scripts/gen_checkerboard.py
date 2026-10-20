#!/usr/bin/env python3
"""Generate a checkerboard Gazebo model (models/checkerboard/) for intrinsic calibration in sim."""
import os
import sys

import cv2
import numpy as np

COLS, ROWS = 10, 7          # squares -> 9 x 6 inner corners
SQUARE_PX = 80
BORDER_PX = 80
SQUARE_M = 0.03


def main(out_dir):
    w, h = COLS * SQUARE_PX + 2 * BORDER_PX, ROWS * SQUARE_PX + 2 * BORDER_PX
    img = np.full((h, w), 255, np.uint8)
    for r in range(ROWS):
        for c in range(COLS):
            if (r + c) % 2 == 0:
                y, x = BORDER_PX + r * SQUARE_PX, BORDER_PX + c * SQUARE_PX
                img[y:y + SQUARE_PX, x:x + SQUARE_PX] = 0
    mdir = os.path.join(out_dir, 'checkerboard')
    tdir = os.path.join(mdir, 'materials', 'textures')
    os.makedirs(tdir, exist_ok=True)
    cv2.imwrite(os.path.join(tdir, 'checkerboard_9x6.png'), img)
    sx, sy = w / SQUARE_PX * SQUARE_M, h / SQUARE_PX * SQUARE_M
    with open(os.path.join(mdir, 'model.config'), 'w') as f:
        f.write(f"""<?xml version="1.0"?>
<model><name>checkerboard</name><version>1.0</version><sdf version="1.10">model.sdf</sdf>
<description>9x6 inner corners, {SQUARE_M} m squares</description></model>
""")
    with open(os.path.join(mdir, 'model.sdf'), 'w') as f:
        f.write(f"""<?xml version="1.0"?>
<sdf version="1.10">
  <model name="checkerboard">
    <static>true</static>
    <link name="link">
      <visual name="visual">
        <geometry><plane><normal>0 0 1</normal><size>{sx:.4f} {sy:.4f}</size></plane></geometry>
        <material>
          <diffuse>1 1 1 1</diffuse>
          <pbr><metal>
            <albedo_map>model://checkerboard/materials/textures/checkerboard_9x6.png</albedo_map>
            <roughness>1.0</roughness><metalness>0.0</metalness>
          </metal></pbr>
        </material>
      </visual>
    </link>
  </model>
</sdf>
""")
    print(f'checkerboard model in {mdir} ({sx:.3f} x {sy:.3f} m)')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else
         os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models'))
