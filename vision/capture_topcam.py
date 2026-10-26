#!/usr/bin/env python3
"""Capture top-camera images for YOLO training data.

Same camera settings as record_bi.sh / eval_bi.sh: /dev/cam_top, 640x480, MJPG, 30fps,
manual exposure 90 (applied after the stream starts, because the camera resets it on open).

Usage (conda env vision_project):
    python capture_topcam.py                    # live window, press keys to save
    python capture_topcam.py --interval 1.0     # also auto-save every 1 s
    python capture_topcam.py --exposure -1      # keep auto exposure
    python capture_topcam.py --session gauze_day1 --auto --skip-similar 4
    python capture_topcam.py --headless --count 3   # no window, save 3 frames and exit

Keys in the window:
    SPACE or s : save current frame
    a          : toggle auto-save (every --interval seconds, default 1 s)
    q or ESC   : quit

Images (clean, no overlay, JPEG q95) go to
    ~/main_project/yolo/datasets/topcam_raw/<session or timestamp>/topcam_YYYYmmdd_HHMMSS_ms.jpg
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

import cv2

DEV = "/dev/cam_top"


def camera_busy():
    real = os.path.realpath(DEV)
    r = subprocess.run(["fuser", real], capture_output=True, text=True)
    return r.stdout.strip()


def set_exposure(value):
    real = os.path.realpath(DEV)
    if value < 0:
        subprocess.run(["v4l2-ctl", "-d", real, "-c", "auto_exposure=3"], capture_output=True)
        return "auto"
    # Toggle through auto so the driver actually sends the new value.
    subprocess.run(["v4l2-ctl", "-d", real, "-c", "auto_exposure=3"], capture_output=True)
    time.sleep(0.3)
    subprocess.run(["v4l2-ctl", "-d", real, "-c", "auto_exposure=1",
                    "-c", f"exposure_time_absolute={value}"], capture_output=True)
    r = subprocess.run(["v4l2-ctl", "-d", real, "-C", "auto_exposure,exposure_time_absolute"],
                       capture_output=True, text=True)
    return r.stdout.replace("\n", " ").strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.expanduser("~/main_project/yolo/datasets/topcam_raw"))
    p.add_argument("--session", default="", help="sub-folder name (default: timestamp)")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--skip-similar", type=float, default=0.0,
                   help="auto mode: skip frame if mean abs diff to last saved < this (e.g. 4)")
    p.add_argument("--exposure", type=int, default=90, help="manual exposure, -1 = leave auto")
    p.add_argument("--interval", type=float, default=1.0, help="auto-save interval (s)")
    p.add_argument("--auto", action="store_true", help="start with auto-save on")
    p.add_argument("--count", type=int, default=0, help="stop after N saved images (0 = no limit)")
    p.add_argument("--headless", "--no-show", dest="no_show", action="store_true",
                   help="no window; auto-save at --interval")
    args = p.parse_args()

    busy = camera_busy()
    if busy:
        sys.exit(f"{DEV} is in use by PID {busy}. Stop record/eval/teleop first.")

    session = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out, session)
    os.makedirs(out_dir, exist_ok=True)

    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if not cap.isOpened():
        sys.exit(f"Cannot open {DEV}")

    # Warm up, then apply exposure while streaming, then let it settle.
    for _ in range(30):
        cap.read()
    print("[exposure]", set_exposure(args.exposure))
    for _ in range(30):
        cap.read()

    auto = args.auto or args.no_show
    last_save = 0.0
    saved = 0
    skipped = 0
    last_small = None
    print(f"Resolution {int(cap.get(3))}x{int(cap.get(4))}")
    print(f"Saving to {out_dir}")
    print("SPACE/s: save   a: auto-save on/off   q/ESC: quit")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("frame read failed")
                break
            now = time.time()
            save = auto and now - last_save >= args.interval

            if not args.no_show:
                view = frame.copy()
                status = f"saved {saved}  skipped {skipped}  auto {'ON' if auto else 'off'} ({args.interval}s)"
                cv2.putText(view, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.putText(view, out_dir[-60:], (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                cv2.imshow("top cam capture", view)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key in (ord(" "), ord("s")):
                    save = True
                if key == ord("a"):
                    auto = not auto
                    last_save = 0.0

            if save and auto and args.skip_similar > 0 and last_small is not None:
                small = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
                if cv2.absdiff(small, last_small).mean() < args.skip_similar:
                    skipped += 1
                    last_save = now
                    save = False
            if save:
                last_small = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
                name = datetime.now().strftime("topcam_%Y%m%d_%H%M%S_%f")[:-3] + ".jpg"
                cv2.imwrite(os.path.join(out_dir, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved += 1
                last_save = now
                print(f"[{saved}] {name}")
                if args.count and saved >= args.count:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print(f"Done: {saved} images ({skipped} near-duplicates skipped) in {out_dir}")


if __name__ == "__main__":
    main()
