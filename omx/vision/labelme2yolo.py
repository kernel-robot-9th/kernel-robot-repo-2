#!/usr/bin/env python3
"""Convert labelme json files to a YOLO detection dataset.

Put each labelme json next to its image (same file name, .json instead of .jpg).
Default (detect): every shape becomes an axis-aligned box.
--obb: rotated rectangles keep their angle (4 corners, YOLO OBB format);
       plain rectangles get angle 0; polygons with >4 points use their min-area rotated box.

Usage (conda env vision_project):
    python labelme2yolo.py datasets/topcam_raw/objects1
    python labelme2yolo.py datasets/topcam_raw/objects1 datasets/topcam_raw/objects2 --val 0.2
    python labelme2yolo.py datasets/topcam_raw/objects1 --classes green_cup,blue_cup,cube
    python labelme2yolo.py datasets/topcam_raw/objects1 --obb   # -> datasets/topcam_obb

Output (rebuilt every run):
    datasets/topcam_yolo/images/{train,val}/*.jpg
    datasets/topcam_yolo/labels/{train,val}/*.txt
    datasets/topcam_yolo/data.yaml
"""
import argparse
import glob
import json
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def corners_of(s):
    """4 corner points of a shape (rectangle, rotated rectangle or polygon)."""
    pts = [tuple(map(float, p[:2])) for p in (s.get("points") or [])]
    st = s.get("shape_type") or "polygon"
    if st in ("point", "line", "linestrip", "circle", "mask") or len(pts) < 2:
        return None
    if len(pts) == 2:  # axis-aligned rectangle: two opposite corners
        (x1, y1), (x2, y2) = pts
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if len(pts) == 4:  # rotated rectangle or 4-point polygon
        return pts
    import cv2
    import numpy as np
    box = cv2.boxPoints(cv2.minAreaRect(np.array(pts, dtype=np.float32)))
    return [tuple(map(float, p)) for p in box]


def shapes_to_boxes(data, obb=False):
    """Yield (label, values). detect: cx cy w h. obb: x1 y1 ... x4 y4. All normalized."""
    w, h = data["imageWidth"], data["imageHeight"]
    for s in data.get("shapes", []):
        c = corners_of(s)
        if c is None:
            print(f"  skip shape '{s.get('label')}' ({s.get('shape_type')})")
            continue
        c = [(min(max(x, 0), w), min(max(y, 0), h)) for x, y in c]
        xs, ys = [x for x, _ in c], [y for _, y in c]
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            continue
        if obb:
            yield s["label"], tuple(v for x, y in c for v in (x / w, y / h))
        else:
            x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
            yield s["label"], ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src", nargs="+", help="folders with images + labelme json")
    p.add_argument("--out", default=os.path.join(HERE, "datasets/topcam_yolo"))
    p.add_argument("--val", type=float, default=0.2, help="validation fraction")
    p.add_argument("--classes", default="", help="comma list to fix class order (default: sorted labels)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--obb", action="store_true",
                   help="oriented boxes (4 corners) for yolo26*-obb; default out datasets/topcam_obb")
    args = p.parse_args()
    if args.obb and args.out == p.get_default("out"):
        args.out = os.path.join(HERE, "datasets/topcam_obb")
    args.out = os.path.abspath(args.out)

    items = []  # (image path, labelme data)
    for src in args.src:
        for js in sorted(glob.glob(os.path.join(src, "*.json"))):
            with open(js) as f:
                data = json.load(f)
            img = os.path.join(os.path.dirname(js), os.path.basename(data.get("imagePath") or ""))
            if not os.path.isfile(img):
                img = os.path.splitext(js)[0] + ".jpg"
            if not os.path.isfile(img):
                print(f"  no image for {js}, skipped")
                continue
            items.append((img, data))
    if not items:
        sys.exit("No labelme json found.")

    labels = sorted({lab for _, d in items for lab, _ in shapes_to_boxes(d, args.obb)})
    classes = [c.strip() for c in args.classes.split(",") if c.strip()] or labels
    unknown = set(labels) - set(classes)
    if unknown:
        sys.exit(f"Labels not in --classes: {sorted(unknown)}")
    cid = {c: i for i, c in enumerate(classes)}

    random.Random(args.seed).shuffle(items)
    n_val = max(1, round(len(items) * args.val)) if len(items) > 1 else 0

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    counts = {c: 0 for c in classes}
    for i, (img, data) in enumerate(items):
        split = "val" if i < n_val else "train"
        os.makedirs(os.path.join(args.out, "images", split), exist_ok=True)
        os.makedirs(os.path.join(args.out, "labels", split), exist_ok=True)
        stem = os.path.splitext(os.path.basename(img))[0]
        shutil.copy2(img, os.path.join(args.out, "images", split, stem + ".jpg"))
        lines = []
        for lab, vals in shapes_to_boxes(data, args.obb):
            lines.append(f"{cid[lab]} " + " ".join(f"{v:.6f}" for v in vals))
            counts[lab] += 1
        with open(os.path.join(args.out, "labels", split, stem + ".txt"), "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

    with open(os.path.join(args.out, "data.yaml"), "w") as f:
        f.write(f"path: {args.out}\ntrain: images/train\nval: images/val\nnames:\n")
        for i, c in enumerate(classes):
            f.write(f"  {i}: {c}\n")

    print(f"{len(items)} images -> train {len(items) - n_val}, val {n_val}")
    for c in classes:
        print(f"  {cid[c]} {c}: {counts[c]} boxes")
    print(f"data.yaml: {os.path.join(args.out, 'data.yaml')}")


if __name__ == "__main__":
    main()
