"""Marker <-> robot calibration: where are the ArUco markers in the robot frame?

The marker *layout* (distances between marker centers, measured with a ruler) is
taken from the current `marker_positions`; what is unknown is how that rectangle sits
relative to the robot base. The robot itself places one block at several known
positions (its own IK frame); vla_perception reports where it sees the block in the
marker frame; a 2D rigid transform (rotation + translation, optionally scale) between
the two point sets is fitted and applied to the markers. Fitting 3 parameters over the
whole working area is far better conditioned than a free homography extrapolated to
the markers. The robot's own systematic placement offset is absorbed too, so later
picks aim where the robot actually puts things.

Needs the full stack running (move_group, controllers, camera, vla_perception) with
nothing else on the table except the calibration block, and the executor idle:

  ros2 run vla_calibration table --color red --start 0.16 0.0

The arm opens above the start point and asks you to put the block under the fingers
(skip with --yes if it is already there).
"""
import argparse
import os
import sys
import time

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.parameter import Parameter

from vla_calibration.common import (DEFAULT_CALIB_DIR, apply_param_files, param_overrides, spin_in_background,
                                    to_list, update_param_file)
from vla_executor.executor_node import GraspError, PickPlaceExecutor
from vla_interfaces.action import PickPlace
from vla_interfaces.msg import BlockArray

DEFAULT_POINTS = [(0.13, 0.10), (0.13, -0.10), (0.20, 0.12), (0.20, -0.12),
                  (0.235, 0.0), (0.16, 0.0), (0.22, 0.06), (0.22, -0.06),
                  (0.15, 0.06), (0.15, -0.06), (0.18, 0.10), (0.18, -0.10)]


