#!/usr/bin/env python3
"""YOLO gauze detector process for eval_bi_api_yolo.py (runs in conda env vision_project).

The robot env (main_project) has no ultralytics, so the API server starts this file with
the vision_project python and talks to it with one JSON line per request on stdin/stdout.

Request:  {"target": "blue_gauze" | null, "frames": 5, "save": "/path/out.jpg" | null}
          optional "image": "/path/frame.jpg" uses that file instead of the camera (testing)
Reply:    {"ok": true, "detection": {...} | null, "all": [...], "frame_mean": 87.3}
          "all" keeps one detection per label (highest confidence, inside the work area first).
          {"ok": false, "error": "..."}

Camera and coordinates:
  YOLO sees 640x480 frames, the same as its training images (--width/--height).
  The click-pick calibration is 1920x1080. The 640x480 view is the centre of the
  1920x1080 view scaled down 2.25x, so --to-calib "sx,sy,tx,ty" maps a point:
      u1080 = sx * u640 + tx,  v1080 = sy * v640 + ty
  (1440x1080 centre crop scaled 2.25x; fov_check.py measured 2.252,2.250,239.8,2.1 on 2026-10-26,
  within ~2 px. Re-run ~/main_project/yolo/fov_check.py if the camera or its modes change.)

Grasp point, the point omx_click_pick used to get from a human click:
  green_gauze (and others): mean of the two corners with the smallest x (left edge)
  blue_gauze:               mean of the two corners with the largest x (right edge)
  "grasp_uv_cam" is in 640x480, "grasp_uv" is the same point in 1920x1080 (sent to click pick).

Work area: a detection is used only when its grasp point is inside BOTH
  --roi (x1,y1,x2,y2 fractions of the 640x480 frame; default x 0~0.4, y 0.5~1,
         which leaves out the black box in the middle) and
  --region (1920x1080 pixel polygon, the click-pick regions_uv), when given.

The camera is opened per request and released right after. Full frames go to the model.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from ultralytics import YOLO


def log(*a):
    print("[yolo_worker]", *a, file=sys.stderr, flush=True)


def set_exposure(dev, value):
    real = os.path.realpath(dev)
    subprocess.run(["v4l2-ctl", "-d", real, "-c", "auto_exposure=3"], capture_output=True)
    if value is None or value < 0:
        return
    time.sleep(0.3)  # toggle through auto so the driver really applies the manual value
    subprocess.run(["v4l2-ctl", "-d", real, "-c", "auto_exposure=1",
                    "-c", f"exposure_time_absolute={value}"], capture_output=True)


def grab_frames(dev, n, exposure, width, height):
    busy = subprocess.run(["fuser", os.path.realpath(dev)], capture_output=True, text=True).stdout.strip()
    if busy:
        raise RuntimeError(f"{dev} is in use by PID {busy}")
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open {dev}")
        for _ in range(30):  # warm up; the camera resets exposure on open
            cap.read()
        set_exposure(dev, exposure)
        for _ in range(30):
            cap.read()
        frames = []
        for _ in range(n):
            ok, f = cap.read()
            if ok:
                frames.append(f)
        if not frames:
            raise RuntimeError("no frame from camera")
        h, w = frames[0].shape[:2]
        if (w, h) != (width, height):
            raise RuntimeError(f"camera gave {w}x{h}, expected {width}x{height}")
        return frames
    finally:
        cap.release()


RIGHT_EDGE_LABELS = ("blue_gauze",)  # grasp the right edge; every other label the left edge


def grasp_point(corners, label):
    """Mean of the two corners with the smallest x (left edge), or the largest x for blue_gauze.

    TODO (user, later): x-sorting can pick the top/bottom edge of a tall box once it is
    rotated; choose the steeper (more vertical) edges first. See ~/main_project/yolo/TODO.md.
    """
    by_x = sorted(corners, key=lambda p: p[0])
    two = by_x[2:] if label in RIGHT_EDGE_LABELS else by_x[:2]
    return [(two[0][0] + two[1][0]) / 2, (two[0][1] + two[1][1]) / 2]


class Area:
    """ROI in camera-frame fractions + optional click-pick region in calibration pixels."""
    def __init__(self, roi, region=None, to_calib=(1, 1, 0, 0)):
        self.roi = roi
        self.region = np.array(region, np.float32) if region else None
        self.sx, self.sy, self.tx, self.ty = to_calib

    def to_calib(self, uv):
        return [self.sx * uv[0] + self.tx, self.sy * uv[1] + self.ty]

    def to_cam(self, uv):
        return [(uv[0] - self.tx) / self.sx, (uv[1] - self.ty) / self.sy]

    def roi_polygon(self, w, h):
        x1, y1, x2, y2 = self.roi
        return np.array([[x1 * w, y1 * h], [x2 * w, y1 * h], [x2 * w, y2 * h], [x1 * w, y2 * h]], np.float32)

    def in_roi(self, uv_cam, w, h):
        return cv2.pointPolygonTest(self.roi_polygon(w, h), (float(uv_cam[0]), float(uv_cam[1])), False) >= 0

    def in_region(self, uv_calib):
        if self.region is None:
            return True
        return cv2.pointPolygonTest(self.region, (float(uv_calib[0]), float(uv_calib[1])), False) >= 0


def detect(model, frames, area, conf, device):
    names = model.names
    out = []
    for i, frame in enumerate(frames):
        h, w = frame.shape[:2]
        r = model.predict(frame, conf=conf, device=device, verbose=False)[0]
        if r.obb is None or not len(r.obb):
            continue
        for poly, xywhr, cls, cf in zip(r.obb.xyxyxyxy.cpu().numpy(), r.obb.xywhr.cpu().numpy(),
                                        r.obb.cls.cpu().numpy(), r.obb.conf.cpu().numpy()):
            cx, cy, bw, bh, ang = map(float, xywhr)
            corners = [[round(float(x), 1), round(float(y), 1)] for x, y in poly]
            cam = grasp_point(corners, names[int(cls)])
            calib = area.to_calib(cam)
            in_roi, in_region = bool(area.in_roi(cam, w, h)), bool(area.in_region(calib))
            out.append({
                "frame": i, "label": names[int(cls)], "conf": round(float(cf), 4),
                "grasp_uv": [round(v, 1) for v in calib], "grasp_uv_cam": [round(v, 1) for v in cam],
                "in_area": in_roi and in_region, "in_roi": in_roi, "in_region": in_region,
                "cx": round(cx, 1), "cy": round(cy, 1), "w": round(bw, 1), "h": round(bh, 1),
                "angle_deg": round(float(np.degrees(ang)), 1),
                "corners": corners, "image_size": [w, h],
            })
    return out


def best_per_label(dets):
    """One detection per label: the highest confidence inside the work area,
    or (when none is inside) the highest confidence anywhere, for the status/image."""
    best = {}
    for d in dets:
        key = d["label"]
        old = best.get(key)
        if old is None or (d["in_area"], d["conf"]) > (old["in_area"], old["conf"]):
            best[key] = d
    return sorted(best.values(), key=lambda d: -d["conf"])


def draw(frame, area, dets, chosen):
    h, w = frame.shape[:2]
    view = frame.copy()
    thick = max(2, w // 640)
    cv2.polylines(view, [area.roi_polygon(w, h).astype(np.int32)], True, (0, 255, 0), thick)
    if area.region is not None:  # click-pick region, mapped into this frame
        poly = np.array([area.to_cam(p) for p in area.region], np.int32)
        cv2.polylines(view, [poly], True, (0, 200, 255), 1)
    for d in dets:
        col = (0, 0, 255) if d is chosen else ((200, 200, 0) if d["in_area"] else (128, 128, 128))
        cv2.polylines(view, [np.array(d["corners"], np.int32)], True, col, thick)
        g = tuple(int(v) for v in d["grasp_uv_cam"])
        cv2.circle(view, g, 4 * thick, col, -1)
        cv2.putText(view, f"{d['label']} {d['conf']:.2f}", (g[0] + 8, g[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45 * thick, col, thick)
    return view


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--weights", required=True)
    p.add_argument("--cam-top", default="/dev/cam_top")
    p.add_argument("--width", type=int, default=640, help="YOLO frame size (= training images)")
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--roi", default="0,0.5,0.4,1.0", help="x1,y1,x2,y2 fractions of the YOLO frame")
    p.add_argument("--region", default="", help="click-pick polygon [[u,v],...] in calibration pixels")
    p.add_argument("--to-calib", default="2.25,2.25,240,0",
                   help="sx,sy,tx,ty: YOLO frame pixel -> calibration (1920x1080) pixel")
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--exposure", type=int, default=90)
    p.add_argument("--device", default="0")
    args = p.parse_args()
    area = Area([float(v) for v in args.roi.split(",")], json.loads(args.region) if args.region else None,
                [float(v) for v in args.to_calib.split(",")])

    model = YOLO(args.weights)
    model.predict(np.zeros((args.height, args.width, 3), np.uint8), device=args.device, verbose=False)
    log("ready", args.weights, "classes", dict(model.names))
    print(json.dumps({"ok": True, "ready": True, "classes": list(model.names.values())}), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("image"):
                frame = cv2.imread(req["image"])
                if frame is None:
                    raise RuntimeError(f"cannot read {req['image']}")
                frames = [frame]
            else:
                frames = grab_frames(args.cam_top, int(req.get("frames", 5)), args.exposure,
                                     args.width, args.height)
            dets = best_per_label(detect(model, frames, area, args.conf, args.device))
            target = req.get("target")
            cand = [d for d in dets if d["in_area"] and (target is None or d["label"] == target)]
            chosen = max(cand, key=lambda d: d["conf"]) if cand else None
            if req.get("save"):
                fi = chosen["frame"] if chosen else (dets[0]["frame"] if dets else len(frames) - 1)
                os.makedirs(os.path.dirname(req["save"]), exist_ok=True)
                cv2.imwrite(req["save"], draw(frames[fi], area, dets, chosen))
            reply = {"ok": True, "detection": chosen, "all": dets,
                     "frame_mean": round(float(frames[-1].mean()), 1)}
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
