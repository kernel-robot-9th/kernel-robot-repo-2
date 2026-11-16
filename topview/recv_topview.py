#!/usr/bin/env python3
"""gram: fastcampus 탑뷰 영상(RTP/H.264, UDP 5000)을 받아 OpenCV 창에 계속 출력.

사용: python3 recv_topview.py [--port 5000] [--width 1280 --height 720]
키: q 종료, s 현재 프레임을 PNG로 저장
frame(BGR numpy 배열)을 받는 부분(process_frame)에 원하는 처리를 넣으면 됨.
"""
import argparse, subprocess, time, sys
import numpy as np
import cv2

def process_frame(frame):
    # 여기에 이미지 처리 코드를 넣으면 됨 (frame: HxWx3 BGR uint8)
    return frame

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    a = ap.parse_args()
    w, h = a.width, a.height
    # 서버(수신기) 열기: UDP 포트로 RTP 받아서 디코딩 후 BGR raw 프레임을 stdout으로
    cmd = ["gst-launch-1.0", "-q",
           "udpsrc", f"port={a.port}",
           "caps=application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000",
           "!", "rtpjitterbuffer", "latency=50", "drop-on-latency=true",
           "!", "rtph264depay", "!", "h264parse", "!", "avdec_h264",
           "!", "videoconvert", "!", "videoscale",
           "!", f"video/x-raw,format=BGR,width={w},height={h}",
           "!", "fdsink", "fd=1", "sync=false"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w * h * 3)
    print(f"listening on UDP {a.port} ... (q: quit, s: save)", flush=True)
    size = w * h * 3
    n, t0 = 0, time.time()
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                print("stream ended", file=sys.stderr); break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            out = process_frame(frame)
            n += 1
            if time.time() - t0 >= 1:
                print(f"{n / (time.time() - t0):.1f} fps", flush=True); n, t0 = 0, time.time()
            cv2.imshow("topview (fastcampus)", out)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("s"):
                fn = time.strftime("topview_%Y%m%d_%H%M%S.png"); cv2.imwrite(fn, out); print("saved", fn)
    finally:
        p.terminate(); p.wait(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