def wrap_yaw(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def base_from_fit(T, base):
    """True arm base pose from the fit T (seen -> commanded) and the assumed base (x, y, yaw).

    The robot lands a command c at seen = T^-1(c), so the true base is T^-1 of the assumed one.
    """
    s, R, t = T
    bx, by, byaw = base
    p = (R.T @ (np.array([bx, by]) - t)) / s
    return float(p[0]), float(p[1]), float(wrap_yaw(byaw - np.arctan2(R[1, 0], R[0, 0])))


def fit_rigid(src, dst, scale=False):
    """Least-squares 2D similarity/rigid transform dst ~ s R src + t (Umeyama)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    a, b = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(b.T @ a)
    D = np.diag([1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum()) if scale else 1.0
    t = mu_d - s * R @ mu_s
    return s, R, t


def apply_rigid(T, pts):
    s, R, t = T
    return (s * (R @ np.asarray(pts, float).T)).T + t


def robust_fit(src, dst, scale=False, max_drop=0.25, min_err=0.005, k=2.5):
    """Fit, then repeatedly drop the worst point while it is an outlier
    (> k x median residual and > min_err), up to max_drop of the points."""
    keep = np.arange(len(src))
    while True:
        T = fit_rigid(src[keep], dst[keep], scale)
        r = np.linalg.norm(apply_rigid(T, src[keep]) - dst[keep], axis=1)
        worst = int(np.argmax(r))
        if (len(keep) - 1 < max(3, int(np.ceil((1 - max_drop) * len(src))))
                or r[worst] <= max(min_err, k * np.median(r))):
            return T, keep
        keep = np.delete(keep, worst)


def leave_one_out(src, dst, scale=False):
    errs = []
    for i in range(len(src)):
        keep = [j for j in range(len(src)) if j != i]
        T = fit_rigid(src[keep], dst[keep], scale)
        errs.append(float(np.linalg.norm(apply_rigid(T, src[i:i + 1])[0] - dst[i])))
    return errs


class TableCalibrator(PickPlaceExecutor):

    def __init__(self, overrides=()):
        # use_sim_time, arm_names, ... come from the executor config
        super().__init__(node_name='vla_calib_table', serve=False, parameter_overrides=list(overrides))
        self.blocks = None
        self.blocks_stamp = 0.0
        self.create_subscription(BlockArray, '/vla/blocks', self._on_blocks, 10)

    def _on_blocks(self, m):
        self.blocks, self.blocks_stamp = m, time.monotonic()

    def observe_block(self, color, frames=6, timeout=6.0):
        """Mean (x, y) in the current marker frame and yaw of the single `color` block."""
        t0 = time.monotonic()
        seen, last = [], 0.0
        deadline = t0 + timeout
        while len(seen) < frames and time.monotonic() < deadline:
            if self.blocks_stamp > max(t0, last):
                last = self.blocks_stamp
                bs = [b for b in self.blocks.blocks if b.color == color]
                if len(bs) > 1:
                    raise RuntimeError(f'{len(bs)} {color} blocks visible - leave only the calibration block')
                if bs:
                    seen.append((bs[0].x, bs[0].y, np.cos(4 * bs[0].yaw), np.sin(4 * bs[0].yaw)))
            time.sleep(0.02)
        if len(seen) < frames // 2:
            raise RuntimeError(f'{color} block not detected by vla_perception')
        m = np.mean(seen, axis=0)
        return m[:2], float(np.arctan2(m[3], m[2]) / 4.0)   # square block: yaw is 90-deg periodic


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--color', default='red', help='color of the calibration block')
    ap.add_argument('--arm', default='',
                    help='two-arm setup: calibrate this arm\'s base pose (left/right) instead of the markers')
    ap.add_argument('--start', type=float, nargs=2, default=None, metavar=('X', 'Y'),
                    help='where the block starts (default: 0.16 m in front of the arm base)')
    ap.add_argument('--points', type=float, nargs='+',
                    help='x1 y1 x2 y2 ... relative to the arm base (default: 12-point grid)')
    ap.add_argument('--fit-scale', action='store_true',
                    help='also fit a uniform scale (if the measured marker layout may be off)')
    ap.add_argument('--no-wrist-check', action='store_true',
                    help='turn the wrist grasp check off (e.g. before the wrist calibration exists)')
    ap.add_argument('--max-drift', type=float, default=0.03,
                    help='drop a point whose block landed farther than this from the command, '
                         'judged with the current marker calibration [m]')
    ap.add_argument('--yes', action='store_true', help='block is already at --start, do not prompt')
    ap.add_argument('--executor-config', nargs='*', default=[
        os.path.join(get_package_share_directory('vla_executor'), 'config', 'executor.yaml')])
    ap.add_argument('--perception-config', default=os.path.join(
        get_package_share_directory('vla_perception'), 'config', 'perception_sim.yaml'),
        help='params file whose marker_positions vla_perception is running with (the layout)')
    ap.add_argument('--out', default=None,
                    help='default: calib/table.yaml (markers) or calib/arm_poses.yaml (--arm)')
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])
    rel = DEFAULT_POINTS if not args.points else list(zip(args.points[0::2], args.points[1::2]))
    out_path = args.out or os.path.join(DEFAULT_CALIB_DIR, 'arm_poses.yaml' if args.arm else 'table.yaml')

    with open(args.perception_config) as f:
        pp = yaml.safe_load(f)['vla_perception']['ros__parameters']
    marker_ids = list(pp.get('marker_ids', [0, 1, 2, 3]))
    layout = np.array(pp['marker_positions'], float).reshape(-1, 2)

    rclpy.init(args=argv)
    node = TableCalibrator(param_overrides(args.executor_config, 'vla_executor'))
    apply_param_files(node, args.executor_config, 'vla_executor')
    node.set_parameters([Parameter('wrist_check', value=not args.no_wrist_check)])
    spin_in_background(node)
    log = node.get_logger()
    arm = node.arm(args.arm or None)
    bx, by, _, byaw = node.arm_base(arm)

    def from_base(px, py):        # point relative to the arm base -> input frame
        c, s_ = np.cos(byaw), np.sin(byaw)
        return (float(bx + c * px - s_ * py), float(by + s_ * px + c * py))

    pts = [from_base(*q) for q in rel]
    start = tuple(args.start) if args.start else from_base(0.16, 0.0)

    if not args.yes:
        sx, sy = start
        node.gripper(node.prm('gripper_open'), 'open', arm)
        node.move_joints(node.ik_or_fail(sx, sy, node.prm('grasp_z') + node.prm('approach_height'), 0.0,
                                         'start', arm), 'start', arm)
        input(f'Put the {args.color} block on the table right under the open fingers '
              f'({sx:.3f}, {sy:.3f}), clear everything else, then press Enter... ')

    seen, cmd = [], []
    cur, cur_yaw = start, 0.0
    try:
        for i, (x, y) in enumerate(pts):
            log.info(f'point {i + 1}/{len(pts)}: place at ({x:.3f}, {y:.3f})')
            for attempt in (1, 2):
                try:
                    node.run_pick_place(PickPlace.Goal(arm=args.arm, pick_x=cur[0], pick_y=cur[1],
                                                       pick_yaw=cur_yaw, pick_color=args.color,
                                                       place_x=x, place_y=y))
                    break
                except GraspError as e:
                    # missed (block slipped or rotated): look again and retry from where it is
                    log.warn(f'  {e}; retrying from the observed position')
                    node.recover(arm)
                    time.sleep(0.5)
                    xy, cur_yaw = node.observe_block(args.color)
                    cur = (float(xy[0]), float(xy[1]))
                    if attempt == 2:
                        raise
            time.sleep(0.5)
            xy, cur_yaw = node.observe_block(args.color)      # blocks rotate a bit when placed
            drift = float(np.hypot(xy[0] - x, xy[1] - y))
            log.info(f'  seen at ({xy[0]:.3f}, {xy[1]:.3f}) in the current marker frame '
                     f'({drift * 1000:.1f} mm from the command)')
            if drift > args.max_drift:
                # the block slipped or was knocked: commanded != actual, keep it out of the fit
                # and pick it up where the camera sees it
                log.warn(f'  point dropped (> {args.max_drift * 1000:.0f} mm)')
                cur = (float(xy[0]), float(xy[1]))
                continue
            seen.append(xy)
            cmd.append((x, y))
            cur = (x, y)
    except Exception as e:  # noqa: BLE001
        log.error(f'calibration run stopped: {e}')
        try:
            node.recover(arm)
        except Exception:  # noqa: BLE001
            pass
        if len(seen) < 3:
            rclpy.shutdown()
            return 1
        log.warn(f'fitting with the {len(seen)} points collected so far')

    seen, cmd = np.array(seen), np.array(cmd)
    T, keep = robust_fit(seen, cmd, args.fit_scale)
    dropped = [tuple(np.round(cmd[i], 3)) for i in range(len(cmd)) if i not in keep]
    seen, cmd = seen[keep], cmd[keep]
    resid = np.linalg.norm(apply_rigid(T, seen) - cmd, axis=1) * 1000
    loo = np.array(leave_one_out(seen, cmd, args.fit_scale)) * 1000 if len(seen) > 3 else np.array([np.nan])
    before = np.linalg.norm(seen - cmd, axis=1) * 1000
    if dropped:
        print(f'\noutliers left out of the fit: {dropped}')
    new = apply_rigid(T, layout)
    s, R, t = T

    print(f'\npoints: {len(seen)}   error before {before.mean():.1f} mm (max {before.max():.1f})   '
          f'after: fit {resid.mean():.1f} mm (max {resid.max():.1f}), '
          f'leave-one-out {np.nanmean(loo):.1f} mm (max {np.nanmax(loo):.1f})')
    print(f'transform: rotation {np.degrees(np.arctan2(R[1, 0], R[0, 0])):+.2f} deg   '
          f'translation ({t[0] * 1000:+.1f}, {t[1] * 1000:+.1f}) mm' + (f'   scale {s:.4f}' if args.fit_scale else ''))
    if args.arm:
        # markers stay put; the arm is where the fit says it is. The robot lands a command c at
        # seen = T^-1(c), so its true base pose is T^-1 applied to the assumed one.
        px_, py_, pyaw = base_from_fit(T, (bx, by, byaw))
        pose = {'x': round(px_, 4), 'y': round(py_, 4), 'yaw': round(pyaw, 4)}
        print(f'  {args.arm} arm base: ({pose["x"]:.4f}, {pose["y"]:.4f}) yaw {np.degrees(pose["yaw"]):+.2f} deg   '
              f'was ({bx:.4f}, {by:.4f}) yaw {np.degrees(byaw):+.2f} deg  '
              f'moved {np.hypot(pose["x"] - bx, pose["y"] - by) * 1000:.1f} mm')
        data = {}
        if os.path.exists(out_path):
            with open(out_path) as f:
                data = yaml.safe_load(f) or {}
        data[args.arm] = pose
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, 'w') as f:
            yaml.safe_dump(data, f, sort_keys=True)
    else:
        for k, i in enumerate(marker_ids):
            print(f'  marker {i}: ({new[k][0]:.4f}, {new[k][1]:.4f})   was ({layout[k][0]:.4f}, {layout[k][1]:.4f})  '
                  f'moved {np.linalg.norm(new[k] - layout[k]) * 1000:.1f} mm')
        update_param_file(out_path, {'vla_perception': {'marker_ids': marker_ids,
                                                        'marker_positions': to_list(new, 4)}})
    print(f'written: {out_path}')
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
