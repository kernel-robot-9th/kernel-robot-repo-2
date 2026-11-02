"""Pause / resume every arm motion when the emergency server sees a person (eval_bi_api_yolo_botharm_v2.py).

The server writes one character to PAUSE_FILE ("1" = paused, "0" = go). Every motion loop reads it:
  - click pick (child process, omxtest MotionController.ramp): patch_ramp() holds the last goal
    while paused and continues the same ramp afterwards.
  - home moves (eval_bi.return_to_start) and the pinky sequence (pinky_move.run_sequence) are
    time-based: they get a PausableClock, a clock that stops while paused, so the interpolation
    keeps sending the same pose (= hold) and goes on from there when resumed.
With OMX_SAFETY=1 in the environment (set by the server) a missing file counts as paused.
Torque stays on while paused, so a held gauze is not dropped.
"""
import os
import threading
import time
from pathlib import Path

PAUSE_FILE = Path(os.environ.get("OMX_PAUSE_FILE", "/dev/shm/omx_pause"))
_real_perf = time.perf_counter
_real_sleep = time.sleep


def paused():
    try:
        return PAUSE_FILE.read_text().strip() == "1"
    except OSError:
        return os.environ.get("OMX_SAFETY") == "1"


def set_paused(value):
    tmp = PAUSE_FILE.with_name(PAUSE_FILE.name + f".{os.getpid()}.tmp")
    tmp.write_text("1" if value else "0")
    os.replace(tmp, PAUSE_FILE)


def log(text):
    print(f"[SAFETY] {text}", flush=True)


def wait_while_paused(where, poll=0.05):
    """Block while paused (logs once). Returns the seconds spent paused."""
    if not paused():
        return 0.0
    began = _real_perf()
    log(f"paused at {where} (torque on, holding)")
    while paused():
        _real_sleep(poll)
    took = _real_perf() - began
    log(f"resume {where} after {took:.1f} s")
    return took


class PausableClock:
    """perf_counter that does not advance while paused (shared by all threads)."""
    def __init__(self, name="motion"):
        self.name = name
        self.offset = 0.0
        self.since = None
        self.lock = threading.Lock()

    def __call__(self):
        now = _real_perf()
        stop = paused()
        with self.lock:
            if stop and self.since is None:
                self.since = now
                log(f"paused during {self.name} (torque on, holding)")
            elif not stop and self.since is not None:
                self.offset += now - self.since
                log(f"resume {self.name} after {now - self.since:.1f} s")
                self.since = None
            return (self.since if self.since is not None else now) - self.offset


class _TimeProxy:
    """Stands in for the time module inside one module: perf_counter pauses, the rest is real."""
    def __init__(self, clock):
        self.perf_counter = clock

    def __getattr__(self, name):
        return getattr(time, name)


def patch_time_module(module, name):
    """module.time.perf_counter -> PausableClock (e.g. eval_bi for return_to_start)."""
    module.time = _TimeProxy(PausableClock(name))


def patch_ramp(motion_controller_class):
    """omxtest pick_robot.MotionController.ramp with a hold while paused (same motion otherwise)."""
    import math
    import pick_robot

    def ramp(self, targets, seconds=None):
        start = {i: self.bus.read(i, 132, 4) for i in targets}
        if 15 in targets:
            targets = dict(targets)
            targets[15] = pick_robot.nearest_wrist(targets[15], start[15])
            self.emit("wrist_goal", dict(present=start[15], goal=targets[15]))
        seconds = self.cfg["stage_seconds"] if seconds is None else seconds
        steps = max(1, math.ceil(seconds / 0.05))
        sent = start.copy()
        for motor_id, value in start.items():
            self.bus.write(motor_id, 116, 4, value)
        for step in range(1, steps + 1):
            if paused():  # the last goal stays: the arm holds where it is
                self.emit("safety_pause", {"step": step, "of": steps})
                wait_while_paused(f"ramp step {step}/{steps}")
            began = time.monotonic()
            t = step / steps
            blend = t * t * (3 - 2 * t)
            for motor_id, target in targets.items():
                value = round(start[motor_id] + blend * (target - start[motor_id]))
                if value != sent[motor_id] or step == steps:
                    self.bus.write(motor_id, 116, 4, value)
                    sent[motor_id] = value
            time.sleep(max(0, seconds / steps - (time.monotonic() - began)))
        time.sleep(self.cfg.get("stage_pause_seconds", 0.5))

    motion_controller_class.ramp = ramp
