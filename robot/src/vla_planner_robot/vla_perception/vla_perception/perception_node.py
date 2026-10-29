#!/usr/bin/env python3
"""Top-camera perception: ArUco corner markers -> table homography -> color blocks.

Publishes vla_interfaces/BlockArray on /vla/blocks (base frame, metres) and an
annotated image on /vla/debug_image. The homography is refreshed whenever all
markers are visible and kept when the arm occludes some of them.
"""
import os

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

from vla_interfaces.msg import Block, BlockArray
from vla_perception.table_geometry import (DEFAULT_ARUCO_DICT, DEFAULT_HSV, TableHomography,
                                           Undistorter, aruco_dictionary_id, blob_pose_on_table,
                                           color_blobs, detect_markers, image_to_numpy)


class PerceptionNode(Node):

    def __init__(self):
        super().__init__('vla_perception')
        p = self.declare_parameter
        p('image_topic', '/camera/image_raw')
        p('camera_info_topic', '/camera/camera_info')
        p('aruco_dictionary', DEFAULT_ARUCO_DICT)   # cv2.aruco name, e.g. DICT_5X5_100
        p('marker_ids', [0, 1, 2, 3])
        # marker centers in the robot base frame, flattened [x0, y0, x1, y1, ...] (m)
        p('marker_positions', [0.05, 0.20, 0.33, 0.20, 0.33, -0.20, 0.05, -0.20])
        p('block_height', 0.025)
        p('roi_margin', 0.0)           # grow the marker polygon by this much (m)
        p('min_area', 150)
        p('max_area', 60000)
        p('frame_id', 'link0')         # frame of marker_positions and of the output (world for two arms)
        p('tray_colors', ['purple'])   # long objects of these colors are trays (two-arm carry)
        p('tray_min_length', 0.12)
        p('tray_height', 0.02)         # height used for the parallax correction of trays
        p('debug_every', 3)            # publish the debug image every N frames
        # real top camera (2026-10-22): fixed calibration files instead of corner markers
        p('calibration_dir', '')       # holds top_intrinsics.yaml + top_homography.yaml (vla_calibration top_camera)
        p('roi_xy', [0.0])             # work-area polygon in frame_id, flattened [x0, y0, x1, y1, ...] (m)
        p('colors', list(DEFAULT_HSV))
        for c, rng in DEFAULT_HSV.items():
            p(f'hsv.{c}', rng)

        ids = list(self.get_parameter('marker_ids').value)
        pos = list(self.get_parameter('marker_positions').value)
        self.marker_xy = {i: (pos[2 * k], pos[2 * k + 1]) for k, i in enumerate(ids)}
        self.hsv = {c: list(self.get_parameter(f'hsv.{c}').value)
                    for c in self.get_parameter('colors').value
                    if self.has_parameter(f'hsv.{c}')}

        self.aruco_dict = aruco_dictionary_id(self.get_parameter('aruco_dictionary').value)
        self.K = None
        self.undistort = Undistorter()
        self.homography = None
        self.fixed = False
        self.frame = 0
        if self.get_parameter('calibration_dir').value:
            self._load_calibration(os.path.expanduser(self.get_parameter('calibration_dir').value))

        self.pub = self.create_publisher(BlockArray, '/vla/blocks', 10)
        self.dbg = self.create_publisher(Image, '/vla/debug_image', 1)
        self.create_subscription(CameraInfo, self.get_parameter('camera_info_topic').value,
                                 self._on_info, qos_profile_sensor_data)
        self.create_subscription(Image, self.get_parameter('image_topic').value,
                                 self._on_image, qos_profile_sensor_data)
        self.get_logger().info(f'markers {self.get_parameter("aruco_dictionary").value} '
                               f'{self.marker_xy}, colors {list(self.hsv)}')

    def _load_calibration(self, folder):
        """K, distortion and the undistorted-pixel -> frame homography from the top_camera tool."""
        with open(os.path.join(folder, 'top_intrinsics.yaml')) as handle:
            intr = yaml.safe_load(handle)
        with open(os.path.join(folder, 'top_homography.yaml')) as handle:
            homo = yaml.safe_load(handle)
        self.K, H = np.array(intr['K'], float), np.array(homo['H'], float)
        self.undistort = Undistorter(self.K, np.array(intr['dist'], float))
        w, h = intr['size']
        grid = np.array([(u, v) for u in np.linspace(0, w, 9) for v in np.linspace(0, h, 6)], float)
        table = cv2.perspectiveTransform(grid.reshape(-1, 1, 2), H).reshape(-1, 2)
        self.homography = TableHomography(grid, table, self.K)   # same H; the camera centre feeds the parallax fix
        self.fixed = True
        c = self.homography.camera_center
        self.get_logger().info(f'calibration {folder}: fit error {homo.get("fit_error_mm")}, check error '
                               f'{homo.get("check_error_mm")} mm, camera at {None if c is None else np.round(c, 3).tolist()}')

    def _on_info(self, msg):
        if self.fixed:
            return
        if self.K is None and any(msg.k):
            self.K = np.array(msg.k).reshape(3, 3)
            self.undistort = Undistorter(self.K, np.array(msg.d) if len(msg.d) else None)
            self.get_logger().info('camera intrinsics received')

    def _update_homography(self, markers):
        if not all(i in markers for i in self.marker_xy):
            return
        ids = list(self.marker_xy)
        img_pts = self.undistort(np.array([markers[i].mean(axis=0) for i in ids]))
        table_pts = np.array([self.marker_xy[i] for i in ids])
        h = TableHomography(img_pts, table_pts, self.K)
        if self.homography is None:
            c = h.camera_center
            self.get_logger().info(
                f'table calibrated: reprojection err {h.reproj_err * 1000:.2f} mm, camera at '
                f'{None if c is None else np.round(c, 3).tolist()}')
        self.homography = h

    def _roi_mask(self, shape):
        roi = list(self.get_parameter('roi_xy').value)
        if len(roi) >= 6:      # explicit work area (real setup has no corner markers)
            poly = self.homography.to_pixel(np.array(roi, float).reshape(-1, 2))
            poly = cv2.convexHull(poly.astype(np.float32)).astype(np.int32)
            mask = np.zeros(shape[:2], np.uint8)
            cv2.fillConvexPoly(mask, poly, 255)
            return mask, poly
        xy = np.array(list(self.marker_xy.values()), float)
        center = xy.mean(axis=0)
        m = self.get_parameter('roi_margin').value
        grown = center + (xy - center) * (1.0 + m / np.linalg.norm(xy - center, axis=1, keepdims=True))
        poly = self.homography.to_pixel(grown)
        poly = cv2.convexHull(poly.astype(np.float32)).astype(np.int32)
        mask = np.zeros(shape[:2], np.uint8)
        cv2.fillConvexPoly(mask, poly, 255)
        return mask, poly

    def _on_image(self, msg):
        try:
            bgr = image_to_numpy(msg)
        except ValueError as e:
            self.get_logger().error(str(e), throttle_duration_sec=5.0)
            return
        markers = {} if self.fixed else detect_markers(bgr, self.aruco_dict)
        if not self.fixed:
            self._update_homography(markers)

        out = BlockArray()
        out.header = msg.header
        out.header.frame_id = self.get_parameter('frame_id').value
        out.table_calibrated = self.homography is not None
        poly = None
        if self.homography is not None:
            roi, poly = self._roi_mask(bgr.shape)
            h = float(self.get_parameter('block_height').value)
            counts = {}
            blobs = color_blobs(bgr, self.hsv, roi,
                                self.get_parameter('min_area').value,
                                self.get_parameter('max_area').value)
            tray_colors = set(self.get_parameter('tray_colors').value)
            for color, contour in blobs:
                x, y, yaw, (length, width), long_yaw = blob_pose_on_table(
                    contour, self.homography, self.undistort, h)
                kind = 'block'
                if color in tray_colors:
                    x, y, yaw, (length, width), long_yaw = blob_pose_on_table(
                        contour, self.homography, self.undistort,
                        float(self.get_parameter('tray_height').value))
                    if length >= self.get_parameter('tray_min_length').value:
                        kind, yaw = 'tray', long_yaw
                m = cv2.moments(contour)
                b = Block()
                b.color = color
                b.kind = kind
                b.length, b.width = float(length), float(width)
                b.x, b.y, b.yaw = float(x), float(y), float(yaw)
                b.u, b.v = int(m['m10'] / m['m00']), int(m['m01'] / m['m00'])
                b.area_px = float(m['m00'])
                out.blocks.append(b)
            # stable ids: per color (trays: per kind), ordered by distance from the frame origin
            out.blocks.sort(key=lambda b: (b.kind, b.color, b.x * b.x + b.y * b.y))
            for b in out.blocks:
                key = 'tray' if b.kind == 'tray' else b.color
                k = counts.get(key, 0)
                counts[key] = k + 1
                b.id = f'{key}_{k}'
        self.pub.publish(out)

        self.frame += 1
        if self.dbg.get_subscription_count() and self.frame % self.get_parameter('debug_every').value == 0:
            self._publish_debug(bgr, markers, poly, out, msg.header)

    def _publish_debug(self, bgr, markers, poly, out, header):
        img = bgr.copy()
        for i, c in markers.items():
            cv2.polylines(img, [c.astype(np.int32)], True, (255, 0, 255), 2)
            cv2.putText(img, str(i), tuple(c.mean(axis=0).astype(int)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (255, 0, 255), 2)
        if poly is not None:
            cv2.polylines(img, [poly], True, (0, 255, 255), 1)
        for b in out.blocks:
            cv2.circle(img, (b.u, b.v), 5, (0, 0, 0), -1)
            cv2.putText(img, f'{b.id} ({b.x:.3f},{b.y:.3f})', (b.u + 8, b.v - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        m = Image()
        m.header = header
        m.height, m.width = rgb.shape[:2]
        m.encoding = 'rgb8'
        m.step = m.width * 3
        m.data = rgb.tobytes()
        self.dbg.publish(m)


def main():
    rclpy.init()
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
