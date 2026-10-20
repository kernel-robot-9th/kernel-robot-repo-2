#!/usr/bin/env python3
"""Generate ArUco marker Gazebo models (models/aruco_<id>/) for the sim world."""
import os
import sys

import cv2
import numpy as np

DICT_NAME = 'DICT_5X5_100'      # keep in sync with vla_perception aruco_dictionary
DICT = getattr(cv2.aruco, DICT_NAME)
MARKER_PX = 400   # marker body (black border included)
QUIET_PX = 80     # white quiet zone on each side
MARKER_M = 0.05   # physical marker edge length [m]


def main(out_dir):
    d = cv2.aruco.getPredefinedDictionary(DICT)
    plate_m = MARKER_M * (MARKER_PX + 2 * QUIET_PX) / MARKER_PX
    for mid in range(4):
        img = cv2.aruco.generateImageMarker(d, mid, MARKER_PX)
        img = np.pad(img, QUIET_PX, constant_values=255)
        mdir = os.path.join(out_dir, f'aruco_{mid}')
        tdir = os.path.join(mdir, 'materials', 'textures')
        os.makedirs(tdir, exist_ok=True)
        cv2.imwrite(os.path.join(tdir, f'marker_{mid}.png'), img)
        with open(os.path.join(mdir, 'model.config'), 'w') as f:
            f.write(f"""<?xml version="1.0"?>
<model>
  <name>aruco_{mid}</name>
  <version>1.0</version>
  <sdf version="1.10">model.sdf</sdf>
  <description>ArUco {DICT_NAME} id {mid}, {MARKER_M} m</description>
</model>
""")
        with open(os.path.join(mdir, 'model.sdf'), 'w') as f:
            f.write(f"""<?xml version="1.0"?>
<sdf version="1.10">
  <model name="aruco_{mid}">
    <static>true</static>
    <link name="link">
      <visual name="visual">
        <pose>0 0 0.0005 0 0 0</pose>
        <geometry>
          <plane><normal>0 0 1</normal><size>{plate_m:.4f} {plate_m:.4f}</size></plane>
        </geometry>
        <material>
          <diffuse>1 1 1 1</diffuse>
          <pbr><metal>
            <albedo_map>model://aruco_{mid}/materials/textures/marker_{mid}.png</albedo_map>
            <roughness>1.0</roughness><metalness>0.0</metalness>
          </metal></pbr>
        </material>
      </visual>
    </link>
  </model>
</sdf>
""")
    print(f'generated 4 markers in {out_dir} (plate {plate_m:.3f} m)')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else
         os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models'))
