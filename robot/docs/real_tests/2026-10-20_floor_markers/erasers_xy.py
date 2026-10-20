"""Floor markers 46-49 -> homography (pixel -> floor cm), colored erasers -> floor cm and PROVISIONAL right-arm x, y.

Layout (from the user's tape measure, approximate): paper squares 3 cm, black squares ~2.2 cm (72 % of the paper,
read off the zoomed image); paper-edge gaps ~16 cm across and ~5 cm deep -> centres 19 cm x 8 cm apart.
Floor frame: origin at the centre of the four markers, +X right in the image, +Y away from the arms (image up).
Arm estimate: yesterday's reference (pixel 1324,685 <-> right arm 0.237,-0.011) and arm axes taken parallel to the
marker rectangle (arm +x = floor +Y, arm +y = floor -X). Not measured: verify with `teleop here` on the markers.
  python3 erasers_xy.py out.jpg [input.jpg]
"""
import sys

import cv2
import numpy as np

CAMERA = '/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0'
BLACK_CM = 2.2
W_CM, H_CM = 19.0, 8.0
CENTRES = {46: (-W_CM / 2, H_CM / 2), 47: (W_CM / 2, H_CM / 2), 48: (W_CM / 2, -H_CM / 2), 49: (-W_CM / 2, -H_CM / 2)}
REF_PX, REF_ARM = (1324, 685), (0.2373, -0.0107)
WORK = (1200, 500, 1700, 900)   # u0, v0, u1, v1: right frame, where the erasers are
HUES = [(0, 8, 'red'), (8, 22, 'orange'), (22, 35, 'yellow'), (35, 85, 'green'), (85, 130, 'blue'),
        (130, 150, 'purple'), (150, 181, 'pink')]
COLORS = ['red', 'orange', 'yellow', 'green', 'light blue', 'blue', 'purple', 'pink']


def capture():
    cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2); cap.set(3, 1920); cap.set(4, 1080)
    for _ in range(20):
        ok, frame = cap.read()
    cap.release()
    return frame


def floor_homography(frame):
    """[출력] H (pixel -> floor cm), residual of the 16 marker corners in mm (mean, max)."""
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.errorCorrectionRate = 1.0          # small (~36 px) markers with glare: bits read at the edge
    params.perspectiveRemovePixelPerCell = 8
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), params)
    corners, ids, _ = detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    img_pts, floor_pts = [], []
    h = BLACK_CM / 2
    for c, i in zip(corners, [] if ids is None else ids.flatten()):
        if int(i) not in CENTRES:
            continue
        cx, cy = CENTRES[int(i)]
        # ArUco corner order: top-left, top-right, bottom-right, bottom-left (marker printed upright, image up = +Y)
        for p, (dx, dy) in zip(c.reshape(4, 2), [(-h, h), (h, h), (h, -h), (-h, -h)]):
            img_pts.append(p); floor_pts.append((cx + dx, cy + dy))
    if len(img_pts) != 16:
        raise RuntimeError(f'need markers 46-49 once each, got {len(img_pts) / 4:g}')
    img_pts, floor_pts = np.float32(img_pts), np.float32(floor_pts)
    H, _ = cv2.findHomography(img_pts, floor_pts)
    err = np.linalg.norm(cv2.perspectiveTransform(img_pts[None], H)[0] - floor_pts, axis=1)
    return H, (err.mean() * 10, err.max() * 10)


def to_floor(H, u, v):
    return cv2.perspectiveTransform(np.float32([[[u, v]]]), H)[0, 0]


def to_arm(H, fx, fy):
    """floor cm -> PROVISIONAL right-arm metres (arm +x = floor +Y, arm +y = floor -X, offset from REF)."""
    ref = to_floor(H, *REF_PX)
    return REF_ARM[0] + (fy - ref[1]) / 100, REF_ARM[1] - (fx - ref[0]) / 100


