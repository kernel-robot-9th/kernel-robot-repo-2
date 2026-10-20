"""Record cameras to MP4 until SIGINT/SIGTERM (one file per camera, time stamp burned in).

  python3 -m vla_teleop.recorder <out_dir> <name>=<device> [<name>=<device> ...]
"""
import os
import signal
import sys
import threading
import time

import cv2

FPS = 15.0
SIZE = {'top': (1280, 720)}            # top camera captured at 1920x1080, stored smaller; others as captured


def record(name, device, out_dir, stop):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if name == 'top':
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    ok, frame = cap.read()
    if not ok:
        print(f'{name}: cannot read {device}', flush=True)
        return
    size = SIZE.get(name, (frame.shape[1], frame.shape[0]))
    path = os.path.join(out_dir, f'{name}.mp4')
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), FPS, size)
    frames, next_t = 0, time.time()
    while not stop.is_set():
        ok, frame = cap.read()
        if not ok:
            continue
        if time.time() < next_t:          # keep a steady FPS whatever the camera delivers
            continue
        next_t += 1.0 / FPS
        frame = cv2.resize(frame, size)
        cv2.putText(frame, time.strftime('%H:%M:%S') + f'.{int(time.time() * 10) % 10}', (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        writer.write(frame)
        frames += 1
    writer.release()
    cap.release()
    print(f'{name}: {frames} frames -> {path}', flush=True)


def main():
    out_dir = sys.argv[1]
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    threads = []
    for spec in sys.argv[2:]:
        name, device = spec.split('=', 1)
        threads.append(threading.Thread(target=record, args=(name, device, out_dir, stop)))
        threads[-1].start()
    print('recording', flush=True)
    for thread in threads:
        thread.join()


if __name__ == '__main__':
    main()
