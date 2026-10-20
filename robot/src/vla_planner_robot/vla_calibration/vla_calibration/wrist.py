#!/usr/bin/env python3
"""Wrist-camera grasp-check calibration: ROI and fill threshold.

With one block on the table (detected by vla_perception), the arm records the wrist
image in three situations:
  held  - block grasped and lifted (what a good grasp looks like)
  empty - gripper closed on nothing at the same height
  miss  - gripper closed just above the block, block left on the table
The ROI is the area the held block covers in every frame (shrunk a little), and the
threshold is placed halfway between the held fill and the worst miss/empty fill.
Output: `wrist_roi`, `wrist_min_fill` for vla_executor.

  ros2 run vla_calibration wrist --color red
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.parameter import Parameter

from vla_calibration.common import (DEFAULT_CALIB_DIR, apply_param_files, param_overrides, spin_in_background,
                                    to_list, update_param_file, wait_for)
from vla_executor.executor_node import PickPlaceExecutor
from vla_executor.grasp_check import color_mask, draw_check, grasp_fill
from vla_interfaces.msg import BlockArray


def roi_from_masks(masks, shrink=0.12, min_area=200):
    """Box (fractions) inside the region present in every held mask, shrunk by `shrink`."""
    common = masks[0].copy()
    for m in masks[1:]:
        common &= m
    common = cv2.morphologyEx(common, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(common)
    if n < 2:
        raise RuntimeError('held block not visible in the wrist image')
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[k, cv2.CC_STAT_AREA] < min_area:
        raise RuntimeError(f'held block covers only {stats[k, cv2.CC_STAT_AREA]} px')
    x, y, w, h = (stats[k, i] for i in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                         cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    x0, x1 = x + shrink * w, x + (1 - shrink) * w
    y0, y1 = y + shrink * h, y + (1 - shrink) * h
    H, W = common.shape
    return [round(float(x0) / W, 3), round(float(y0) / H, 3), round(float(x1) / W, 3), round(float(y1) / H, 3)]


def choose_threshold(held, negatives, min_margin=0.25):
    lo, hi = max(negatives), min(held)
    thr = round((lo + hi) / 2.0, 3)
    return thr, hi - lo, (hi - lo) >= min_margin


class WristCalibrator(PickPlaceExecutor):

    def __init__(self, overrides=()):
        super().__init__(node_name='vla_calib_wrist', serve=False, parameter_overrides=list(overrides))
        self.blocks = None
        self.create_subscription(BlockArray, '/vla/blocks', lambda m: setattr(self, 'blocks', m), 10)

    def frames(self, n, arm, gap=0.15):
        out = []
        for _ in range(n):
            img = self.latest_wrist_image(timeout=2.0, arm=arm)
            if img is None:
                raise RuntimeError(f'no wrist image for arm "{arm.name}"')
            out.append(img)
            time.sleep(gap)
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--color', default='red', help='block to use (must be the only one of that color)')
    ap.add_argument('--arm', default='', help='two-arm setup: which arm (left/right) does the test')
    ap.add_argument('--frames', type=int, default=5)
    ap.add_argument('--miss-offset', type=float, default=0.02,
                    help='how far above the grasp height the "miss" grasp closes [m]')
    ap.add_argument('--executor-config', nargs='*', default=[
        os.path.join(get_package_share_directory('vla_executor'), 'config', 'executor.yaml')])
    ap.add_argument('--colors-config', default=os.path.join(DEFAULT_CALIB_DIR, 'colors.yaml'),
                    help='calibrated colors (used if the file exists)')
    ap.add_argument('--out', default=os.path.join(DEFAULT_CALIB_DIR, 'wrist.yaml'))
    ap.add_argument('--debug-image', default=os.path.join(DEFAULT_CALIB_DIR, 'wrist_calibration.png'))
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])

    rclpy.init(args=argv)
    node = WristCalibrator(param_overrides(args.executor_config + [args.colors_config], 'vla_executor'))
    apply_param_files(node, args.executor_config + [args.colors_config], 'vla_executor')
    node.set_parameters([Parameter('wrist_check', value=False)])
    spin_in_background(node)
    log = node.get_logger()

    blk = wait_for(lambda: node.blocks and next((b for b in node.blocks.blocks if b.color == args.color), None), 10.0)
    if blk is None:
        log.error(f'no {args.color} block on /vla/blocks')
        rclpy.shutdown()
        return 1
    hsv = node.hsv_ranges()[args.color]
    x, y, yaw = blk.x, blk.y, blk.yaw
    gz, up = node.prm('grasp_z'), node.prm('approach_height')
    arm = node.arm(args.arm or None)
    try:
        q_pre = node.ik_or_fail(x, y, gz + up, yaw, 'pre', arm)
        q_grasp = node.ik_or_fail(x, y, gz, yaw, 'grasp', arm)
        q_miss = node.ik_or_fail(x, y, gz + args.miss_offset, yaw, 'miss', arm)
    except RuntimeError as e:
        log.error(f'{args.color} block at ({x:.3f}, {y:.3f}): {e}')
        rclpy.shutdown()
        return 1

    try:
        log.info(f'{args.color} block at ({x:.3f}, {y:.3f}): held')
        node.gripper(node.prm('gripper_open'), 'open', arm)
        node.move_joints(q_pre, 'pre', arm)
        node.move_joints(q_grasp, 'grasp', arm)
        node.gripper(node.prm('gripper_closed'), 'close', arm)
        node.move_joints(q_pre, 'lift', arm)
        held = node.frames(args.frames, arm)
        node.move_joints(q_grasp, 'put back', arm)
        node.gripper(node.prm('gripper_release'), 'release', arm)
        node.move_joints(q_pre, 'up', arm)

        log.info('empty')
        node.gripper(node.prm('gripper_closed'), 'close', arm)
        empty = node.frames(args.frames, arm)

        log.info('miss (closed above the block)')
        node.gripper(node.prm('gripper_open'), 'open', arm)
        node.move_joints(q_miss, 'miss', arm)
        node.gripper(node.prm('gripper_closed'), 'close', arm)
        node.move_joints(q_pre, 'lift', arm)
        miss = node.frames(args.frames, arm)
        node.recover(arm)
    except Exception as e:  # noqa: BLE001
        log.error(f'stopped: {e}')
        try:
            node.recover(arm)
        except Exception:  # noqa: BLE001
            pass
        rclpy.shutdown()
        return 1

    roi = roi_from_masks([color_mask(f, hsv) for f in held])
    fill = {name: [grasp_fill(f, {args.color: hsv}, args.color, roi)[0] for f in fs]
            for name, fs in (('held', held), ('empty', empty), ('miss', miss))}
    thr, margin, ok = choose_threshold(fill['held'], fill['empty'] + fill['miss'])

    print('\nROI (x0, y0, x1, y1 fractions):', roi)
    for k, v in fill.items():
        print(f'  {k:5s} fill  min {min(v) * 100:5.1f} %   max {max(v) * 100:5.1f} %')
    print(f'threshold {thr * 100:.1f} %   margin {margin * 100:.1f} %'
          + ('' if ok else '   WARNING: small margin - check lighting / camera mount'))
    tiles = [draw_check(fs[-1], roi, grasp_fill(fs[-1], {args.color: hsv}, args.color, roi)[0],
                        args.color, grasp_fill(fs[-1], {args.color: hsv}, args.color, roi)[0] >= thr)
             for fs in (held, empty, miss)]
    os.makedirs(os.path.dirname(os.path.abspath(args.debug_image)), exist_ok=True)
    cv2.imwrite(args.debug_image, np.hstack(tiles))
    update_param_file(args.out, {'vla_executor': {'wrist_roi': to_list(roi, 3),
                                                  'wrist_min_fill': float(thr)}})
    print(f'written: {args.out}  (debug image {args.debug_image})')
    rclpy.shutdown()
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
