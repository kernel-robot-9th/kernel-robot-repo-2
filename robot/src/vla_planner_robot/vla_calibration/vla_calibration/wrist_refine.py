"""Refine the top-camera homography with the wrist camera, on the real arm.

The 2026-10-22 table homography came from corners touched with the leader arm (tool tilted up to 14 deg);
picks with the tool vertical landed ~3 cm short. Here the arm itself finds where each block really is:
it looks down at the block with the tool vertical and centres the wrist camera on it (`center_on_block`,
reference pixel from the 2026-10-22 successful grasp). The centred tool (x, y) paired with what the top
camera reports for that block refits the table mapping: an affine correction A on top of H (least squares),
written back to calib/top_homography.yaml (the old file is kept beside it).

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
from types import SimpleNamespace

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.parameter import Parameter

from vla_calibration.common import DEFAULT_CALIB_DIR, apply_param_files, param_overrides, spin_in_background, wait_for
from vla_executor.executor_node import PickPlaceExecutor
from vla_interfaces.msg import BlockArray

POINTS = os.path.join(DEFAULT_CALIB_DIR, 'wrist_points.csv')
FIELDS = ['time', 'id', 'color', 'top_x', 'top_y', 'u', 'v', 'arm_x', 'arm_y']


def fit_affine(src, dst):
    """Least-squares 2D affine A (2x3) with dst ~ A [src, 1]. [출력] A, residuals [m] per point."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    X = np.column_stack([src, np.ones(len(src))])
    A = np.linalg.lstsq(X, dst, rcond=None)[0].T
    return A, np.linalg.norm(X @ A.T - dst, axis=1)


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
    node.set_parameters([Parameter('wrist_center_offset', value=[0.0, 0.0]),
                         Parameter('wrist_center_shift_place', value=False),
                         Parameter('wrist_center_iters', value=4),
                         Parameter('wrist_center_tol', value=15.0)])
    spin_in_background(node)
    log = node.get_logger()
    msg = wait_for(lambda: node.blocks if node.blocks and node.blocks.blocks else None, 15.0)
    if msg is None:
        log.error('no blocks on /vla/blocks (is perception running?)')
        rclpy.shutdown()
        return 1
    blocks = [b for b in msg.blocks if b.kind == 'block' and (not args.colors or b.color in args.colors)]
    arm = node.arm(None)
    rows = []
    try:
        node.gripper(node.prm('gripper_open'), 'open', arm)
        for b in blocks:
            g = SimpleNamespace(pick_x=b.x, pick_y=b.y, pick_yaw=b.yaw, pick_color=b.color, pick_z_offset=0.0)
            pick_z = node.prm('grasp_z')
            try:
                node.move_joints(node.approach_ik(b.x, b.y, pick_z, b.yaw, 'above', arm), 'above', arm)
                node.center_on_block(g, arm, {})
            except RuntimeError as e:
                log.warn(f'{b.id}: {e}')
                continue
            finally:
                try:      # back up before the next block
                    node.move_joints(node.approach_ik(g.pick_x, g.pick_y, pick_z, b.yaw, 'up', arm), 'up', arm)
                except RuntimeError:
                    pass
            if not node.last_centred:
                log.warn(f'{b.id}: not centred, point dropped')
                continue
            d = np.hypot(g.pick_x - b.x, g.pick_y - b.y)
            log.info(f'{b.id}: top camera ({b.x:.3f}, {b.y:.3f}) -> arm ({g.pick_x:.3f}, {g.pick_y:.3f}), '
                     f'{d * 1000:.0f} mm apart')
            rows.append({'time': time.strftime('%F %T'), 'id': b.id, 'color': b.color, 'top_x': round(b.x, 4),
                         'top_y': round(b.y, 4), 'u': b.u, 'v': b.v,
                         'arm_x': round(g.pick_x, 4), 'arm_y': round(g.pick_y, 4)})
    finally:
        node.go_observe(arm)
        rclpy.shutdown()
    new = not os.path.exists(args.points)
    with open(args.points, 'a', newline='') as handle:
        w = csv.DictWriter(handle, FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} of {len(blocks)} blocks measured -> {args.points}')
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
    with open(path, 'w') as handle:
        yaml.safe_dump(homo, handle, sort_keys=False)
    print(f'wrote {path} (previous: {backup}); restart perception to use it')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('measure', help='centre the wrist camera on every visible block, append the points')
    m.add_argument('--colors', nargs='*', default=[], help='only these colors (default: all blocks)')
    f = sub.add_parser('fit', help='fit the correction and rewrite top_homography.yaml')
    f.add_argument('--dry-run', action='store_true', help='print the fit, write nothing')
    for p in (m, f):
        p.add_argument('--points', default=POINTS)
        p.add_argument('--calib-dir', default=DEFAULT_CALIB_DIR)
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])
    return measure(args) if args.cmd == 'measure' else fit(args)


if __name__ == '__main__':
    sys.exit(main())
