"""PROVISIONAL top-view pixel -> right-arm base frame (x, y, z), from ONE reference point. Replace with floor markers 46-49.

Assumptions (not measured):
  - camera looks straight down and its image axes match the arm: image up = arm +x, image left = arm +y
  - scale from the reference point and the right arm's joint1 axis, guessed at pixel row 1010 (base plate centre)
  - lid tops are as high as the reference lid (z of the closed gripper tip resting on the blue lid)
  python3 pixel_to_arm_estimate.py <u> <v> [<u> <v> ...]
"""
import math
import sys

REF_PX = (1324, 685)                   # blue lid centre in the top view when the tool was centred over it
REF_ARM = (0.2373, -0.0107, -0.0518)   # tool x, y, z (m) at that moment, gripper closed (calib_points_v1_closed_gripper.csv)
BASE_ROW_PX = 1010                     # guessed image row of the right arm's joint1 axis
M_PER_PX = REF_ARM[0] / (BASE_ROW_PX - REF_PX[1])
SAFE_Z_MIN = -0.04
MAX_REACH = 0.296                      # farthest tool x measured by teleop


def to_arm(u, v):
    x = REF_ARM[0] + (REF_PX[1] - v) * M_PER_PX
    y = REF_ARM[1] - (u - REF_PX[0]) * M_PER_PX
    return x, y, REF_ARM[2]


if __name__ == '__main__':
    print(f'scale {M_PER_PX * 1000:.2f} mm/px (estimate)')
    values = [float(a) for a in sys.argv[1:]]
    for u, v in zip(values[0::2], values[1::2]):
        x, y, z = to_arm(u, v)
        reach = math.hypot(x, y)
        notes = []
        if reach > MAX_REACH:
            notes.append('beyond measured reach')
        if z < SAFE_Z_MIN:
            notes.append(f'lid top below safe z {SAFE_Z_MIN}')
        print(f'pixel ({u:.0f},{v:.0f}) -> x {x:+.3f}  y {y:+.3f}  z {z:+.3f} m  reach {reach:.3f} m'
              + (f'  [{"; ".join(notes)}]' if notes else ''))