def find_erasers(frame, H):
    """[출력] list of dicts: id, color, u, v, floor_cm, size_cm, yaw_deg, arm_m, contour."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # bright pastel erasers wash out (S 50-80 at V 255); the carpet stays darker (V < 140)
    mask = cv2.inRange(hsv, (0, 90, 80), (180, 255, 255)) | cv2.inRange(hsv, (0, 40, 170), (180, 255, 255))
    roi = np.zeros_like(mask); roi[WORK[1]:WORK[3], WORK[0]:WORK[2]] = 255
    mask = cv2.morphologyEx(mask & roi, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    found, counts = [], {}
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(contour) < 1200:
            continue
        blob = np.zeros_like(mask); cv2.drawContours(blob, [contour], -1, 255, -1)
        hue = float(np.median(hsv[..., 0][blob > 0]))
        sat = float(np.median(hsv[..., 1][blob > 0]))
        color = next(n for lo, hi, n in HUES if lo <= hue < hi)
        if color == 'blue' and sat < 180:
            color = 'light blue'
        rect = cv2.minAreaRect(contour)
        corners_floor = cv2.perspectiveTransform(np.float32(cv2.boxPoints(rect))[None], H)[0]
        sides = [np.linalg.norm(corners_floor[k] - corners_floor[(k + 1) % 4]) for k in range(4)]
        long_k = int(np.argmax(sides[:2]))
        dx, dy = corners_floor[long_k + 1] - corners_floor[long_k]
        yaw = (np.degrees(np.arctan2(dy, dx)) + 90) % 180 - 90
        fx, fy = to_floor(H, *rect[0])
        n = counts.get(color, 0); counts[color] = n + 1
        found.append({'id': f"{color.replace(' ', '_')}_{n}", 'color': color, 'u': rect[0][0], 'v': rect[0][1],
                      'hue': hue, 'sat': sat, 'floor_cm': (float(fx), float(fy)),
                      'size_cm': (max(sides[:2]), min(sides[:2])), 'yaw_deg': float(yaw),
                      'arm_m': to_arm(H, fx, fy), 'contour': contour})
    return found


if __name__ == '__main__':
    out = sys.argv[1]
    if len(sys.argv) > 2:
        frame = cv2.imread(sys.argv[2])
    else:
        frame = capture()
        cv2.imwrite(out.replace('.jpg', '_raw.jpg'), frame)
    H, (mean_mm, max_mm) = floor_homography(frame)
    print(f'homography from 16 corners: residual mean {mean_mm:.1f} mm, max {max_mm:.1f} mm')
    ref = to_floor(H, *REF_PX)
    print(f'reference point (1324,685) -> floor ({ref[0]:+.1f}, {ref[1]:+.1f}) cm')
    vis = frame.copy()
    cv2.rectangle(vis, WORK[:2], WORK[2:], (0, 255, 255), 1)
    print(f'{"color":11s} {"pixel":>12s}  {"floor X,Y cm":>14s}  {"size cm":>11s}  {"yaw":>5s}  arm x, y (m, provisional)')
    for e in find_erasers(frame, H):
        (fx, fy), (a, b), (ax, ay) = e['floor_cm'], e['size_cm'], e['arm_m']
        print(f"{e['color']:11s} ({e['u']:5.0f},{e['v']:4.0f})  ({fx:+6.1f},{fy:+6.1f})  {a:4.1f}x{b:4.1f}  "
              f"{e['yaw_deg']:+5.0f}  x {ax:+.3f}  y {ay:+.3f}   (hue {e['hue']:.0f}, sat {e['sat']:.0f})")
        cv2.drawContours(vis, [e['contour']], -1, (0, 0, 255), 2)
        cv2.putText(vis, f"{e['color']} ({ax:+.3f},{ay:+.3f})", (int(e['u']) - 80, int(e['v']) - 40), 0, 0.7,
                    (0, 0, 255), 2)
    cv2.imwrite(out, vis)
