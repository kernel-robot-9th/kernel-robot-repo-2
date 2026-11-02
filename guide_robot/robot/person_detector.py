"""Pinky용 사람 검출기: ONNX로 내보낸 YOLOv8n (COCO), onnxruntime 또는 OpenCV DNN으로 실행.

Pi에는 ultralytics/torch가 없음 (디스크에 들어가지 않았음). 모델은 노트북에서 한 번만 내보냄:
  pip install ultralytics
  yolo export model=yolov8n.pt format=onnx imgsz=320 opset=12      # -> yolov8n.onnx (~12 MB)
그다음 Pinky의 ~/guide_robot/models/yolov8n.onnx로 복사.

ROS 없이 Pinky에서 테스트:
  python3 robot/person_detector.py photo.jpg                 # 박스를 출력하고 photo_det.jpg 저장
  python3 robot/person_detector.py photo.jpg --bench 20      # 이 Pi에서의 속도

백엔드: onnxruntime이 설치되어 있으면 사용 (pip install onnxruntime, 보통 더 빠름), 아니면 cv2.dnn.
"""
from __future__ import annotations

import argparse
import os
import time

import cv2
import numpy as np

DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "models", "yolov8n.onnx")
PERSON = 0  # COCO 클래스 id


class PersonDetector:
    def __init__(self, model: str = DEFAULT_MODEL, imgsz: int = 320, conf: float = 0.4,
                 nms: float = 0.45, backend: str = "auto", threads: int = 2):
        model = os.path.expanduser(model)
        if not os.path.exists(model):
            raise FileNotFoundError(f"{model} not found: do step 3 (YOLO export) in guide.md")
        self.imgsz, self.conf, self.nms = imgsz, conf, nms
        self.sess = self.net = None
        if backend in ("auto", "ort"):
            try:
                import onnxruntime as ort
                so = ort.SessionOptions()
                so.intra_op_num_threads = threads  # RTAB-Map용 코어를 남겨 둠
                self.sess = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
                self.inp = self.sess.get_inputs()[0].name
                self.backend = "onnxruntime"
            except ImportError:
                if backend == "ort":
                    raise
        if self.sess is None:
            cv2.setNumThreads(threads)
            self.net = cv2.dnn.readNetFromONNX(model)
            self.backend = "cv2.dnn"

    def detect(self, bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """영상 속 사람들: `bgr` 픽셀 기준 [(x1, y1, x2, y2, score)]."""
        h, w = bgr.shape[:2]
        s = self.imgsz / max(h, w)
        nw, nh = int(round(w * s)), int(round(h * s))
        pad = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)  # 레터박스, 영상은 왼쪽 위 모서리에
        pad[:nh, :nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = cv2.dnn.blobFromImage(pad, 1 / 255.0, (self.imgsz, self.imgsz), swapRB=True)
        if self.sess is not None:
            out = self.sess.run(None, {self.inp: blob})[0]
        else:
            self.net.setInput(blob)
            out = self.net.forward()
        return self.decode(out, s, w, h)

    def decode(self, out: np.ndarray, s: float, w: int, h: int):
        out = np.squeeze(out, 0)
        if out.shape[0] < out.shape[1]:  # YOLOv8: (84, N) -> (N, 84)
            out = out.T
        scores = out[:, 4 + PERSON]
        keep = scores > self.conf
        if not keep.any():
            return []
        b, sc = out[keep, :4] / s, scores[keep]
        x1 = np.clip(b[:, 0] - b[:, 2] / 2, 0, w)
        y1 = np.clip(b[:, 1] - b[:, 3] / 2, 0, h)
        x2 = np.clip(b[:, 0] + b[:, 2] / 2, 0, w)
        y2 = np.clip(b[:, 1] + b[:, 3] / 2, 0, h)
        rects = [[float(a), float(c), float(e - a), float(f - c)] for a, c, e, f in zip(x1, y1, x2, y2)]
        idx = cv2.dnn.NMSBoxes(rects, sc.astype(float).tolist(), self.conf, self.nms)
        idx = np.array(idx).flatten()
        return [(float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i]), float(sc[i])) for i in idx]


def draw(img: np.ndarray, boxes) -> np.ndarray:
    for x1, y1, x2, y2, s in boxes:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
        cv2.putText(img, f"person {s:.2f}", (int(x1), max(12, int(y1) - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--backend", default="auto", choices=["auto", "ort", "cv2"])
    ap.add_argument("--bench", type=int, default=0, help="N번 실행 시간 측정")
    a = ap.parse_args()
    det = PersonDetector(a.model, conf=a.conf, backend=a.backend)
    img = cv2.imread(a.image)
    if img is None:
        raise SystemExit(f"could not read {a.image}")
    boxes = det.detect(img)
    print(f"{det.backend}: {len(boxes)} person(s)")
    for b in boxes:
        print("  x1=%.0f y1=%.0f x2=%.0f y2=%.0f  conf=%.2f" % b)
    out = os.path.splitext(a.image)[0] + "_det.jpg"
    cv2.imwrite(out, draw(img.copy(), boxes))
    print("->", out)
    if a.bench:
        t = time.perf_counter()
        for _ in range(a.bench):
            det.detect(img)
        dt = (time.perf_counter() - t) / a.bench
        print(f"{dt * 1000:.0f} ms / frame  (~{1 / dt:.1f} Hz)")


if __name__ == "__main__":
    main()
