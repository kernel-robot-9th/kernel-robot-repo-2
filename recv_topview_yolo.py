#!/usr/bin/env python3
"""fastcampus 탑뷰 영상(RTP/H.264, UDP 5000)을 받아 YOLO 사람 검출 결과를 OpenCV 창에 출력하고,
로봇 서버(fastcampus eval_bi_api_yolo_botharm_v2.py)에 사람 유무를 계속 보냄.

사용: .venv/bin/python recv_topview_yolo.py --robot-url http://<fastcampus IP>:8000 [--port 5000] [--device 0]
사용(AWS 경유): .venv/bin/python recv_topview_yolo.py --srt <EC2 IP> [--latency 200]
키: q 종료, s 현재 프레임을 PNG로 저장
--device: 0 = 첫 번째 NVIDIA GPU (omen), cpu = CPU (gram)

로봇 정지 신호 (--robot-url을 주면):
  POST <robot-url>/safety {"person_exist": true|false, ...}  --send-interval(0.2 s)마다 계속 보냄.
  - true : 최근 --window(10) 프레임 중 --on-frames(7) 프레임 이상에서 사람이 보이면 바로
  - false: 사람이 --off-seconds(2 s) 동안 한 번도 안 보이면
  - 영상이 --stale(0.5 s) 넘게 안 들어오면 true (영상이 끊겼는데 false를 보내지 않도록)
  이 프로그램이 꺼지거나 네트워크가 끊기면 신호가 안 가고, 로봇 서버가 1초 뒤 스스로 멈춤.
"""
import argparse, json, subprocess, threading, time, sys, urllib.request
from collections import deque
import numpy as np
import cv2
from ultralytics import YOLO

model = None
args = None
_fps = 0.0


