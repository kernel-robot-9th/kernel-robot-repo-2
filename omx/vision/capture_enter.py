#!/usr/bin/env python3
"""Top camera capture: press ENTER to save one frame, ESC to quit.

Same camera settings as record_bi.sh / eval_bi.sh: /dev/cam_top, 640x480, MJPG, 30fps,
manual exposure 90.

Usage (conda env vision_project):
    python capture_enter.py                     # folder name = start time
    python capture_enter.py --session objects1  # datasets/topcam_raw/objects1/
    python capture_enter.py --exposure -1       # keep auto exposure

Keys (click the camera window first so it has keyboard focus):
    ENTER : save current frame
    ESC   : quit
"""
import argparse
import os
import sys
import time
from datetime import datetime

import cv2

from capture_topcam import DEV, camera_busy, set_exposure

ENTER_KEYS = (13, 10)  # Enter / keypad Enter
ESC_KEY = 27


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.expanduser("~/main_project/yolo/datasets/topcam_raw"))
    p.add_argument("--session", default="", help="sub-folder name (default: start time)")
    p.add_argument("--exposure", type=int, default=90, help="manual exposure, -1 = auto")
    args = p.parse_args()

    busy = camera_busy()
    if busy:
        sys.exit(f"{DEV} is in use by PID {busy}. Stop record/eval/teleop first.")

    session = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out, session)
    os.makedirs(out_dir, exist_ok=True)

    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if not cap.isOpened():
        sys.exit(f"Cannot open {DEV}")

    # Warm up, apply exposure while streaming (camera resets it on open), let it settle.
    for _ in range(30):
        cap.read()
    print("[exposure]", set_exposure(args.exposure))
    for _ in range(30):
        cap.read()

    saved = 0
    flash_until = 0.0
    print(f"Saving to {out_dir}")
    print("ENTER: capture   ESC: quit")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("frame read failed")
                break

            view = frame.copy()
            cv2.putText(view, f"saved {saved}   ENTER: capture  ESC: quit", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            if time.time() < flash_until:
                cv2.rectangle(view, (0, 0), (view.shape[1] - 1, view.shape[0] - 1), (0, 255, 0), 8)
            cv2.imshow("top cam capture", view)

            key = cv2.waitKey(1) & 0xFF
            if key == ESC_KEY:
                break
            if key in ENTER_KEYS:
                name = datetime.now().strftime("topcam_%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
                cv2.imwrite(os.path.join(out_dir, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved += 1
                flash_until = time.time() + 0.3
                print(f"[{saved}] {name}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print(f"Done: {saved} images in {out_dir}")


if __name__ == "__main__":
    main()
