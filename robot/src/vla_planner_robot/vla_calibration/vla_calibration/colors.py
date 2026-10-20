#!/usr/bin/env python3
"""Block color (HSV) calibration.

Put one block of each color on the table inside the four markers (nothing else
colorful in between), fold the arm out of the view, and run:

  ros2 run vla_calibration colors --colors red green blue yellow

Saturated blobs inside the marker quad are matched to the requested colors by hue,
their pixel statistics are collected over several frames and turned into HSV
ranges. The result is written for both vla_perception and vla_executor (the
wrist-camera grasp check uses the same colors).
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

from vla_calibration.common import DEFAULT_CALIB_DIR, spin_in_background, update_param_file
from vla_perception.table_geometry import DEFAULT_ARUCO_DICT, detect_markers, image_to_numpy

# nominal OpenCV hue (0-179) of each color name
REFERENCE_HUE = {'red': 0, 'orange': 12, 'yellow': 28, 'green': 60, 'cyan': 90,
                 'blue': 115, 'purple': 140, 'pink': 165}


def hue_distance(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def circular_median(h):
    """Median hue that is robust to the 0/179 wrap (red)."""
    shifted = (h.astype(np.int32) + 90) % 180
    if np.std(shifted) < np.std(h):
        return (np.median(shifted) - 90) % 180
    return float(np.median(h))


def table_mask(shape, markers, ids, marker_pad=8):
    """Inside the quad of marker centers, minus the markers themselves."""
    mask = np.zeros(shape[:2], np.uint8)
    centers = np.array([markers[i].mean(axis=0) for i in ids], np.float32)
    cv2.fillConvexPoly(mask, cv2.convexHull(centers).astype(np.int32), 255)
    for i in ids:
        x0, y0 = markers[i].min(axis=0).astype(int) - marker_pad
        x1, y1 = markers[i].max(axis=0).astype(int) + marker_pad
        mask[max(y0, 0):y1, max(x0, 0):x1] = 0
    return mask


def find_blobs(bgr, mask, s_min=80, v_min=50, min_area=150):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = ((hsv[:, :, 1] >= s_min) & (hsv[:, :, 2] >= v_min)).astype(np.uint8) * 255
    sat &= mask
    sat = cv2.morphologyEx(sat, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(sat)
    blobs = []
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] >= min_area:
            px = hsv[labels == k]
            blobs.append((circular_median(px[:, 0]), px))
    return blobs


def hsv_range(pixels, hue_margin=6, s_drop=40, v_drop=50, s_floor=60, v_floor=40):
    """Pixel samples (N x 3 HSV) -> flat OpenCV range list (6 numbers per range)."""
    h = pixels[:, 0].astype(np.int32)
    center = circular_median(h)
    rel = ((h - center + 90) % 180) - 90                     # hue relative to center, -90..89
    lo = int(np.floor(np.percentile(rel, 1))) - hue_margin
    hi = int(np.ceil(np.percentile(rel, 99))) + hue_margin
    s_lo = int(max(s_floor, np.percentile(pixels[:, 1], 2) - s_drop))
    v_lo = int(max(v_floor, np.percentile(pixels[:, 2], 2) - v_drop))
    a, b = int(round(center)) + lo, int(round(center)) + hi
    if a < 0:
        return [0, s_lo, v_lo, b, 255, 255, 180 + a, s_lo, v_lo, 179, 255, 255]
    if b > 179:
        return [a, s_lo, v_lo, 179, 255, 255, 0, s_lo, v_lo, b - 180, 255, 255]
    return [a, s_lo, v_lo, b, 255, 255]


def range_hues(flat):
    out = set()
    for k in range(0, len(flat), 6):
        out.update(range(flat[k], flat[k + 3] + 1))
    return out


class ColorCollector(Node):

    def __init__(self, args):
        super().__init__('vla_calib_colors')
        self.args = args
        self.samples = {c: [] for c in args.colors}
        self.frames = 0
        self.problems = []
        self.create_subscription(Image, args.image_topic, self._on_image, qos_profile_sensor_data)

    def _on_image(self, msg):
        if self.frames >= self.args.frames:
            return
        bgr = image_to_numpy(msg)
        markers = detect_markers(bgr, self.args.aruco_dictionary)
        ids = self.args.marker_ids
        if not all(i in markers for i in ids):
            self.problems.append('markers not all visible')
            return
        blobs = find_blobs(bgr, table_mask(bgr.shape, markers, ids))
        assigned = {}
        for hue, px in blobs:
            c = min(self.args.colors, key=lambda c: hue_distance(hue, REFERENCE_HUE[c]))
            if hue_distance(hue, REFERENCE_HUE[c]) > self.args.max_hue_error:
                self.problems.append(f'blob with hue {hue:.0f} matches no requested color')
                continue
            assigned.setdefault(c, []).append(px)
        missing = [c for c in self.args.colors if c not in assigned]
        if missing:
            self.problems.append(f'no blob for {missing}')
            return
        for c, pxs in assigned.items():
            self.samples[c].append(np.concatenate(pxs))
        self.frames += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image-topic', default='/camera/image_raw')
    ap.add_argument('--colors', nargs='+', default=['red', 'green', 'blue', 'yellow'],
                    choices=sorted(REFERENCE_HUE))
    ap.add_argument('--marker-ids', type=int, nargs=4, default=[0, 1, 2, 3])
    ap.add_argument('--aruco-dictionary', default=DEFAULT_ARUCO_DICT,
                    help='must match vla_perception aruco_dictionary')
    ap.add_argument('--frames', type=int, default=15)
    ap.add_argument('--max-hue-error', type=float, default=20.0)
    ap.add_argument('--timeout', type=float, default=60.0)
    ap.add_argument('--out', default=os.path.join(DEFAULT_CALIB_DIR, 'colors.yaml'))
    args = ap.parse_args(rclpy.utilities.remove_ros_args(argv or sys.argv)[1:])

    rclpy.init(args=argv)
    node = ColorCollector(args)
    spin_in_background(node)
    deadline = time.monotonic() + args.timeout
    while node.frames < args.frames and time.monotonic() < deadline:
        time.sleep(0.1)
    if node.frames == 0:
        last = node.problems[-1] if node.problems else 'no image'
        node.get_logger().error(f'no usable frame ({last})')
        rclpy.shutdown()
        return 1

    ranges, report = {}, []
    for c in args.colors:
        px = np.concatenate(node.samples[c])
        ranges[c] = hsv_range(px)
        med = [int(np.median(px[:, k])) for k in range(3)]
        report.append(f'  {c:7s} median HSV {med}  ->  {ranges[c]}')
    # sanity: no hue shared between two colors, and every color still matches its own pixels
    overlaps = [(a, b) for i, a in enumerate(args.colors) for b in args.colors[i + 1:]
                if range_hues(ranges[a]) & range_hues(ranges[b])]
    for c in args.colors:
        px = np.concatenate(node.samples[c])
        m = np.zeros(len(px), bool)
        r = ranges[c]
        for k in range(0, len(r), 6):
            m |= np.all((px >= r[k:k + 3]) & (px <= r[k + 3:k + 6]), axis=1)
        report.append(f'  {c:7s} recall on collected pixels {100 * m.mean():.1f} %')

    params = {'colors': list(args.colors)}
    params.update({f'hsv.{c}': ranges[c] for c in args.colors})
    update_param_file(args.out, {'vla_perception': params, 'vla_executor': params})
    print(f'\nframes used: {node.frames}')
    print('\n'.join(report))
    if overlaps:
        print(f'WARNING: overlapping hue ranges {overlaps} - colors may be confused')
    print(f'written: {args.out}')
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
