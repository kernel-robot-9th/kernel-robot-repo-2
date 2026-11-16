#!/usr/bin/env python3
"""Live gauze detection on the top camera (YOLO26-obb), work area only.

The full frame goes to the model (same as training); detections whose center is
outside the work area (ROI) are dropped. The ROI is drawn in green.

Usage (conda env vision_project):
    python live_obb.py
    python live_obb.py --weights runs/obb/gauze_obb_v1/weights/best.pt --conf 0.5
    python live_obb.py --roi 0,0.5,0.4,1.0       # x1,y1,x2,y2 as fractions of the frame

Keys (click the window first):
    ENTER : save the current annotated frame to outputs/live/
    ESC   : quit
"""
import argparse
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO

from capture_topcam import DEV, camera_busy, set_exposure

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = [(255, 80, 0), (0, 220, 120), (0, 160, 255), (200, 0, 200)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default=os.path.join(HERE, "runs/obb/gauze_obb_v1/weights/best.pt"))
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--roi", default="0,0.5,0.4,1.0", help="x1,y1,x2,y2 fractions")
    p.add_argument("--exposure", type=int, default=90, help="manual exposure, -1 = auto")
    p.add_argument("--device", default="0")
    p.add_argument("--headless", type=int, default=0, help="no window: run N frames, print, exit")
    args = p.parse_args()

    busy = camera_busy()
    if busy:
        sys.exit(f"{DEV} is in use by PID {busy}. Stop record/eval/teleop first.")

    model = YOLO(args.weights)
    names = model.names

    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if not cap.isOpened():
        sys.exit(f"Cannot open {DEV}")
    for _ in range(30):
        cap.read()
    print("[exposure]", set_exposure(args.exposure))
    for _ in range(30):
        cap.read()

    out_dir = os.path.join(HERE, "outputs/live")
    fx1, fy1, fx2, fy2 = map(float, args.roi.split(","))
    t_prev, fps, frames = time.time(), 0.0, 0
    print("ENTER: save frame   ESC: quit")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("frame read failed")
                break
            h, w = frame.shape[:2]
            rx1, ry1, rx2, ry2 = int(fx1 * w), int(fy1 * h), int(fx2 * w), int(fy2 * h)

            r = model.predict(frame, conf=args.conf, device=args.device, verbose=False)[0]
            view = frame.copy()
            cv2.rectangle(view, (rx1, ry1), (rx2 - 1, ry2 - 1), (0, 255, 0), 2)
            found = []
            if r.obb is not None and len(r.obb):
                for poly, xywhr, cls, cf in zip(r.obb.xyxyxyxy.cpu().numpy(), r.obb.xywhr.cpu().numpy(),
                                                r.obb.cls.cpu().numpy(), r.obb.conf.cpu().numpy()):
                    cx, cy, bw, bh, ang = xywhr
                    if not (rx1 <= cx < rx2 and ry1 <= cy < ry2):
                        continue
                    c = int(cls)
                    col = COLORS[c % len(COLORS)]
                    cv2.polylines(view, [poly.astype(np.int32)], True, col, 2)
                    cv2.circle(view, (int(cx), int(cy)), 3, col, -1)
                    cv2.putText(view, f"{names[c]} {cf:.2f} {np.degrees(ang):.0f}deg",
                                (int(cx) + 5, int(cy) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2)
                    found.append((names[c], float(cf), float(cx), float(cy), float(np.degrees(ang))))

            now = time.time()
            fps = 0.9 * fps + 0.1 / max(now - t_prev, 1e-6)
            t_prev = now
            cv2.putText(view, f"{len(found)} in ROI  {fps:.0f} fps   ENTER: save  ESC: quit", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            frames += 1
            if args.headless:
                print(f"frame {frames}: " + ", ".join(f"{n} {c:.2f} ({x:.0f},{y:.0f}) {a:.0f}deg"
                                                       for n, c, x, y, a in found))
                if frames >= args.headless:
                    os.makedirs(out_dir, exist_ok=True)
                    cv2.imwrite(os.path.join(out_dir, "headless_last.jpg"), view)
                    break
                continue

            cv2.imshow("gauze obb (top cam)", view)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key in (13, 10):
                os.makedirs(out_dir, exist_ok=True)
                name = datetime.now().strftime("live_%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
                cv2.imwrite(os.path.join(out_dir, name), view)
                print("saved", name)
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
