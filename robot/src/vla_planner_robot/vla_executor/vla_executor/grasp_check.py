"""Wrist-camera grasp check: is the picked block between the fingers?

A held block is a few centimetres from the wrist camera and fills most of the region
just below the fingertips; a block left on the table (missed grasp) is ~6 cm further
away and fills far less. So the check is the fraction of ROI pixels of the block's color.
"""
import cv2
import numpy as np


def color_mask(bgr, hsv_ranges):
    """Union of the HSV ranges (6 numbers per range, OpenCV H in 0-179)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for k in range(0, len(hsv_ranges), 6):
        mask |= cv2.inRange(hsv, np.array(hsv_ranges[k:k + 3], np.uint8),
                            np.array(hsv_ranges[k + 3:k + 6], np.uint8))
    return mask


def roi_pixels(shape, roi):
    """roi = [x0, y0, x1, y1] as fractions of width/height -> integer pixel box."""
    h, w = shape[:2]
    x0, y0, x1, y1 = roi
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def grasp_fill(bgr, hsv_by_color, color, roi):
    """Fraction of the ROI covered by `color` ('' = best of all colors). Returns (fill, color)."""
    x0, y0, x1, y1 = roi_pixels(bgr.shape, roi)
    crop = bgr[y0:y1, x0:x1]
    colors = [color] if color else list(hsv_by_color)
    best = (0.0, color)
    for c in colors:
        if c not in hsv_by_color:
            raise ValueError(f'no HSV range for color "{c}"')
        fill = float(np.count_nonzero(color_mask(crop, hsv_by_color[c]))) / max(crop.shape[0] * crop.shape[1], 1)
        if fill > best[0]:
            best = (fill, c)
    return best


def draw_check(bgr, roi, fill, color, ok):
    img = bgr.copy()
    x0, y0, x1, y1 = roi_pixels(img.shape, roi)
    col = (0, 200, 0) if ok else (0, 0, 255)
    cv2.rectangle(img, (x0, y0), (x1, y1), col, 2)
    cv2.putText(img, f'{color or "?"} {fill * 100:.0f}% {"OK" if ok else "MISS"}', (5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    return img
