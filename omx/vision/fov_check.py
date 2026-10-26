#!/usr/bin/env python3
"""Measure how the 640x480 top-camera view sits inside the 1920x1080 view (conda env vision_project).

Prints sx,sy,tx,ty for eval_bi_api_yolo.py --to-calib (u1080 = sx*u640 + tx, v1080 = sy*v640 + ty)
and saves outputs/fov_640_in_1080.jpg. Needs a textured scene and a free camera.
"""
import cv2
import numpy as np

DEV = "/dev/cam_top"


def grab(w, h):
    c = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    for _ in range(40):
        c.read()
    ok, f = c.read()
    c.release()
    if not ok or f.shape[:2] != (h, w):
        raise SystemExit(f"could not grab {w}x{h}")
    return f


a, b = grab(640, 480), grab(1920, 1080)
orb = cv2.ORB_create(4000)
ka, da = orb.detectAndCompute(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), None)
kb, db = orb.detectAndCompute(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), None)
m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, True).match(da, db), key=lambda x: x.distance)[:400]
src = np.float32([ka[x.queryIdx].pt for x in m])
dst = np.float32([kb[x.trainIdx].pt for x in m])
A, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
sx, sy, tx, ty = A[0, 0], A[1, 1], A[0, 2], A[1, 2]
err = np.linalg.norm(src[inl.ravel() == 1] @ A[:, :2].T + A[:, 2] - dst[inl.ravel() == 1], axis=1)
print(f"inliers {int(inl.sum())}/{len(m)}, mean error {err.mean():.2f}px (1920x1080)")
print(f"skew terms {A[0, 1]:.4f} {A[1, 0]:.4f} (should be ~0)")
print(f"--to-calib {sx:.3f},{sy:.3f},{tx:.1f},{ty:.1f}")
c = np.float32([[0, 0], [640, 0], [640, 480], [0, 480]]) @ A[:, :2].T + A[:, 2]
v = b.copy()
cv2.polylines(v, [c.astype(np.int32)], True, (0, 0, 255), 4)
cv2.imwrite("outputs/fov_640_in_1080.jpg", cv2.resize(v, (960, 540)))
