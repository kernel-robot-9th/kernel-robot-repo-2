"""Refine the top-camera homography with the wrist camera, on the real arm.

The 2026-10-22 table homography and board height came from corners touched with the leader arm (tool tilted
up to 14 deg, the arm sagging more the further it reaches); picks with the tool vertical landed ~3 cm short
and ~1.5 cm low. Here the arm itself finds where each green block really is, tool vertical:
  - height: the green 2.5 cm cube's size in the wrist image gives the camera distance, so the tool's real height
    above the grasp pose (calib/wrist_descent.yaml, from the 2026-10-22 successful grasp video)
  - x, y: probe moves measure the image Jacobian; the arm moves until the block sits where that video had it at
    the same real height (the camera looks down at an angle: a height error alone would shift the block in v)
The centred (x, y) paired with the top camera's (x, y) refits the table mapping (affine correction on H), and the
height errors refit the surface plane. Both go to calib/top_homography.yaml (the old file is kept beside it).

  ros2 launch vla_bringup real_vla.launch.py fold_on_start:=true      # cameras, follower, perception
  ros2 run vla_calibration wrist_refine measure     # every visible block; move them, repeat (6-9 points)
  ros2 run vla_calibration wrist_refine fit         # -> calib/top_homography.yaml
"""
import argparse
import csv
import os
import shutil
import sys
import time

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory

from vla_calibration.common import DEFAULT_CALIB_DIR, apply_param_files, param_overrides, spin_in_background, wait_for
from vla_executor.executor_node import PickPlaceExecutor
from vla_interfaces.msg import BlockArray

POINTS = os.path.join(DEFAULT_CALIB_DIR, 'wrist_points.csv')
FIELDS = ['time', 'id', 'color', 'top_x', 'top_y', 'u', 'v', 'arm_x', 'arm_y', 'h_cmd', 'h_real', 'surface_z']
GRASP_Z = 0.0125      # the reference grasp: tool at the block's mid height above the surface plane


