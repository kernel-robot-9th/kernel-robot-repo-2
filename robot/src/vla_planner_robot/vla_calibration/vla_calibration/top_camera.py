"""Real top-camera calibration (no ROS): ChArUco intrinsics, then a 9-point table homography pixel -> arm (x, y).

Follows the team guide "OMX 탑뷰 카메라 캘리브레이션 가이드" (2026-10-21):
  1. intrinsics: ChArUco 7x5 squares, 30 / 22 mm, DICT_5X5_100, 20-30 views, RMS <= 0.5 px
  2. table plane: 9 points in a 3x3 grid (markers DICT_5X5_100 ids 20-28) -> cv2.findHomography on undistorted
     pixels, mean error <= 5 mm; ids 29-32 are check points never used in the fit.
The arm side of each point comes from `ros2 run vla_teleop teleop here p<id>` (tool tip resting on the marker centre,
same FK end point the pick tools use); several rows with the same label are averaged (backlash).

  ros2 run vla_calibration top_camera capture      # live view, SPACE saves a view, Q quits
  ros2 run vla_calibration top_camera intrinsics   # -> calib/top_intrinsics.yaml
  ros2 run vla_calibration top_camera points       # marker centres in the top view -> calib/table_points_px.csv
  ros2 run vla_calibration top_camera homography --arm-points ~/.cache/vla_teleop/<session>/points.csv
"""
import argparse
import csv
import glob
import os
import sys
import time

import cv2
import numpy as np
import yaml

CALIB_DIR = os.path.expanduser('~/dev_ws/robot/calib')
CAMERA = '/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0'
SIZE = (1920, 1080)
DICTIONARY = cv2.aruco.DICT_5X5_100
FIT_IDS = list(range(20, 29))
CHECK_IDS = list(range(29, 33))
RMS_TARGET_PX = 0.5
MEAN_TARGET_MM = 5.0


# ---------------------------------------------------------------------------- pure helpers (tested)
def make_board(squares=(7, 5), square_m=0.030, marker_m=0.022):
    return cv2.aruco.CharucoBoard(squares, square_m, marker_m, cv2.aruco.getPredefinedDictionary(DICTIONARY))


class Pattern:
    """Calibration target: ChArUco (guide default) or a plain chessboard (`--pattern chessboard --board 9x6`).
    find(gray, fast) -> (image points N x 1 x 2, object points N x 1 x 3) or (None, None)."""

    def __init__(self, args):
        self.kind = args.pattern
        if self.kind == 'charuco':
            self.board = make_board(tuple(args.squares), args.square, args.marker)
            self.detector = cv2.aruco.CharucoDetector(self.board)
            self.min_points = 8
            self.label = f'ChArUco {args.squares[0]}x{args.squares[1]} {args.square * 1000:g}/{args.marker * 1000:g} mm'
        else:
            cols, rows = (int(v) for v in args.board.lower().split('x'))
            self.size = (cols, rows)
            grid = np.zeros((cols * rows, 3), np.float32)
            grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * args.square
            self.grid = grid.reshape(-1, 1, 3)
            self.min_points = cols * rows
            self.label = f'chessboard {cols}x{rows} inner corners, {args.square * 1000:g} mm'

    def find(self, gray, fast=False):
        if self.kind == 'charuco':
            corners, ids, _, _ = self.detector.detectBoard(gray)
            if ids is None or len(ids) < self.min_points:
                return None, None
            obj, img = self.board.matchImagePoints(corners, ids)
            return img, obj
        if fast:   # live preview: half resolution, quick reject when no board is in view
            small = cv2.resize(gray, None, fx=0.5, fy=0.5)
            ok, corners = cv2.findChessboardCorners(small, self.size, cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK)
            return (corners * 2, self.grid) if ok else (None, None)
        ok, corners = cv2.findChessboardCornersSB(gray, self.size, cv2.CALIB_CB_EXHAUSTIVE + cv2.CALIB_CB_ACCURACY)
        return (corners, self.grid) if ok else (None, None)


def marker_centre(corners):
    """Intersection of the marker's diagonals: the true centre under perspective (the corner mean is not)."""
    p = np.asarray(corners, np.float64).reshape(4, 2)
    d1, d2 = p[2] - p[0], p[3] - p[1]
    cross = lambda a, b: a[0] * b[1] - a[1] * b[0]   # noqa: E731 - 2D cross (numpy 2 dropped 2D np.cross)
    t = cross(p[1] - p[0], d2) / cross(d1, d2)
    return p[0] + t * d1


