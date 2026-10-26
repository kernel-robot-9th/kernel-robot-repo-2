# YOLO on the top camera

Environment: `conda activate vision_project` (ultralytics 8.4, CPU torch).

Weights in this folder: yolo11n/s, yolov8n/s (detection), yolov8s/m-worldv2 (YOLO-World, CLIP text model in `weights/clip/`).

## Collect top-view images

Stop record/eval/teleop first (only one process can open `/dev/cam_top`).

```bash
conda activate vision_project
cd ~/main_project/yolo
python capture_topcam.py --session gauze_day1
```

- Same camera settings as record_bi.sh / eval_bi.sh: 640x480 MJPG 30fps, manual exposure 90.
- Keys: `SPACE`/`s` save one frame, `a` auto-save on/off (every `--interval` s, default 1.0), `q`/`ESC` quit.
- Saved frames are clean (no overlay), JPEG q95:
  `~/main_project/yolo/datasets/topcam_raw/<session>/topcam_YYYYmmdd_HHMMSS_ms.jpg`
- Useful options: `--interval 0.5`, `--auto` (start with auto-save on), `--skip-similar 4` (auto mode skips near-identical frames),
  `--exposure -1` (auto exposure), `--count N`, `--headless` (no window, auto-save).

## Train (labelme → YOLO26, GPU)

`vision_project` now has GPU torch (2.7.1+cu128, RTX 5080).

1. Capture: `python capture_enter.py --session objects1` (ENTER = save, ESC = quit).
2. Label in labelme with `labelme --nodata` (or File → uncheck "Save With Image Data"),
   save each json next to its image in `datasets/topcam_raw/<session>/`.
3. Convert: `python labelme2yolo.py datasets/topcam_raw/objects1 [more folders] --val 0.2`
   → `datasets/topcam_yolo/` + `data.yaml` (rectangles and polygons → boxes; classes sorted by name, or fix order with `--classes a,b,c`).
4. Train: `python train_yolo.py --name objects_v1` (default yolo26s.pt, 100 epochs, 640, batch 16, GPU)
   → `runs/detect/objects_v1/weights/best.pt`.

### Rotated boxes (OBB)
Label with labelme's rotated rectangle, then
`python labelme2yolo.py datasets/topcam_raw/objects1 --obb` (→ `datasets/topcam_obb`) and
`python train_yolo.py --obb --name objects_obb` (yolo26s-obb.pt → `runs/obb/objects_obb/weights/best.pt`).
Plain rectangles in an OBB set get angle 0; polygons with >4 points use their min-area rotated box.