def fit_affine(src, dst):
    """Least-squares 2D affine A (2x3) with dst ~ A [src, 1]. [출력] A, residuals [m] per point."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    X = np.column_stack([src, np.ones(len(src))])
    A = np.linalg.lstsq(X, dst, rcond=None)[0].T
    return A, np.linalg.norm(X @ A.T - dst, axis=1)


def fit_plane(xy, dz):
    """Least-squares dz ~ a + b x + c y (a constant only for fewer than 3 points). [출력] (a, b, c)."""
    xy, dz = np.asarray(xy, float), np.asarray(dz, float)
    if len(dz) < 3:
        return float(dz.mean()), 0.0, 0.0
    a, b, c = np.linalg.lstsq(np.column_stack([np.ones(len(dz)), xy]), dz, rcond=None)[0]
    return float(a), float(b), float(c)


class Descent:
    """Reference wrist view of a block straight below the tool, by tool height (calib/wrist_descent.yaml)."""

    def __init__(self, path):
        with open(path) as handle:
            d = yaml.safe_load(handle)
        rows = np.array(d['rows'], float)
        self.rows = rows[np.argsort(rows[:, 1])]          # by size
        self.k, self.d0 = d['size_model']['k'], d['size_model']['d0']

    def height(self, size):
        return self.k / size - self.d0

    def ref(self, size):
        """(u, v) of a centred block that looks `size` px large."""
        return (float(np.interp(size, self.rows[:, 1], self.rows[:, 2])),
                float(np.interp(size, self.rows[:, 1], self.rows[:, 3])))


def cut_side(bgr, hsv_ranges):
    """'top' / 'bottom' / 'side' when the largest colour blob touches that image border, else None."""
    import cv2
    from vla_executor.grasp_check import color_mask
    mask = cv2.morphologyEx(color_mask(bgr, hsv_ranges), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours = [c for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
                if cv2.contourArea(c) >= 300]
    if not contours:
        return None
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    if y <= 1:
        return 'top'
    if y + h >= mask.shape[0] - 1:
        return 'bottom'
    return 'side' if x <= 1 or x + w >= mask.shape[1] - 1 else None


def block_view(bgr, hsv_ranges, near):
    """(u, v, size) of the colour blob nearest `near` (size = mean minAreaRect side), or None."""
    import cv2
    from vla_executor.grasp_check import color_mask
    mask = cv2.morphologyEx(color_mask(bgr, hsv_ranges), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    best = None
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(contour) < 800:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if y <= 1 or y + h >= mask.shape[0] - 1 or x <= 1 or x + w >= mask.shape[1] - 1:
            continue                                     # cut by the image border: centre and size are wrong
        (u, v), (a, b), _ = cv2.minAreaRect(contour)
        key = np.hypot(u - near[0], v - near[1])
        if best is None or key < best[0]:
            best = (key, (u, v, (a + b) / 2))
    return None if best is None else best[1]


def refined_homography(H, A):
    """H (pixel -> table) followed by the affine correction A."""
    return np.vstack([A, [0.0, 0.0, 1.0]]) @ np.asarray(H, float)


class WristRefiner(PickPlaceExecutor):

    def __init__(self, overrides=()):
        super().__init__(node_name='vla_calib_wrist_refine', serve=False, parameter_overrides=list(overrides))
        self.blocks = None
        self.create_subscription(BlockArray, '/vla/blocks', lambda m: setattr(self, 'blocks', m), 10)


def measure(args):
    rclpy.init()
    configs = [os.path.join(get_package_share_directory('vla_executor'), 'config', 'executor_real.yaml')]
    node = WristRefiner(param_overrides(configs, 'vla_executor'))
    apply_param_files(node, configs, 'vla_executor')
    spin_in_background(node)
    log = node.get_logger()
    descent = Descent(os.path.join(args.calib_dir, 'wrist_descent.yaml'))
    msg = wait_for(lambda: node.blocks if node.blocks and node.blocks.blocks else None, 15.0)
    if msg is None:
        log.error('no blocks on /vla/blocks (is perception running?)')
        rclpy.shutdown()
        return 1
    blocks = [b for b in msg.blocks if b.kind == 'block' and b.color == args.color]
    hsv = node.hsv_ranges()[args.color]
    arm = node.arm(None)
    plane = node.prm('surface_plane')
    rows = []
    dbg = os.path.join(os.path.expanduser('~/.cache/vla_executor'), 'refine-' + time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(dbg, exist_ok=True)

    last = {}

    def view(x, y, yaw, label):
        node.move_joints(node.ik_or_fail(x, y, GRASP_Z + args.height, yaw, label, arm), label, arm)
        img = node.latest_wrist_image(after=time.monotonic() + 0.5, timeout=3.0, arm=arm)
        if img is None:
            raise RuntimeError('no wrist image')
        import cv2
        last['img'] = img
        c = block_view(img, hsv, (320, 240))
        mark = img.copy()
        if c is not None:
            r = descent.ref(c[2])
            cv2.drawMarker(mark, (int(r[0]), int(r[1])), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
            cv2.circle(mark, (int(c[0]), int(c[1])), 8, (0, 255, 255), 2)
        cv2.putText(mark, f'{label}: {c and tuple(round(v) for v in c)}', (8, 24), 0, 0.6, (0, 255, 255), 2)
        cv2.imwrite(os.path.join(dbg, f'{time.strftime("%H%M%S")}_{label.replace(" ", "_")}.jpg'), mark)
        return c

    try:
        node.gripper(node.prm('gripper_open'), 'open', arm)
        for b in blocks:
            x, y, yaw = b.x, b.y, b.yaw
            r = float(np.hypot(x, y))
            ux, uy = x / r, y / r                     # radial: the wrist image's v axis (the camera turns with joint1)
            x, y = x + args.look_ahead * ux, y + args.look_ahead * uy
            try:
                try:                                  # approach from above where that is in reach
                    node.move_joints(node.approach_ik(x, y, GRASP_Z + args.height, yaw, 'above', arm), 'above', arm)
                except RuntimeError as e:
                    log.info(f'{b.id}: {e}; going straight to the look pose')
                c = view(x, y, yaw, 'look')
                for _ in range(4):                    # cut by the top/bottom edge: step out/in 1 cm until whole
                    if c is not None:
                        break
                    side = cut_side(last['img'], hsv)
                    if side not in ('top', 'bottom'):
                        raise RuntimeError(f'block not in the wrist image ({side or "not seen"})')
                    step = 0.01 if side == 'top' else -0.01
                    x, y = x + step * ux, y + step * uy
                    c = view(x, y, yaw, f'search {side}')
                if c is None:
                    raise RuntimeError('block not found in the wrist image')
                p = args.probe
                cx = view(x + p, y, yaw, 'probe x')
                cy = view(x, y + p, yaw, 'probe y')
                if cx is None or cy is None:
                    raise RuntimeError('block lost in a probe move')
                J = np.column_stack([np.subtract(cx[:2], c[:2]) / p, np.subtract(cy[:2], c[:2]) / p])
                ok = False
                for _ in range(args.iters):
                    ref = descent.ref(c[2])
                    err = np.subtract(ref, c[:2])
                    log.info(f'{b.id}: block ({c[0]:.0f}, {c[1]:.0f}) {c[2]:.0f} px, ref ({ref[0]:.0f}, {ref[1]:.0f}),'
                             f' {np.hypot(*err):.0f} px off, real height {descent.height(c[2]) * 1000:.0f} mm')
                    if np.hypot(*err) <= args.tol:
                        ok = True
                        break
                    d = np.linalg.solve(J, err)
                    n = float(np.hypot(*d))
                    if n > 0.03:
                        d *= 0.03 / n
                    x, y = x + d[0], y + d[1]
                    c = view(x, y, yaw, 'shift')
                    if c is None:
                        raise RuntimeError('block lost after a shift')
            except (RuntimeError, np.linalg.LinAlgError) as e:
                log.warn(f'{b.id}: {e}')
                continue
            finally:
                try:
                    node.move_joints(node.approach_ik(x, y, GRASP_Z + args.height, yaw, 'up', arm), 'up', arm)
                except RuntimeError:
                    pass
            if not ok:
                log.warn(f'{b.id}: not centred, point dropped')
                continue
            h_real = descent.height(c[2])
            surface = plane[0] + plane[1] * x + plane[2] * y
            log.info(f'{b.id}: top camera ({b.x:.3f}, {b.y:.3f}) -> arm ({x:.3f}, {y:.3f}), '
                     f'{np.hypot(x - b.x, y - b.y) * 1000:.0f} mm apart; height {args.height * 1000:.0f} mm commanded, '
                     f'{h_real * 1000:.0f} mm real')
            rows.append({'time': time.strftime('%F %T'), 'id': b.id, 'color': b.color, 'top_x': round(b.x, 4),
                         'top_y': round(b.y, 4), 'u': b.u, 'v': b.v, 'arm_x': round(x, 4), 'arm_y': round(y, 4),
                         'h_cmd': args.height, 'h_real': round(h_real, 4), 'surface_z': round(surface, 4)})
    finally:
        node.go_observe(arm)
        rclpy.shutdown()
    new = not os.path.exists(args.points)
    with open(args.points, 'a', newline='') as handle:
        w = csv.DictWriter(handle, FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} of {len(blocks)} {args.color} blocks measured -> {args.points} (views: {dbg})')
    return 0 if rows else 1


def fit(args):
    with open(args.points) as handle:
        pts = list(csv.DictReader(handle))
    if len(pts) < 4:
        print(f'{len(pts)} points in {args.points}: need at least 4 (move the blocks and measure again)')
        return 1
    src = [(float(p['top_x']), float(p['top_y'])) for p in pts]
    dst = [(float(p['arm_x']), float(p['arm_y'])) for p in pts]
    A, res = fit_affine(src, dst)
    before = np.linalg.norm(np.subtract(src, dst), axis=1)
    for p, b, r in zip(pts, before, res):
        print(f"  {p['id']:8s} top ({float(p['top_x']):.3f}, {float(p['top_y']):.3f}) arm ({float(p['arm_x']):.3f}, "
              f"{float(p['arm_y']):.3f}): {b * 1000:5.1f} mm before, {r * 1000:4.1f} mm after")
    print(f'mean {before.mean() * 1000:.1f} -> {res.mean() * 1000:.1f} mm, max {before.max() * 1000:.1f} -> '
          f'{res.max() * 1000:.1f} mm\nA = {np.round(A, 4).tolist()}')
    # the arm sat (h_cmd - h_real) lower than the plane model says: raise the surface by that much
    xy = [(float(p['arm_x']), float(p['arm_y'])) for p in pts]
    dz = [float(p['h_cmd']) - float(p['h_real']) for p in pts]
    old = [float(p['surface_z']) for p in pts]
    pa, pb, pc = fit_plane(xy, np.add(old, dz))
    for p, z in zip(pts, dz):
        print(f"  {p['id']:8s} height error {z * 1000:+5.1f} mm (arm lower than the model when +)")
    print(f'surface plane z = {pa:+.4f} {pb:+.4f} x {pc:+.4f} y  (executor surface_plane, base frame)')
    path = os.path.join(args.calib_dir, 'top_homography.yaml')
    with open(path) as handle:
        homo = yaml.safe_load(handle)
    if args.dry_run:
        return 0
    backup = path.replace('.yaml', f'_{time.strftime("%Y%m%d-%H%M%S")}.yaml')
    shutil.copy(path, backup)
    homo['H'] = refined_homography(homo['H'], A).tolist()
    homo['wrist_refine'] = {'points': len(pts), 'affine': np.round(A, 6).tolist(),
                            'error_mm_before': round(float(before.mean() * 1000), 1),
                            'error_mm_after': round(float(res.mean() * 1000), 1),
                            'max_error_mm_after': round(float(res.max() * 1000), 1),
                            'date': time.strftime('%F %T'), 'previous': os.path.basename(backup)}
    homo['plane_z'] = {'a': pa, 'b': pb, 'c': pc, 'note': 'surface for the grasp reference (green cube mid at +0.0125), '
                       'from wrist_refine: tool vertical, sag included'}
    with open(path, 'w') as handle:
        yaml.safe_dump(homo, handle, sort_keys=False)
    print(f'wrote {path} (previous: {backup}); restart perception to use it')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('measure', help='centre the wrist camera on every visible green block, append the points')
    m.add_argument('--color', default='green', help='a 2.5 cm cube of this colour (its size is the height gauge)')
    m.add_argument('--height', type=float, default=0.02, help='commanded tool height above the grasp pose [m]')
    m.add_argument('--probe', type=float, default=0.005)
    m.add_argument('--look-ahead', type=float, default=0.02, help='first look this far beyond the block [m]')
    m.add_argument('--iters', type=int, default=5)
    m.add_argument('--tol', type=float, default=10.0, help='px')
    f = sub.add_parser('fit', help='fit the correction and rewrite top_homography.yaml')
    f.add_argument('--dry-run', action='store_true', help='print the fit, write nothing')
    for p in (m, f):
        p.add_argument('--points', default=POINTS)
        p.add_argument('--calib-dir', default=DEFAULT_CALIB_DIR)
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])
    return measure(args) if args.cmd == 'measure' else fit(args)


if __name__ == '__main__':
    sys.exit(main())