def average_arm_points(rows):
    """teleop `points.csv` rows -> {marker id: (x, y, z, n, max tilt deg)} for labels `p<id>`, repeated rows averaged."""
    groups = {}
    for row in rows:
        label = row['label'].strip()
        if not (label.startswith('p') and label[1:].isdigit()):
            continue
        groups.setdefault(int(label[1:]), []).append(
            (float(row['x_m']), float(row['y_m']), float(row['z_m']), abs(float(row.get('tilt_deg') or 0))))
    out = {}
    for marker_id, values in groups.items():
        v = np.array(values)
        out[marker_id] = (*v[:, :3].mean(0), len(values), v[:, 3].max())
    return out


def fit_homography(pixels, arm_xy):
    """[입력] undistorted pixels N x 2, arm (x, y) m N x 2 [출력] H (3x3), per-point error mm."""
    pixels, arm_xy = np.float32(pixels), np.float32(arm_xy)
    H, _ = cv2.findHomography(pixels, arm_xy, 0)           # all points: 9 hand-made pairs, no outlier rejection
    return H, error_mm(H, pixels, arm_xy)


def error_mm(H, pixels, arm_xy):
    pred = cv2.perspectiveTransform(np.float32(pixels).reshape(-1, 1, 2), H).reshape(-1, 2)
    return np.linalg.norm(pred - np.float32(arm_xy), axis=1) * 1000


def average_labelled(rows, prefix):
    """teleop rows -> {label: (x, y, z, n, max tilt)} for labels starting with `prefix` (repeats averaged)."""
    groups = {}
    for row in rows:
        label = row['label'].strip()
        if label.startswith(prefix):
            groups.setdefault(label, []).append((float(row['x_m']), float(row['y_m']), float(row['z_m']),
                                                 abs(float(row.get('tilt_deg') or 0))))
    return {k: (*np.array(v)[:, :3].mean(0), len(v), np.array(v)[:, 3].max()) for k, v in groups.items()}


def fit_rigid_2d(src, dst):
    """Rotation + translation (no scale, reflection allowed: the board may lie face up either way round) taking
    board points src (m) to arm points dst (m). [출력] R (2x2), t (2,), residual per point (m)."""
    src, dst = np.asarray(src, np.float64), np.asarray(dst, np.float64)
    sc, dc = src.mean(0), dst.mean(0)
    U, _, Vt = np.linalg.svd((src - sc).T @ (dst - dc))
    R = (U @ Vt).T
    t = dc - R @ sc
    return R, t, np.linalg.norm(src @ R.T + t - dst, axis=1)


def plane_z(arm_xyz):
    """Least-squares plane z = a + b x + c y through the touched tool heights (floor + sag as the arm sees it)."""
    p = np.asarray(arm_xyz, np.float64)
    A = np.column_stack([np.ones(len(p)), p[:, 0], p[:, 1]])
    coef, *_ = np.linalg.lstsq(A, p[:, 2], rcond=None)
    return coef, p[:, 2] - A @ coef


def undistort(pixels, K, dist):
    return cv2.undistortPoints(np.float32(pixels).reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)


def pixel_to_arm(u, v, calib):
    """Top-view pixel (raw camera image) -> right-arm (x, y) m, from the saved intrinsics + homography."""
    p = undistort([[u, v]], calib['K'], calib['dist'])
    x, y = cv2.perspectiveTransform(p.reshape(-1, 1, 2), calib['H'])[0, 0]
    return float(x), float(y)


def load_calibration(calib_dir=CALIB_DIR):
    with open(os.path.join(calib_dir, 'top_intrinsics.yaml')) as handle:
        intr = yaml.safe_load(handle)
    with open(os.path.join(calib_dir, 'top_homography.yaml')) as handle:
        homo = yaml.safe_load(handle)
    return {'K': np.array(intr['K']), 'dist': np.array(intr['dist']), 'H': np.array(homo['H']),
            'size': tuple(intr['size']), 'plane_z': homo.get('plane_z')}


# ---------------------------------------------------------------------------- camera
def open_camera(device):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, SIZE[0]); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, SIZE[1])
    for _ in range(30):
        cap.read()
    ok, frame = cap.read()
    if not ok:
        sys.exit(f'cannot read {device}')
    if (frame.shape[1], frame.shape[0]) != SIZE:
        sys.exit(f'{device} gives {frame.shape[1]}x{frame.shape[0]}, expected {SIZE[0]}x{SIZE[1]} (resolution is fixed)')
    return cap


