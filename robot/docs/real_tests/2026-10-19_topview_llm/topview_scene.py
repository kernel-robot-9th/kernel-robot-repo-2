"""Top camera scene check: capture, HSV stats of lids, colored-lid blobs, markers. Pixel coordinates only."""
import sys, cv2, numpy as np
out = sys.argv[1]
cap = cv2.VideoCapture(4, cv2.CAP_V4L2); cap.set(3, 1920); cap.set(4, 1080)
for _ in range(20): ok, frame = cap.read()
cap.release()
cv2.imwrite(out.replace('.jpg', '_raw.jpg'), frame)
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
# color ranges for the lids seen in the photos (OpenCV H 0..180); first guesses, to be calibrated
RANGES = {'orange': [(5, 80, 120), (18, 255, 255)], 'green': [(40, 40, 50), (85, 255, 200)],
          'blue': [(95, 90, 80), (125, 255, 255)], 'gray': [(0, 0, 120), (180, 35, 210)]}
DRAW = {'orange': (0, 140, 255), 'green': (0, 180, 0), 'blue': (255, 120, 0), 'gray': (160, 160, 160)}
vis = frame.copy()
h_img = frame.shape[0]
print(f'frame {frame.shape[1]}x{frame.shape[0]}')
for name, (lo, hi) in RANGES.items():
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    blobs = []
    for k in range(1, n):
        x, y, w, h, area = stats[k]
        if not (2500 < area < 40000) or y > h_img * 0.95: continue
        if name == 'gray' and not (0.6 < w / h < 1.6): continue
        blobs.append((int(cents[k][0]), int(cents[k][1]), int(area), w, h))
        cv2.rectangle(vis, (x, y), (x + w, y + h), DRAW[name], 3)
        cv2.putText(vis, name, (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, DRAW[name], 2)
    print(f'{name:6s}: {len(blobs)} -> ' + ', '.join(f'({cx},{cy}) {w}x{h}px' for cx, cy, a, w, h in blobs))
det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
corners, ids, _ = det.detectMarkers(frame)
if ids is not None:
    cv2.aruco.drawDetectedMarkers(vis, corners, ids)
print('markers 4X4_50:', [] if ids is None else [int(i) for i in ids.flatten()])
cv2.imwrite(out, vis)
