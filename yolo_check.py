#!/usr/bin/env python3
"""Check what YOLO sees right now, with the same settings as eval_bi_api_yolo.py (no robot).

Run in conda env vision_project (the API server may stay running; the camera is only
borrowed for a moment):
  conda activate vision_project
  cd ~/kernel-robot-repo-2-il
  python yolo_check.py                 # every detection down to conf 0.10, plus the API's pick
  python yolo_check.py --target green_gauze
  python yolo_check.py --image some.jpg

Prints every box (label, conf, grasp point 640x480 / 1920x1080, inside ROI / click-pick region)
and what the API would pick at --conf (default 0.5). Saves outputs/yolo_check_<time>.jpg:
  green rectangle = ROI, yellow = click-pick region, red = API pick, cyan = would pass,
  grey = outside the work area, thin orange = below --conf (the API ignores it).
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from yolo_worker import Area, best_per_label, detect, grab_frames

YOLO_DIR = Path.home() / "main_project" / "yolo"
CLICK_CONFIG = Path.home() / "main_project/omxtest-main/config/omx_click_pick.json"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--weights", default=str(YOLO_DIR / "runs/obb/gauze_obb_v1/weights/best.pt"))
    p.add_argument("--target", default=None, help="blue_gauze / green_gauze (default: any)")
    p.add_argument("--image", default=None, help="use a saved 640x480 image instead of the camera")
    p.add_argument("--conf", type=float, default=0.5, help="API threshold")
    p.add_argument("--show-conf", type=float, default=0.10, help="also list boxes down to this")
    p.add_argument("--frames", type=int, default=5)
    p.add_argument("--exposure", type=int, default=90)
    p.add_argument("--roi", default="0,0.5,0.4,1.0")
    p.add_argument("--to-calib", default="2.25,2.25,240,0")
    p.add_argument("--cam-top", default="/dev/cam_top")
    args = p.parse_args()

    region = json.loads(CLICK_CONFIG.read_text())["regions_uv"][0]
    area = Area([float(v) for v in args.roi.split(",")], region, [float(v) for v in args.to_calib.split(",")])
    model = YOLO(args.weights)
    if args.image:
        frames = [cv2.imread(args.image)]
    else:
        frames = grab_frames(args.cam_top, args.frames, args.exposure, 640, 480)
    print(f"frames {len(frames)}, brightness {frames[-1].mean():.0f}/255")

    every = detect(model, frames, area, args.show_conf, "0")
    # one row per box of the last frame, plus each label's best over all frames
    last = [d for d in every if d["frame"] == len(frames) - 1]
    print(f"\nall boxes in the last frame (conf >= {args.show_conf}):")
    for d in sorted(last, key=lambda d: -d["conf"]):
        flags = ("ROI ok" if d["in_roi"] else "outside ROI") + ", " + \
                ("region ok" if d["in_region"] else "outside click-pick region")
        low = "  (below API conf)" if d["conf"] < args.conf else ""
        print(f"  {d['label']:12s} conf {d['conf']:.2f}  grasp 640x480 {d['grasp_uv_cam']} "
              f"-> 1920x1080 {d['grasp_uv']}  {flags}{low}")
    if not last:
        print("  (nothing)")

    api = best_per_label([d for d in every if d["conf"] >= args.conf])
    cand = [d for d in api if d["in_area"] and (args.target is None or d["label"] == args.target)]
    chosen = max(cand, key=lambda d: d["conf"]) if cand else None
    print(f"\nAPI would pick ({args.target or 'any gauze'}, conf >= {args.conf}): "
          + (f"{chosen['label']} conf {chosen['conf']:.2f} at 1920x1080 {chosen['grasp_uv']}" if chosen else "nothing"))

    view = frames[-1].copy()
    cv2.polylines(view, [area.roi_polygon(640, 480).astype(np.int32)], True, (0, 255, 0), 2)
    cv2.polylines(view, [np.array([area.to_cam(q) for q in area.region], np.int32)], True, (0, 200, 255), 1)
    for d in last:
        if d["conf"] < args.conf:
            col, th = (0, 140, 255), 1
        elif chosen and d["label"] == chosen["label"] and d["grasp_uv"] == chosen["grasp_uv"]:
            col, th = (0, 0, 255), 2
        else:
            col, th = ((255, 255, 0) if d["in_area"] else (128, 128, 128)), 2
        cv2.polylines(view, [np.array(d["corners"], np.int32)], True, col, th)
        g = tuple(int(v) for v in d["grasp_uv_cam"])
        cv2.circle(view, g, 3, col, -1)
        cv2.putText(view, f"{d['label'].split('_')[0]} {d['conf']:.2f}", (g[0] + 5, g[1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
    out = YOLO_DIR / "outputs" / f"yolo_check_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), view)
    print(f"\nimage: {out}")


if __name__ == "__main__":
    main()