def cmd_capture(args):
    """Live view with ChArUco detection and a 4x4 coverage grid; SPACE saves the view when enough corners show."""
    os.makedirs(args.out, exist_ok=True)
    pattern = Pattern(args)
    cap = open_camera(args.camera)
    coverage = np.zeros((4, 4), int)
    existing = sorted(glob.glob(os.path.join(args.out, '*.png')))
    saved = len(existing)
    for path in existing:                                   # views from an earlier session count for the red cells too
        found, _ = pattern.find(cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY), fast=True)
        for u, v in ([] if found is None else found.reshape(-1, 2)):
            coverage[min(3, int(v * 4 // SIZE[1])), min(3, int(u * 4 // SIZE[0]))] += 1
    if existing:
        print(f'{saved} views already in {args.out}; red cells show where none of them reached')
    title = f'{pattern.label} capture (SPACE save, Q quit)'
    cv2.namedWindow(title, cv2.WINDOW_NORMAL); cv2.resizeWindow(title, 1280, 720)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        corners, _ = pattern.find(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), fast=True)
        n = 0 if corners is None else len(corners)
        shown = frame.copy()
        if n:
            for u, v in corners.reshape(-1, 2):
                cv2.circle(shown, (int(u), int(v)), 6, (0, 255, 0), 2)
        h, w = frame.shape[:2]
        for r in range(4):
            for c in range(4):
                if coverage[r, c] == 0:
                    cv2.rectangle(shown, (c * w // 4, r * h // 4), ((c + 1) * w // 4, (r + 1) * h // 4), (0, 0, 255), 2)
        cv2.putText(shown, f'corners {n}  saved {saved}  (red cells: no view there yet; tilt the board too)',
                    (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
        cv2.imshow(title, shown)
        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            break
        if key == ord(' '):
            if n < pattern.min_points:
                print(f'not saved: board not found ({n} corners)')
                continue
            path = os.path.join(args.out, f'view_{time.strftime("%H%M%S")}_{saved:02d}.png')
            cv2.imwrite(path, frame)
            saved += 1
            for u, v in corners.reshape(-1, 2):
                coverage[min(3, int(v * 4 // h)), min(3, int(u * 4 // w))] += 1
            print(f'saved {path} ({n} corners)')
    cap.release(); cv2.destroyAllWindows()
    print(f'{saved} views in {args.out} (aim for 20-30)')
    return 0


def cmd_intrinsics(args):
    pattern = Pattern(args)
    obj, img, names, size = [], [], [], None
    for path in sorted(glob.glob(os.path.join(args.images, '*.png'))):
        gray = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        i, o = pattern.find(gray)
        if i is None:
            print(f'   skip {os.path.basename(path)}: board not found')
            continue
        obj.append(np.float32(o)); img.append(np.float32(i)); names.append(os.path.basename(path))
    if len(obj) < 10:
        sys.exit(f'only {len(obj)} usable views; capture 20-30')
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(obj, img, size, None, None)
    per_view = []
    for o, i, r, t in zip(obj, img, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, r, t, K, dist)
        per_view.append(float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - i.reshape(-1, 2)) ** 2, axis=1)))))
    for name, err in sorted(zip(names, per_view), key=lambda e: -e[1])[:5]:
        print(f'   worst views: {name} {err:.2f} px')
    print(f'RMS reprojection {rms:.3f} px over {len(obj)} views (target <= {RMS_TARGET_PX}; above 1.0: recapture)')
    print(f'fx {K[0, 0]:.1f} fy {K[1, 1]:.1f} cx {K[0, 2]:.1f} cy {K[1, 2]:.1f}  dist {np.round(dist.ravel(), 4).tolist()}')
    out = {'size': list(size), 'K': K.tolist(), 'dist': dist.ravel().tolist(), 'rms_px': float(rms), 'views': len(obj),
           'board': pattern.label,
           'camera': args.camera, 'date': time.strftime('%F %T')}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as handle:
        yaml.safe_dump(out, handle, sort_keys=False)
    print(f'saved {args.out}')
    return 0 if rms <= 1.0 else 2


def cmd_points(args):
    """Marker centres (ids 20-32) in the top view, averaged over several frames, raw and undistorted."""
    with open(args.intrinsics) as handle:
        intr = yaml.safe_load(handle)
    K, dist = np.array(intr['K']), np.array(intr['dist'])
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(DICTIONARY))
    cap = open_camera(args.camera)
    seen, frame = {}, None
    for _ in range(args.frames):
        ok, frame = cap.read()
        corners, ids, _ = detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        for c, i in zip(corners, [] if ids is None else ids.flatten()):
            if int(i) in FIT_IDS + CHECK_IDS:
                seen.setdefault(int(i), []).append(marker_centre(c))
    cap.release()
    rows, vis = [], frame.copy()
    for marker_id in sorted(seen):
        u, v = np.mean(seen[marker_id], axis=0)
        uu, vv = undistort([[u, v]], K, dist)[0]
        rows.append({'id': marker_id, 'u_px': round(float(u), 2), 'v_px': round(float(v), 2),
                     'u_undist_px': round(float(uu), 2), 'v_undist_px': round(float(vv), 2), 'frames': len(seen[marker_id])})
        cv2.drawMarker(vis, (int(u), int(v)), (0, 0, 255), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(vis, str(marker_id), (int(u) + 12, int(v) - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    missing = [i for i in FIT_IDS if i not in seen]
    with open(args.out, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['id', 'u_px', 'v_px', 'u_undist_px', 'v_undist_px', 'frames'])
        writer.writeheader(); writer.writerows(rows)
    cv2.imwrite(args.out.replace('.csv', '.jpg'), vis)
    print(f'found {[r["id"] for r in rows]}; missing fit points {missing}. Saved {args.out} and the image')
    return 1 if missing else 0


def cmd_board(args):
    """A chessboard lying flat on the table instead of point markers: its inner corners in the top view (raw and
    undistorted) with their board coordinates; the image marks the 4 outer corners to touch and 2 check corners."""
    with open(args.intrinsics) as handle:
        intr = yaml.safe_load(handle)
    K, dist = np.array(intr['K']), np.array(intr['dist'])
    cols, rows = (int(v) for v in args.board.lower().split('x'))
    cap = open_camera(args.camera)
    found = []
    for _ in range(args.frames):
        ok, frame = cap.read()
        ok, corners = cv2.findChessboardCornersSB(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (cols, rows),
                                                  cv2.CALIB_CB_EXHAUSTIVE + cv2.CALIB_CB_ACCURACY)
        if ok:
            found.append(corners.reshape(-1, 2))
    cap.release()
    if len(found) < 3:
        sys.exit(f'chessboard {cols}x{rows} not found in the top view ({len(found)} of {args.frames} frames). '
                 f'Lay it flat in the work area, nothing on it, arm folded out of the way')
    if np.ptp(np.stack(found), axis=0).max() > 2.0:
        print('warning: corners moved between frames (board not still?)')
    raw = np.median(np.stack(found), axis=0)
    und = undistort(raw, K, dist)
    touch = {f'c0_0': 0, f'c{cols - 1}_0': cols - 1, f'c0_{rows - 1}': (rows - 1) * cols, f'c{cols - 1}_{rows - 1}': rows * cols - 1}
    check = {f'c{cols // 2}_{rows // 2}': (rows // 2) * cols + cols // 2, f'c{cols // 2 - 2}_{rows // 2 - 1}': (rows // 2 - 1) * cols + cols // 2 - 2}
    vis = frame.copy()
    out_rows = []
    for k, ((u, v), (uu, vv)) in enumerate(zip(raw, und)):
        i, j = k % cols, k // cols
        label = f'c{i}_{j}'
        out_rows.append({'label': label, 'board_x_m': round(i * args.square, 5), 'board_y_m': round(j * args.square, 5),
                         'u_px': round(float(u), 2), 'v_px': round(float(v), 2),
                         'u_undist_px': round(float(uu), 2), 'v_undist_px': round(float(vv), 2)})
        colour = (0, 0, 255) if label in touch else (255, 0, 255) if label in check else (0, 200, 0)
        cv2.circle(vis, (int(u), int(v)), 9 if label in touch or label in check else 4, colour, 2)
        if label in touch or label in check:
            cv2.putText(vis, label, (int(u) + 10, int(v) - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 3)
    with open(args.out, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        writer.writeheader(); writer.writerows(out_rows)
    cv2.imwrite(args.out.replace('.csv', '.jpg'), vis)
    print(f'{len(out_rows)} corners from {len(found)} frames -> {args.out} and the image')
    print('touch (red): ' + ', '.join(touch) + '   check (magenta): ' + ', '.join(check))
    return 0


def cmd_homography(args):
    if args.board_points:
        return homography_from_board(args)
    with open(args.points_px) as handle:
        px = {int(r['id']): (float(r['u_undist_px']), float(r['v_undist_px'])) for r in csv.DictReader(handle)}
    rows = []
    for path in args.arm_points:
        with open(os.path.expanduser(path)) as handle:
            rows += list(csv.DictReader(handle))
    arm = average_arm_points(rows)
    fit = [i for i in FIT_IDS if i in px and i in arm]
    if len(fit) < 6:
        sys.exit(f'only {len(fit)} fit points with both pixel and arm values ({fit}); need 9 (at least 6)')
    for i in fit:
        if arm[i][4] > 5:
            print(f'   warning p{i}: gripper tilted {arm[i][4]:.1f} deg when touched')
    H, err = fit_homography([px[i] for i in fit], [arm[i][:2] for i in fit])
    print('fit points (error mm):  ' + '  '.join(f'p{i} {e:.1f}' for i, e in zip(fit, err)))
    print(f'mean {err.mean():.1f} mm, max {err.max():.1f} mm (target mean <= {MEAN_TARGET_MM})')
    check = [i for i in CHECK_IDS if i in px and i in arm]
    check_err = error_mm(H, [px[i] for i in check], [arm[i][:2] for i in check]) if check else np.array([])
    if check:
        print('check points (error mm): ' + '  '.join(f'p{i} {e:.1f}' for i, e in zip(check, check_err))
              + f'   mean {check_err.mean():.1f} mm')
    else:
        print('no check points yet (ids 29-32): touch 3-4 new points to validate')
    coef, resid = plane_z([arm[i][:3] for i in fit + check])
    print(f'touched heights: z = {coef[0]:+.4f} {coef[1]:+.4f}*x {coef[2]:+.4f}*y  (residual max {abs(resid).max() * 1000:.1f} mm)')
    out = {'H': H.tolist(), 'input': 'undistorted top-view pixels (top_intrinsics.yaml K, dist)', 'output': 'right arm x, y [m]',
           'fit_ids': fit, 'fit_error_mm': {'mean': float(err.mean()), 'max': float(err.max())},
           'check_ids': check, 'check_error_mm': {'mean': float(check_err.mean()), 'max': float(check_err.max())} if check else None,
           'plane_z': {'a': float(coef[0]), 'b': float(coef[1]), 'c': float(coef[2]),
                       'note': 'tool height touching the table, z = a + b x + c y (includes arm sag)'},
           'arm_points': {f'p{i}': [round(float(v), 4) for v in arm[i][:3]] + [int(arm[i][3])] for i in fit + check},
           'date': time.strftime('%F %T')}
    with open(args.out, 'w') as handle:
        yaml.safe_dump(out, handle, sort_keys=False)
    print(f'saved {args.out}')
    worst = max(err.mean(), check_err.mean() if check else 0)
    return 0 if worst <= MEAN_TARGET_MM else 2


def homography_from_board(args):
    """Board corners: touched outer corners fix board -> arm (rigid 2D); every corner then gives a pixel <-> arm pair."""
    with open(args.board_points) as handle:
        corners = {r['label']: r for r in csv.DictReader(handle)}
    rows = []
    for path in args.arm_points:
        with open(os.path.expanduser(path)) as handle:
            rows += list(csv.DictReader(handle))
    touched = {k: v for k, v in average_labelled(rows, 'c').items() if k in corners}
    labels = sorted(touched)
    if args.direct:
        return board_direct(args, corners, touched, labels)
    if args.fit_corners:
        outer = [k for k in labels if k in args.fit_corners]
    else:   # default: the board's four outer corners fix it, every other touched corner is a check
        mi = max(int(k[1:].split('_')[0]) for k in corners); mj = max(int(k.split('_')[1]) for k in corners)
        outer = [k for k in labels if k in (f'c0_0', f'c{mi}_0', f'c0_{mj}', f'c{mi}_{mj}')]
    checks = [k for k in labels if k not in outer]
    if len(outer) < 3:
        sys.exit(f'need at least 3 touched corners (teleop here c0_0 ...), have {labels}')
    for k in labels:
        if touched[k][4] > 5:
            print(f'   warning {k}: gripper tilted {touched[k][4]:.1f} deg when touched')
    board_xy = lambda k: (float(corners[k]['board_x_m']), float(corners[k]['board_y_m']))  # noqa: E731
    R, t, resid = fit_rigid_2d([board_xy(k) for k in outer], [touched[k][:2] for k in outer])
    print('touched corners (board -> arm residual mm): ' + '  '.join(f'{k} {r * 1000:.1f}' for k, r in zip(outer, resid)))
    px = np.float32([(float(r['u_undist_px']), float(r['v_undist_px'])) for r in corners.values()])
    arm = np.float32([R @ np.array(board_xy(k)) + t for k in corners])
    H, err = fit_homography(px, arm)
    print(f'homography from {len(px)} corners: mean {err.mean():.2f} mm, max {err.max():.2f} mm (pixel noise + flatness)')
    check_err = np.array([])
    if checks:
        cpx = [(float(corners[k]['u_undist_px']), float(corners[k]['v_undist_px'])) for k in checks]
        check_err = error_mm(H, cpx, [touched[k][:2] for k in checks])
        print('check corners (camera vs touched, mm): ' + '  '.join(f'{k} {e:.1f}' for k, e in zip(checks, check_err))
              + f'   mean {check_err.mean():.1f}')
    else:
        print('no check corners touched yet (e.g. the magenta ones in board_points_px.jpg)')
    coef, zres = plane_z([touched[k][:3] for k in labels])
    print(f'touched heights: z = {coef[0]:+.4f} {coef[1]:+.4f}*x {coef[2]:+.4f}*y  (residual max {abs(zres).max() * 1000:.1f} mm)')
    out = {'H': H.tolist(), 'input': 'undistorted top-view pixels (top_intrinsics.yaml K, dist)', 'output': 'right arm x, y [m]',
           'method': f'chessboard on the table, {len(outer)} touched corners -> rigid board->arm, {len(px)} corners',
           'touch_residual_mm': {'mean': float(resid.mean() * 1000), 'max': float(resid.max() * 1000)},
           'fit_error_mm': {'mean': float(err.mean()), 'max': float(err.max())},
           'check_error_mm': {'mean': float(check_err.mean()), 'max': float(check_err.max())} if checks else None,
           'plane_z': {'a': float(coef[0]), 'b': float(coef[1]), 'c': float(coef[2]),
                       'note': 'tool height touching the board, z = a + b x + c y (includes arm sag)'},
           'touched': {k: [round(float(v), 4) for v in touched[k][:3]] + [int(touched[k][3])] for k in labels},
           'date': time.strftime('%F %T')}
    with open(args.out, 'w') as handle:
        yaml.safe_dump(out, handle, sort_keys=False)
    print(f'saved {args.out}')
    worst = max(resid.mean() * 1000, check_err.mean() if checks else 0)
    return 0 if worst <= MEAN_TARGET_MM else 2


def board_direct(args, corners, touched, labels):
    """Each touched corner is a pixel <-> arm (FK) pair, as in the guide's 9-point method: the board only marks exact
    points. The arm's own FK error at long reach is then inside H, so a later pick commanded in FK lands right."""
    checks = [k for k in labels if args.check_corners and k in args.check_corners]
    fit = [k for k in labels if k not in checks]
    if len(fit) < 4:
        sys.exit(f'need at least 4 touched corners for the fit, have {fit}')
    pix = lambda ks: [(float(corners[k]['u_undist_px']), float(corners[k]['v_undist_px'])) for k in ks]  # noqa: E731
    H, err = fit_homography(pix(fit), [touched[k][:2] for k in fit])
    print('fit corners (error mm): ' + '  '.join(f'{k} {e:.1f}' for k, e in zip(fit, err)) + f'   mean {err.mean():.1f}')
    if len(fit) == 4:
        print('   (4 points fix a homography exactly: the fit error is 0 by construction; add points or check corners)')
    check_err = error_mm(H, pix(checks), [touched[k][:2] for k in checks]) if checks else np.array([])
    if checks:
        print('check corners (mm): ' + '  '.join(f'{k} {e:.1f}' for k, e in zip(checks, check_err)) + f'   mean {check_err.mean():.1f}')
    coef, zres = plane_z([touched[k][:3] for k in labels])
    print(f'touched heights: z = {coef[0]:+.4f} {coef[1]:+.4f}*x {coef[2]:+.4f}*y  (residual max {abs(zres).max() * 1000:.1f} mm)')
    out = {'H': H.tolist(), 'input': 'undistorted top-view pixels (top_intrinsics.yaml K, dist)', 'output': 'right arm x, y [m] (FK)',
           'method': f'chessboard corners as points, direct pixel <-> FK pairs, {len(fit)} fit + {len(checks)} check',
           'fit_ids': fit, 'fit_error_mm': {'mean': float(err.mean()), 'max': float(err.max())},
           'check_ids': checks, 'check_error_mm': {'mean': float(check_err.mean()), 'max': float(check_err.max())} if checks else None,
           'plane_z': {'a': float(coef[0]), 'b': float(coef[1]), 'c': float(coef[2]),
                       'note': 'tool height touching the board, z = a + b x + c y (includes arm sag)'},
           'touched': {k: [round(float(v), 4) for v in touched[k][:3]] + [int(touched[k][3])] for k in labels},
           'date': time.strftime('%F %T')}
    with open(args.out, 'w') as handle:
        yaml.safe_dump(out, handle, sort_keys=False)
    print(f'saved {args.out}')
    worst = max(err.mean(), check_err.mean() if checks else 0)
    return 0 if worst <= MEAN_TARGET_MM else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'intrinsics'):
        p = sub.add_parser(name)
        p.add_argument('--pattern', choices=['charuco', 'chessboard'], default='charuco')
        p.add_argument('--board', default='9x6', help='chessboard inner corners, cols x rows')
        p.add_argument('--squares', type=int, nargs=2, default=[7, 5], help='ChArUco squares')
        p.add_argument('--square', type=float, default=0.030, help='measured square side, m')
        p.add_argument('--marker', type=float, default=0.022, help='measured marker side, m')
        p.add_argument('--camera', default=CAMERA)
    sub.choices['capture'].add_argument('--out', default=os.path.join(CALIB_DIR, 'intrinsics_views'))
    sub.choices['intrinsics'].add_argument('--images', default=os.path.join(CALIB_DIR, 'intrinsics_views'))
    sub.choices['intrinsics'].add_argument('--out', default=os.path.join(CALIB_DIR, 'top_intrinsics.yaml'))
    p = sub.add_parser('points')
    p.add_argument('--camera', default=CAMERA)
    p.add_argument('--intrinsics', default=os.path.join(CALIB_DIR, 'top_intrinsics.yaml'))
    p.add_argument('--frames', type=int, default=15)
    p.add_argument('--out', default=os.path.join(CALIB_DIR, 'table_points_px.csv'))
    p = sub.add_parser('board', help='chessboard flat on the table instead of point markers')
    p.add_argument('--board', default='9x6')
    p.add_argument('--square', type=float, default=0.023, help='measured square side, m')
    p.add_argument('--camera', default=CAMERA)
    p.add_argument('--intrinsics', default=os.path.join(CALIB_DIR, 'top_intrinsics.yaml'))
    p.add_argument('--frames', type=int, default=10)
    p.add_argument('--out', default=os.path.join(CALIB_DIR, 'board_points_px.csv'))
    p = sub.add_parser('homography')
    p.add_argument('--board-points', help='board_points_px.csv from `board` (chessboard mode)')
    p.add_argument('--direct', action='store_true', help='board mode: fit H on touched corners directly (pixel <-> FK)')
    p.add_argument('--check-corners', nargs='+', help='--direct: touched corners kept out of the fit')
    p.add_argument('--fit-corners', nargs='+', help='touched corners used for the board->arm fit (default: the 4 outer '
                   'corners; every other touched corner is a check)')
    p.add_argument('--points-px', default=os.path.join(CALIB_DIR, 'table_points_px.csv'))
    p.add_argument('--arm-points', nargs='+', required=True, help='teleop points.csv file(s): labels p20..p32, or c<i>_<j>')
    p.add_argument('--out', default=os.path.join(CALIB_DIR, 'top_homography.yaml'))
    args = parser.parse_args(argv)
    os.makedirs(CALIB_DIR, exist_ok=True)
    return {'capture': cmd_capture, 'intrinsics': cmd_intrinsics, 'points': cmd_points, 'board': cmd_board,
            'homography': cmd_homography}[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
