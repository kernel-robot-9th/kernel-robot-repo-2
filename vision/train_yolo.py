#!/usr/bin/env python3
"""Train a YOLO detector on the top-camera dataset (GPU).

Usage (conda env vision_project):
    python train_yolo.py                              # yolo26s, 100 epochs
    python train_yolo.py --model yolo26n.pt --epochs 150
    python train_yolo.py --name objects_v2
    python train_yolo.py --obb --name objects_obb     # rotated boxes, yolo26s-obb

Results: runs/{detect,obb}/<name>/weights/best.pt
"""
import argparse
import os

from ultralytics import YOLO

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--obb", action="store_true", help="oriented boxes: yolo26s-obb + datasets/topcam_obb")
    p.add_argument("--data", default="")
    p.add_argument("--model", default="")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default="0", help="0 = GPU, cpu = CPU")
    p.add_argument("--name", default="topcam")
    args = p.parse_args()
    ds = "topcam_obb" if args.obb else "topcam_yolo"
    args.data = args.data or os.path.join(HERE, "datasets", ds, "data.yaml")
    args.model = args.model or os.path.join(HERE, "yolo26s-obb.pt" if args.obb else "yolo26s.pt")
    task_dir = "obb" if args.obb else "detect"

    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=os.path.join(HERE, "runs", task_dir),
        name=args.name,
        patience=30,
        fliplr=0.5,
        workers=4,
    )
    print("best weights:", os.path.join(str(model.trainer.save_dir), "weights/best.pt"))


if __name__ == "__main__":
    main()
