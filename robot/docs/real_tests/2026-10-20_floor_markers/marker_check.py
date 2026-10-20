"""Top view floor-marker check: capture, detect ArUco DICT_4X4_50, report ids, centres, size, and distances
in cm using the printed marker side (2.2 cm black square) as the scale.  python3 marker_check.py out.jpg [input.jpg]"""
import itertools
import sys

import cv2
import numpy as np

CAMERA = '/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0'
SIDE_M = 0.022   # black square; the 3 cm printed size includes the white paper
FLOOR_IDS = [46, 47, 48, 49]
out = sys.argv[1]
if len(sys.argv) > 2:
    frame = cv2.imread(sys.argv[2])
else:
    cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2); cap.set(3, 1920); cap.set(4, 1080)
    for _ in range(20):
        ok, frame = cap.read()
    cap.release()
    cv2.imwrite(out.replace('.jpg', '_raw.jpg'), frame)
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
params = cv2.aruco.DetectorParameters()
params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
params.errorCorrectionRate = 1.0          # small (~36 px) markers with glare: bits read at the edge
params.perspectiveRemovePixelPerCell = 8
detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), params)
corners, ids, _ = detector.detectMarkers(gray)
found = {}
vis = frame.copy()
if ids is not None:
    cv2.aruco.drawDetectedMarkers(vis, corners, ids)
    for c, i in zip(corners, ids.flatten()):
        pts = c.reshape(4, 2)
        side = np.mean([np.linalg.norm(pts[k] - pts[(k + 1) % 4]) for k in range(4)])
        found.setdefault(int(i), []).append((pts.mean(0), side, pts))
print(f'frame {frame.shape[1]}x{frame.shape[0]}')
for i in sorted(found):
    for centre, side, _ in found[i]:
        tag = '  <- floor' if i in FLOOR_IDS else ''
        print(f'id {i:2d}  centre ({centre[0]:7.1f},{centre[1]:6.1f})  side {side:5.1f} px  '
              f'{SIDE_M * 1000 / side:.2f} mm/px{tag}')
floor = {i: found[i][0] for i in FLOOR_IDS if i in found and len(found[i]) == 1}
missing = [i for i in FLOOR_IDS if i not in found]
dup = [i for i in FLOOR_IDS if len(found.get(i, [])) > 1]
print('floor markers found:', sorted(floor), ' missing:', missing, ' duplicated:', dup)
if len(floor) >= 2:
    scale = SIDE_M / np.mean([s for _, s, _ in floor.values()])
    print(f'mean scale {scale * 1000:.3f} mm/px (from the black squares)')
    for a, b in itertools.combinations(sorted(floor), 2):
        d = np.linalg.norm(floor[a][0] - floor[b][0])
        print(f'  {a}-{b}: {d:6.1f} px  ~{d * scale * 100:5.1f} cm')
    for i, (centre, _, pts) in floor.items():
        cv2.putText(vis, str(i), tuple(int(v) for v in centre + (20, -20)), 0, 1.2, (0, 0, 255), 3)
cv2.imwrite(out, vis)