class PersonState:
    """Frames -> person_exist with a quick on (on_frames of window) and a slow off (off_seconds)."""
    def __init__(self, window, on_frames, off_seconds, stale):
        self.hist = deque(maxlen=window)
        self.on_frames, self.off_seconds, self.stale = on_frames, off_seconds, stale
        self.person = False
        self.last_person = 0.0
        self.last_frame = None
        self.count = 0
        self.lock = threading.Lock()

    def frame(self, count, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.last_frame, self.count = now, count
            self.hist.append(count > 0)
            if count > 0:
                self.last_person = now
            seen = sum(self.hist)
            if not self.person and seen >= self.on_frames:
                self.person = True
                log(f"person_exist -> true ({seen}/{len(self.hist)} frames with a person)")
            elif self.person and now - self.last_person >= self.off_seconds:
                self.person = False
                self.hist.clear()
                log(f"person_exist -> false (no person for {self.off_seconds:g} s)")

    def value(self, now=None):
        """(person_exist to send, reason)."""
        now = time.time() if now is None else now
        with self.lock:
            if self.last_frame is None:
                return True, "no video yet"
            if now - self.last_frame > self.stale:
                return True, f"no video for {now - self.last_frame:.1f} s"
            return self.person, "person" if self.person else "clear"


def log(text):
    print(f"[{time.strftime('%H:%M:%S')}] [SAFETY] {text}", flush=True)


def sender(state, url, interval):
    """POST person_exist every interval; logs what changes and send errors (not every packet)."""
    seq, last_sent, last_err, ok_since_err = 0, None, None, True
    while True:
        began = time.time()
        person, reason = state.value(began)
        seq += 1
        body = json.dumps({"person_exist": person, "reason": reason, "persons": state.count,
                           "seq": seq, "sent_at": began}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=max(0.1, interval * 1.5)) as r:
                r.read()
            if not ok_since_err:
                log(f"robot server reachable again ({url})")
            ok_since_err = True
            if (person, reason.split(" ")[0]) != last_sent:
                log(f"sent person_exist={str(person).lower()} ({reason})")
                last_sent = (person, reason.split(" ")[0])
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            if ok_since_err or err != last_err:
                log(f"send failed to {url}: {err} (robot stops by itself after 1 s)")
            ok_since_err, last_err = False, err
        time.sleep(max(0.0, interval - (time.time() - began)))


def process_frame(frame, state=None):
    r = model(frame, imgsz=args.imgsz, classes=[0], conf=args.conf, device=args.device, half=args.half, verbose=False)[0]
    out = r.plot()
    cnt = len(r.boxes)
    if state is not None:
        state.frame(cnt)
        person, reason = state.value()
        col = (0, 0, 255) if person else (0, 200, 0)
        cv2.putText(out, f"ROBOT {'STOP' if person else 'GO'} ({reason})", (10, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2, cv2.LINE_AA)
    cv2.putText(out, f"persons: {cnt}  fps: {_fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
    return out

def main():
    global model, args, _fps
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--model", default="yolo26s.pt")
    ap.add_argument("--device", default="0")
    ap.add_argument("--half", action="store_true", help="FP16 (GPU only)")
    ap.add_argument("--srt", default=None, help="AWS 중계 서버 IP (지정하면 UDP 대신 SRT로 받음)")
    ap.add_argument("--srt-port", type=int, default=8890)
    ap.add_argument("--streamid", default="read:topview")
    ap.add_argument("--latency", type=int, default=200, help="SRT 버퍼(ms)")
    ap.add_argument("--conf", type=float, default=0.5, help="person confidence")
    ap.add_argument("--robot-url", default=None,
                    help="fastcampus robot server, e.g. http://10.42.0.xx:8000 (POST /safety); none = display only")
    ap.add_argument("--send-interval", type=float, default=0.2)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--on-frames", type=int, default=7)
    ap.add_argument("--off-seconds", type=float, default=2.0)
    ap.add_argument("--stale", type=float, default=0.5, help="no frame for this long -> person_exist true")
    args = a = ap.parse_args()
    model = YOLO(a.model)
    model(np.zeros((a.height, a.width, 3), np.uint8), imgsz=a.imgsz, classes=[0], device=a.device, half=a.half, verbose=False)  # warm-up
    state = None
    if a.robot_url:
        state = PersonState(a.window, a.on_frames, a.off_seconds, a.stale)
        url = a.robot_url.rstrip("/") + "/safety"
        threading.Thread(target=sender, args=(state, url, a.send_interval), daemon=True).start()
        log(f"sending person_exist to {url} every {a.send_interval:g} s "
            f"(on: {a.on_frames}/{a.window} frames, off: {a.off_seconds:g} s, no video {a.stale:g} s -> true)")
    else:
        print("no --robot-url: display only, the robot gets no person_exist", flush=True)
    w, h = a.width, a.height
    if a.srt:
        # 다른 와이파이: AWS MediaMTX에서 SRT(MPEG-TS)로 받기
        src = ["srtsrc", f"uri=srt://{a.srt}:{a.srt_port}", f"streamid={a.streamid}", f"latency={a.latency}",
               "!", "tsdemux"]
    else:
        # 같은 와이파이: UDP RTP로 직접 받기
        src = ["udpsrc", f"port={a.port}",
               "caps=application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000",
               "!", "rtpjitterbuffer", "latency=50", "drop-on-latency=true",
               "!", "rtph264depay"]
    cmd = ["gst-launch-1.0", "-q", *src,
           "!", "h264parse", "!", "avdec_h264",
           "!", "videoconvert", "!", "videoscale",
           "!", f"video/x-raw,format=BGR,width={w},height={h}",
           "!", "fdsink", "fd=1", "sync=false"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w * h * 3)
    where = f"SRT {a.srt}:{a.srt_port} ({a.streamid})" if a.srt else f"UDP {a.port}"
    print(f"listening on {where} ... (q: quit, s: save)", flush=True)
    size = w * h * 3
    n, t0 = 0, time.time()
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                print("stream ended", file=sys.stderr); break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            out = process_frame(frame, state)
            n += 1
            if time.time() - t0 >= 1:
                _fps = n / (time.time() - t0)
                print(f"{_fps:.1f} fps", flush=True); n, t0 = 0, time.time()
            cv2.imshow("topview YOLO (fastcampus)", out)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("s"):
                fn = time.strftime("topview_yolo_%Y%m%d_%H%M%S.png"); cv2.imwrite(fn, out); print("saved", fn)
    finally:
        p.terminate(); p.wait(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
