#!/usr/bin/env python3
"""Put the top camera back where it was: live view with the reference picture's markers overlaid.

  conda activate vision_project
  cd ~/kernel-robot-repo-2-il
  python camera_align.py              # window: red = reference markers, green = now, shift in px
  python camera_align.py --once       # no window: print the shift once and save outputs/camera_align.jpg

Move/rotate the camera until the shift reads under ~2 px (that was the 10/25 -> 10/26 difference).
Reference: the 10/25 top-camera picture the click-pick and YOLO settings were made with.
ESC / q = quit.
"""
import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np

YOLO = Path.home() / "main_project" / "yolo"
REF = YOLO / "datasets/topcam_raw/sample_20261025/topcam_20261025_174055_565.jpg"
DET = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
                              cv2.aruco.DetectorParameters())


def markers(img):
    corners, ids, _ = DET.detectMarkers(img)
    return [] if ids is None else [(int(i), c[0]) for c, i in zip(corners, ids.ravel())]


def compare(ref_m, now_m):
    """Per-marker shift (same id, nearest centre) and the overall move/rotation."""
    pairs = []
    for i, ca in ref_m:
        cands = [cb for j, cb in now_m if j == i]
        if not cands:
            continue
        cb = min(cands, key=lambda c: np.linalg.norm(c.mean(0) - ca.mean(0)))
        if np.linalg.norm(cb.mean(0) - ca.mean(0)) < 80:
            pairs.append((i, ca, cb))
    if len(pairs) < 2:
        return pairs, None
    src = np.float32([p for _, ca, _ in pairs for p in ca])
    dst = np.float32([p for _, _, cb in pairs for p in cb])
    A, _ = cv2.estimateAffinePartial2D(src, dst)
    return pairs, A


def draw(now, ref_m, now_m, pairs, A):
    view = now.copy()
    for _, c in ref_m:
        cv2.polylines(view, [c.astype(np.int32)], True, (0, 0, 255), 2)
    for _, c in now_m:
        cv2.polylines(view, [c.astype(np.int32)], True, (0, 255, 0), 2)
    for _, ca, cb in pairs:
        cv2.arrowedLine(view, tuple(map(int, ca.mean(0))), tuple(map(int, cb.mean(0))), (0, 255, 255), 2)
    if A is not None:
        mean = np.mean([np.linalg.norm(cb.mean(0) - ca.mean(0)) for _, ca, cb in pairs])
        rot = np.degrees(np.arctan2(A[1, 0], A[0, 0]))
        ok = mean < 3
        text = f"shift {mean:.1f}px  move ({A[0, 2]:+.0f},{A[1, 2]:+.0f})  rot {rot:+.2f}deg  {'OK' if ok else 'MOVE CAMERA'}"
        cv2.putText(view, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0) if ok else (0, 0, 255), 2)
    else:
        cv2.putText(view, "not enough markers", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return view


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true")
    p.add_argument("--ref", default=str(REF))
    p.add_argument("--cam-top", default="/dev/cam_top")
    args = p.parse_args()
    ref_m = markers(cv2.imread(args.ref))
    cap = cv2.VideoCapture(args.cam_top, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(30):
        cap.read()
    subprocess.run(["v4l2-ctl", "-d", str(Path(args.cam_top).resolve()), "-c", "auto_exposure=1",
                    "-c", "exposure_time_absolute=90"], capture_output=True)
    try:
        while True:
            ok, now = cap.read()
            if not ok:
                break
            now_m = markers(now)
            pairs, A = compare(ref_m, now_m)
            view = draw(now, ref_m, now_m, pairs, A)
            if args.once:
                for i, ca, cb in pairs:
                    d = cb.mean(0) - ca.mean(0)
                    print(f"marker {i} at {ca.mean(0).round(0)}: shift {d.round(1)} ({np.linalg.norm(d):.1f}px)")
                if A is not None:
                    print("overall move (%.1f, %.1f) px, rotation %.2f deg" %
                          (A[0, 2], A[1, 2], np.degrees(np.arctan2(A[1, 0], A[0, 0]))))
                out = YOLO / "outputs/camera_align.jpg"
                cv2.imwrite(str(out), view)
                print("image:", out)
                break
            cv2.imshow("camera align (red = reference, green = now)", view)
            if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
