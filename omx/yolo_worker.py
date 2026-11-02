#!/usr/bin/env python3
"""YOLO gauze detector process for eval_bi_api_yolo.py (runs in conda env vision_project).

The robot env (main_project) has no ultralytics, so the API server starts this file with
the vision_project python and talks to it with one JSON line per request on stdin/stdout.

Request:  {"target": "blue_gauze" | null, "frames": 5, "save": "/path/out.jpg" | null}
          optional "image": "/path/frame.jpg" uses that file instead of the camera (testing)
          optional "roi" [x1,y1,x2,y2] / "region" [[u,v],...] | null / "conf": this request's work area
                   (eval_bi_api_yolo_botharm.py: one worker serves both arms)
          optional "weights": another model file (loaded once, kept)
          optional "after": epoch seconds; with --keep-open the frames are the first ones taken
                   at or after this time (the moment the arm asked), even if the request waited
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
  the two box edges closer to vertical in the picture are the side edges (works up to +-45 deg);
  green_gauze (and others): middle of the left side edge
  blue_gauze:               middle of the right side edge
  "grasp_edge" is that edge in 1920x1080 (click_pick_yolo.py --edge rotates the wrist to it).
  "grasp_uv_cam" is in 640x480, "grasp_uv" is the same point in 1920x1080 (sent to click pick).

Work area: a detection is used only when its grasp point is inside BOTH
  --roi (x1,y1,x2,y2 fractions of the 640x480 frame; default x 0~0.4, y 0.5~1,
         which leaves out the black box in the middle) and
  --region (1920x1080 pixel polygon, the click-pick regions_uv), when given.

The camera is opened per request and released right after (default), or with --keep-open
opened once at start and read all the time by a thread (last ~3 s of frames kept), so a request
only picks frames and never waits for the camera. Full frames go to the model.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import threading
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


class LiveCamera:
    """--keep-open: the camera stays open; a thread keeps reading so the newest frames are always ready.

    frames_after(t, n) returns the first n frames taken at or after time t (epoch seconds), waiting for
    them if t is now. The thread reopens the camera if reads keep failing.
    """
    def __init__(self, dev, exposure, width, height, keep_s=3.0):
        self.dev, self.exposure, self.width, self.height = dev, exposure, width, height
        self.buf = collections.deque(maxlen=int(30 * keep_s))
        self.cond = threading.Condition()
        self.error = None
        self.cap = self._open()
        threading.Thread(target=self._loop, daemon=True, name="camera").start()

    def _open(self):
        busy = subprocess.run(["fuser", os.path.realpath(self.dev)], capture_output=True, text=True).stdout.strip()
        if busy:
            raise RuntimeError(f"{self.dev} is in use by PID {busy}")
        cap = cv2.VideoCapture(self.dev, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open {self.dev}")
        for _ in range(30):  # warm up; the camera resets exposure on open
            cap.read()
        set_exposure(self.dev, self.exposure)
        for _ in range(30):
            cap.read()
        ok, f = cap.read()
        if not ok:
            cap.release()
            raise RuntimeError("no frame from camera")
        h, w = f.shape[:2]
        if (w, h) != (self.width, self.height):
            cap.release()
            raise RuntimeError(f"camera gave {w}x{h}, expected {self.width}x{self.height}")
        log("camera open (kept open)", self.dev)
        return cap

    def _loop(self):
        fails = 0
        while True:
            ok, f = self.cap.read()
            if ok:
                fails = 0
                with self.cond:
                    self.buf.append((time.time(), f))
                    self.error = None
                    self.cond.notify_all()
                continue
            fails += 1
            time.sleep(0.05)
            if fails >= 20:  # ~1 s without frames: reopen
                log("camera reads failing, reopening")
                self.cap.release()
                try:
                    self.cap = self._open()
                    fails = 0
                except Exception as exc:
                    with self.cond:
                        self.error = f"{type(exc).__name__}: {exc}"
                        self.cond.notify_all()
                    time.sleep(1.0)

    def frames_after(self, t, n, timeout=3.0):
        end = time.time() + timeout
        with self.cond:
            while True:
                got = [f for ts, f in self.buf if ts >= t][:n]
                if len(got) >= n:
                    return got
                left = end - time.time()
                if left <= 0:
                    if got:
                        return got
                    raise RuntimeError(f"no new camera frame in {timeout:.0f} s" +
                                       (f" ({self.error})" if self.error else ""))
                self.cond.wait(left)


RIGHT_EDGE_LABELS = ("blue_gauze",)  # grasp the right edge; every other label the left edge


def side_edges(corners):
    """The two box edges closer to vertical in the picture (|dy| >= |dx|), as [[x, y], [x, y]] pairs.

    YOLO's corner order says nothing about the gauze's real corners, so the edges are chosen by
    direction instead of by x: this stays right for any rotation within +-45 deg of upright.
    """
    edges = [[corners[i], corners[(i + 1) % 4]] for i in range(4)]
    steep = lambda e: abs(e[1][1] - e[0][1]) - abs(e[1][0] - e[0][0])
    pair_a, pair_b = (edges[0], edges[2]), (edges[1], edges[3])  # opposite edges
    return list(pair_a if sum(map(steep, pair_a)) >= sum(map(steep, pair_b)) else pair_b)


def grasp_edge(corners, label):
    """Edge to grasp: left one of the two side edges, or the right one for blue_gauze.
    Returned top point first, so the edge direction is always "down the picture"."""
    mid = lambda e: ((e[0][0] + e[1][0]) / 2, (e[0][1] + e[1][1]) / 2)
    a, b = side_edges(corners)
    left, right = (a, b) if mid(a)[0] <= mid(b)[0] else (b, a)
    edge = right if label in RIGHT_EDGE_LABELS else left
    return sorted(edge, key=lambda p: p[1])


def grasp_point(corners, label):
    """Middle of the grasp edge (left side edge; right side edge for blue_gauze)."""
    e = grasp_edge(corners, label)
    return [(e[0][0] + e[1][0]) / 2, (e[0][1] + e[1][1]) / 2]


def edge_tilt_deg(edge):
    """Picture angle of the edge from vertical, + = top leans right (clockwise on screen)."""
    (x1, y1), (x2, y2) = edge
    return float(np.degrees(np.arctan2(x1 - x2, y2 - y1)))


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
            edge = grasp_edge(corners, names[int(cls)])
            cam = grasp_point(corners, names[int(cls)])
            calib = area.to_calib(cam)
            in_roi, in_region = bool(area.in_roi(cam, w, h)), bool(area.in_region(calib))
            out.append({
                "frame": i, "label": names[int(cls)], "conf": round(float(cf), 4),
                "grasp_uv": [round(v, 1) for v in calib], "grasp_uv_cam": [round(v, 1) for v in cam],
                "in_area": in_roi and in_region, "in_roi": in_roi, "in_region": in_region,
                "cx": round(cx, 1), "cy": round(cy, 1), "w": round(bw, 1), "h": round(bh, 1),
                "angle_deg": round(float(np.degrees(ang)), 1),
                # grasp edge (top point first) in 1920x1080 and its tilt in the 640x480 picture;
                # click_pick_yolo.py --edge turns it into a table angle for the wrist (ID15)
                "grasp_edge": [[round(v, 1) for v in area.to_calib(p)] for p in edge],
                "edge_tilt_deg": round(edge_tilt_deg(edge), 1),
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
        edge = np.array([area.to_cam(p) for p in d["grasp_edge"]], np.int32)
        cv2.line(view, tuple(map(int, edge[0])), tuple(map(int, edge[1])), (255, 0, 255), 2 * thick)
        g = tuple(int(v) for v in d["grasp_uv_cam"])
        cv2.circle(view, g, 4 * thick, col, -1)
        cv2.putText(view, f"{d['label']} {d['conf']:.2f} tilt {d['edge_tilt_deg']:+.0f}", (g[0] + 8, g[1] - 8),
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
    p.add_argument("--keep-open", action="store_true",
                   help="open the camera once and keep reading it (requests pick frames by time)")
    args = p.parse_args()
    area = Area([float(v) for v in args.roi.split(",")], json.loads(args.region) if args.region else None,
                [float(v) for v in args.to_calib.split(",")])

    to_calib = [float(v) for v in args.to_calib.split(",")]
    model = YOLO(args.weights)
    model.predict(np.zeros((args.height, args.width, 3), np.uint8), device=args.device, verbose=False)
    models = {os.path.realpath(args.weights): model}
    camera = LiveCamera(args.cam_top, args.exposure, args.width, args.height) if args.keep_open else None
    log("ready", args.weights, "classes", dict(model.names))
    print(json.dumps({"ok": True, "ready": True, "classes": list(model.names.values())}), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            asked = req.get("after") or time.time()
            use = model
            if req.get("weights"):
                key = os.path.realpath(req["weights"])
                if key not in models:
                    log("loading", key)
                    models[key] = YOLO(key)
                use = models[key]
            req_area = area
            if "roi" in req or "region" in req:
                roi = req.get("roi", area.roi)
                roi = [float(v) for v in (roi.split(",") if isinstance(roi, str) else roi)]
                region = req["region"] if "region" in req else (area.region.tolist() if area.region is not None else None)
                req_area = Area(roi, region, to_calib)
            if req.get("image"):
                frame = cv2.imread(req["image"])
                if frame is None:
                    raise RuntimeError(f"cannot read {req['image']}")
                frames = [frame]
            elif camera is not None:
                frames = camera.frames_after(asked, int(req.get("frames", 5)))
            else:
                frames = grab_frames(args.cam_top, int(req.get("frames", 5)), args.exposure,
                                     args.width, args.height)
            dets = best_per_label(detect(use, frames, req_area, float(req.get("conf", args.conf)), args.device))
            target = req.get("target")
            cand = [d for d in dets if d["in_area"] and (target is None or d["label"] == target)]
            chosen = max(cand, key=lambda d: d["conf"]) if cand else None
            if req.get("save"):
                fi = chosen["frame"] if chosen else (dets[0]["frame"] if dets else len(frames) - 1)
                os.makedirs(os.path.dirname(req["save"]), exist_ok=True)
                cv2.imwrite(req["save"], draw(frames[fi], req_area, dets, chosen))
            reply = {"ok": True, "detection": chosen, "all": dets,
                     "frame_mean": round(float(frames[-1].mean()), 1),
                     "waited_s": round(time.time() - asked, 2)}
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
