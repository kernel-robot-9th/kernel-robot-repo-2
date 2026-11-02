"""eval_bi_api_yolo.py for both arms: one command lists targets and counts, left and right work at once.

POST /command {"command": {"blue": 1, "green": 1}, "request_id": "cycle-001"}
  (a string works too: "blue:1, green:1", '{"blue":1,"green":0}', or the old "pick and place blue gauze")
  key = what to pick, value = how many times (0 = skip).
  green -> left arm  (green_gauze, omxtest-main single, ROI --roi)
  blue  -> right arm (blue_gauze,  omxtest-main --arm right, ROI --right-roi)
  (--left-targets / --right-targets change who picks what.)
  Each arm goes through its own targets in the command's order, the two arms at the same time.
  One try = YOLO at home -> click pick HIGH ... RETREAT -> [bin] CARRY_HIGH -> DROP_RELEASE -> RELEASE
            -> RETURN_HIGH [/bin] -> home (torque off).

Shared bin: CARRY_HIGH .. RETURN_HIGH is over the bin for both arms. The first arm to reach CARRY_HIGH
takes the bin; the other one stops after RETREAT (holding its gauze, torque on) and goes to CARRY_HIGH
when the first one's RETURN_HIGH is done. If an arm fails while it holds the bin, the bin stays closed:
the waiting arm stops at RETREAT too (torque on) and the command fails. Nothing moves into the bin twice.

A target that YOLO cannot find (arm at home) ends that target's tries; the arm goes on with its next
target. The command succeeds only when every try is done (then end_point true / EMR end-point;
with --pinky the both-arm pinky sequence runs after both arms are home).
GET /status: "arms" (each arm's target, try, phase, click stage), "bin" (free / left / right /
blocked by ...), "tries" (one line per try). Both arms run in one process with one bin lock.

Run (env main_project, in ~/kernel-robot-repo-2-il):
  python eval_bi_api_yolo_botharm.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto \
      --pinky --obb-rotate --joint-offset 14:-150 --open-scale 0.9 --close-extra 150 --slide 150
  Pick options (--joint-offset, --open-scale, --close-extra, --slide, --obb-rotate, --wrist-deg,
  --no-posture ...) go to both arms; --right-<option> overrides one for the right arm only.
  --sim      no camera, no motors, fake detections: test the order and the bin lock anywhere
  --dry-run  real YOLO and click-pick plans, no motor port; stages are only printed
  --no-right left arm only (a right-arm target in a command is refused before anything moves)
Test sender: python api_sender_yolo.py flow --no-callback --pinky --command '{"blue":1,"green":1}'
"""
import argparse
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from pydantic import Field, field_validator

import eval_bi_api as base
import eval_bi_api_yolo as yb

HERE = Path(__file__).resolve().parent
GAUZE = {"blue": "blue_gauze", "green": "green_gauze"}  # command key -> YOLO label
LEFT_TARGETS = {"green": "green_gauze"}  # --left-targets
RIGHT_TARGETS = {"blue": "blue_gauze"}  # --right-targets


def set_targets(left, right):
    """--left-targets green --right-targets blue -> LEFT_TARGETS / RIGHT_TARGETS (used by parse_command)."""
    for side, keys in (("left", left), ("right", right)):
        bad = [k for k in keys if k not in GAUZE]
        if bad:
            raise ValueError(f"--{side}-targets: unknown {bad}; use {', '.join(GAUZE)}")
    if set(left) & set(right):
        raise ValueError(f"{sorted(set(left) & set(right))} given to both arms")
    LEFT_TARGETS.clear()
    LEFT_TARGETS.update({k: GAUZE[k] for k in left})
    RIGHT_TARGETS.clear()
    RIGHT_TARGETS.update({k: GAUZE[k] for k in right})
MAX_COUNT = 20


class YoloQueue:
    """One YOLO worker (camera kept open) for both arms. Each arm's request goes into a FIFO queue
    with the time it asked; one thread sends them to the worker in that order. The worker uses the
    frames taken at or after the asking time, so a request that waited still sees that moment."""
    def __init__(self, worker):
        self.worker = worker
        self.jobs = queue.Queue()
        self.waiting = 0
        self.count_lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="yolo-queue").start()

    def start(self):
        return self.worker.start()

    def close(self):
        self.worker.close()

    def _loop(self):
        while True:
            payload, slot, done = self.jobs.get()
            try:
                slot["reply"] = self.worker.request(payload)
            except Exception as exc:
                slot["error"] = exc
            with self.count_lock:
                self.waiting -= 1
            done.set()

    def request(self, payload, tag=""):
        payload = {**payload, "after": time.time()}
        slot, done = {}, threading.Event()
        with self.count_lock:
            ahead = self.waiting
            self.waiting += 1
        if ahead:
            print(f"{tag}[YOLO] queued, {ahead} ahead", flush=True)
        self.jobs.put((payload, slot, done))
        done.wait()
        if "error" in slot:
            raise slot["error"]
        return slot["reply"]


def parse_command(command):
    """'blue:1, green:1' / '{"blue": 1}' / 'pick and place blue gauze' -> [("blue", 1), ...].
    blue_gauze / green_gauze work as keys too."""
    text = command if isinstance(command, str) else json.dumps(command)
    known = {**LEFT_TARGETS, **RIGHT_TARGETS}
    pairs = re.findall(r"""["']?([A-Za-z_]+)["']?\s*:\s*["']?(\d+)""", text)
    if not pairs:  # old single-target sentence
        words = [k for k in known if re.search(rf"\b{k}\b", text.lower())]
        if len(words) != 1:
            raise ValueError(f"command needs targets like 'blue:1, green:1' ({', '.join(known)})")
        pairs = [(words[0], "1")]
    jobs = {}
    for key, count in pairs:
        key = key.lower()
        key = key[:-len("_gauze")] if key.endswith("_gauze") else key
        if key not in known:
            raise ValueError(f"unknown target {key!r}; known: {', '.join(known)}")
        if not 0 <= int(count) <= MAX_COUNT:
            raise ValueError(f"{key}: count must be 0..{MAX_COUNT}")
        jobs[key] = jobs.get(key, 0) + int(count)
    jobs = [(k, n) for k, n in jobs.items() if n > 0]
    if not jobs:
        raise ValueError("command has no target with a count above 0")
    return jobs


class MultiCommandRequest(base.CommandRequest):
    """command may be a JSON object {"blue": 2, ...} or a string; kept as a canonical string."""
    command: str = Field(min_length=1, max_length=2000)

    @field_validator("command", mode="before")
    @classmethod
    def object_to_text(cls, value):
        if isinstance(value, dict):
            value = ", ".join(f"{k}:{v}" for k, v in value.items())
        if isinstance(value, str) and value.strip():
            parse_command(value)  # 422 before anything is accepted
        return value


class BinBlocked(RuntimeError):
    pass


class Bin:
    """The shared bin: one arm at a time from CARRY_HIGH to the end of RETURN_HIGH."""
    def __init__(self, on_change=lambda text: None):
        self.cond = threading.Condition()
        self.owner = None
        self.blocked = None  # arm that stopped while holding the bin
        self.on_change = on_change

    def state(self):
        if self.blocked:
            return f"blocked by {self.blocked}"
        return self.owner or "free"

    def acquire(self, arm, stop):
        with self.cond:
            if self.owner not in (None, arm):
                print(f"[{arm.upper()}] waiting at RETREAT: {self.owner} arm is over the bin", flush=True)
            while self.owner not in (None, arm):
                if self.blocked:
                    raise BinBlocked(f"bin blocked: {self.blocked} arm stopped over it")
                if stop.is_set():
                    raise BinBlocked("command stopped")
                self.cond.wait(0.2)
            self.owner = arm
        self.on_change(self.state())

    def release(self, arm):
        with self.cond:
            if self.owner == arm:
                self.owner = None
            self.cond.notify_all()
        self.on_change(self.state())

    def block(self, arm):
        with self.cond:
            self.blocked = arm
            self.cond.notify_all()
        self.on_change(self.state())


class Arm:
    """Everything one arm needs: its YOLO worker, its click-pick child, its home move."""
    def __init__(self, name, worker, targets, home, click_args, lane_args, move, area=None):
        self.name = name
        self.worker = worker        # shared YoloQueue or None (--sim)
        self.area = area or {}      # this arm's {"roi", "region", "conf", "weights"} for each request
        self.targets = targets      # {"blue": "blue_gauze", ...}
        self.home = home            # [(label, pose6, seconds), ...] RETURN_HIGH -> home
        self.click_args = click_args  # fn(det) -> click_pick_yolo.py options
        self.lane_args = lane_args  # click_pick_lane.py options (--arm, --omx-root, --sim ...)
        self.move = move            # fn(segments, disable_torque_at_end)


class BothArmRunner:
    """Takes PolicyRunner's place in eval_bi_api: one command -> both arms' tries -> result."""
    def __init__(self, arms, frames=5, save_dir=None, sim=False):
        self.arms = arms            # {"left": Arm, "right": Arm or None}
        self.frames = frames
        self.save_dir = Path(save_dir) if save_dir else None
        self.sim = sim
        self.last_end_reason = None
        self.last_result = {}
        self.next_stage = None
        self.on_stage = None
        self.on_update = None
        self.lock = threading.Lock()
        self.status = {}

    def preload(self):
        workers = {id(a.worker): a.worker for a in self.arms.values() if a is not None and a.worker is not None}
        for w in workers.values():  # one shared worker
            ready = w.start()
            logging.info("YOLO ready (one worker, camera kept open), classes %s", ready.get("classes"))

    def _push(self, **fields):
        with self.lock:
            for key, value in fields.items():
                if isinstance(value, dict) and isinstance(self.status.get(key), dict):
                    self.status[key] = {**self.status[key], **value}
                else:
                    self.status[key] = value
            snap = json.loads(json.dumps(self.status))
        return self.on_update(snap) if self.on_update is not None else None

    def _arm_status(self, arm, **fields):
        with self.lock:
            current = dict(self.status.get("arms", {}).get(arm, {}))
        current.update(fields)
        self._push(arms={arm: current})

    def __call__(self, command, return_event):
        jobs = parse_command(command)
        lanes = {}
        for key, count in jobs:
            side = "left" if key in LEFT_TARGETS else "right"
            if self.arms.get(side) is None:
                raise RuntimeError(f"{key} needs the {side} arm, which is off (--no-right or not set up); "
                                   "nothing moved")
            lanes.setdefault(side, []).append((key, count))
        self.status = {}
        request_id = self._push(phase="running", bin="free", tries=[],
                                arms={s: {"jobs": [f"{k}:{n}" for k, n in j], "phase": "waiting"}
                                      for s, j in lanes.items()}) or "latest"
        stop = threading.Event()  # set when one arm fails: the other finishes its current try only
        self.bin = Bin(lambda text: self._push(bin=text))
        errors = {}

        def lane(side):
            try:
                self._run_lane(side, lanes[side], request_id, stop)
            except Exception as exc:
                logging.exception("%s arm failed", side)
                errors[side] = str(exc)
                stop.set()

        threads = [threading.Thread(target=lane, args=(s,), name=f"{s}-arm") for s in lanes]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        tries = self.status.get("tries", [])
        missed = [t for t in tries if t["result"] != "done"]
        self._push(phase="done" if not errors and not missed else "failed")
        if errors:
            raise RuntimeError("; ".join(f"{s}: {e}" for s, e in errors.items()))
        if missed:
            raise RuntimeError("not every try was done: " +
                               ", ".join(f"{t['target']} #{t['n']} {t['result']}" for t in missed))
        self.last_end_reason = "botharm_done"

    def _run_lane(self, side, jobs, request_id, stop):
        arm = self.arms[side]
        for key, count in jobs:
            for n in range(1, count + 1):
                if stop.is_set():
                    self._try_result(side, key, n, "skipped (other arm failed)")
                    continue
                self._arm_status(side, target=key, n=f"{n}/{count}", phase="detect", click_stage=None)
                found = self._one_try(arm, key, n, request_id, stop)
                self._try_result(side, key, n, "done" if found else "not found")
                if not found:  # nothing left of this target in the arm's area
                    for rest in range(n + 1, count + 1):
                        self._try_result(side, key, rest, "skipped (none left)")
                    break
        self._arm_status(side, phase="done", target=None, click_stage=None)

    def _try_result(self, side, key, n, result):
        with self.lock:
            tries = list(self.status.get("tries", []))
        tries.append({"arm": side, "target": key, "n": n, "result": result})
        self._push(tries=tries)
        print(f"[{side.upper()}] {key} #{n}: {result}", flush=True)

    def _detect(self, arm, key, n, request_id):
        label = arm.targets[key]
        if arm.worker is None:  # --sim
            time.sleep(0.3)
            return {"label": label, "conf": 0.99, "grasp_uv": [1000.0, 700.0], "grasp_edge": None}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save = str(self.save_dir / f"{stamp}_{request_id}_{arm.name}_{key}{n}.jpg") if self.save_dir else None
        reply = arm.worker.request({"target": label, "frames": self.frames, "save": save, **arm.area},
                                   tag=f"[{arm.name.upper()}]")
        det = reply["detection"]
        for o in reply["all"]:
            mark = "  <- target" if det and o["label"] == det["label"] else ""
            print(f"[{arm.name.upper()}][YOLO] {o['label']} conf {o['conf']:.2f} grasp {o['grasp_uv']} "
                  f"{'in area' if o['in_area'] else 'outside area'}{mark}", flush=True)
        self.last_result[arm.name] = {"target": label, "detection": det, "image": save}
        return det

    def _one_try(self, arm, key, n, request_id, stop):
        det = self._detect(arm, key, n, request_id)
        if det is None:
            arm.move([], True)  # stays at home, torque off
            return False
        self._arm_status(arm.name, phase="pick", detection=det)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = yb.YOLO_DIR / "outputs/api"
        log_dir.mkdir(parents=True, exist_ok=True) if not self.sim else None
        log = log_dir / f"{stamp}_{request_id}_{arm.name}_{key}{n}_click_pick.jsonl"
        self._click_pick(arm, det, log, stop)
        self._arm_status(arm.name, phase="to_home", click_stage=None)
        arm.move(arm.home, True)
        return True

    def _click_pick(self, arm, det, log, stop):
        read_fd, write_fd = os.pipe()
        cmd = [sys.executable, "-u", str(HERE / "click_pick_lane.py"), *arm.lane_args,
               "--gate-fd", str(read_fd), "--", *arm.click_args(det, log)]
        logging.info("%s click pick: %s", arm.name, " ".join(cmd))
        try:
            proc = subprocess.Popen(cmd, cwd=str(HERE), stdout=subprocess.PIPE, text=True, bufsize=1,
                                    pass_fds=(read_fd,))
        finally:
            os.close(read_fd)
        gate = os.fdopen(write_fd, "w")
        holding = False
        tag = f"[{arm.name.upper()}]"
        try:
            for line in proc.stdout:
                if line.startswith("BIN_WAIT"):
                    self._arm_status(arm.name, phase="wait_bin")
                    try:
                        self.bin.acquire(arm.name, stop)
                        holding = True
                        answer = "GO"
                    except BinBlocked as exc:
                        print(f"{tag} {exc}; stopping at RETREAT (torque on)", flush=True)
                        answer = "STOP"
                    gate.write(answer + "\n")
                    gate.flush()
                elif line.startswith("BIN_FREE"):
                    self.bin.release(arm.name)
                    holding = False
                elif line.startswith("STAGE "):
                    name = line.split()[1]
                    self._arm_status(arm.name, phase=yb.STAGE_PHASE.get(name, "pick"), click_stage=name)
                else:
                    print(f"{tag} {line}", end="", flush=True)
            code = proc.wait()
        finally:
            gate.close()
            if proc.poll() is None:
                proc.kill()
            if holding:
                # Stopped between CARRY_HIGH and the end of RETURN_HIGH: keep the bin closed.
                self.bin.block(arm.name)
        if code == 3:
            raise RuntimeError(f"{arm.name} click pick stopped; arm held where it stopped (torque on)")
        if code != 0:
            raise RuntimeError(f"{arm.name} click pick failed (exit {code}); arm held, see {log}")


# ---- arm moves ---------------------------------------------------------------------------

def right_home_segments(seconds):
    """Right arm RETURN_HIGH -> home: pinky_sequence.json return.right.start + right gripper rest."""
    data = json.loads((HERE / "pinky_sequence.json").read_text())
    start = list(data["return"]["right"]["start"]) + [float(data["gripper"]["right"]["rest"])]
    return [("HOME", start, seconds)]


def move_right(segments, disable_torque_at_end, fps=30):
    """Right arm (/dev/omx_follower) through [(label, pose6, seconds)], like yb.move_left.

    The right follower has narrower motor limits than its file, so the calibration check is
    pinky_move.check_calibration (same zero/direction, limits may be narrower).
    """
    from types import SimpleNamespace
    from eval_bi import JOINT_NAMES, return_to_start
    from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig
    from pinky_move import ARMS, check_calibration

    port, calib_id = ARMS["right"]
    occupied = subprocess.run(["fuser", port], capture_output=True, text=True)
    if occupied.returncode != 1:
        raise RuntimeError(f"right port busy or ownership check failed: {occupied.stdout} {occupied.stderr}")
    arm = OmxFollower(OmxFollowerConfig(id=calib_id, port=port, cameras={}))
    bus = arm.bus
    enabled = finished = False
    try:
        bus.connect()
        check_calibration("right", bus)
        modes = bus.sync_read("Operating_Mode", normalize=False)
        for name, mode in modes.items():
            if mode not in ((3, 5) if name == "gripper" else (3, 4)):
                raise RuntimeError(f"right: unexpected operating mode for {name}: {mode}")
        errors = bus.sync_read("Hardware_Error_Status", normalize=False)
        if any(errors.values()):
            raise RuntimeError(f"right motor hardware errors: {errors}")
        bus.sync_write("Goal_Position", bus.sync_read("Present_Position"))
        enabled = True
        bus.enable_torque()

        def send(action):  # return_to_start speaks in left_* keys; they are only labels here
            errs = bus.sync_read("Hardware_Error_Status", normalize=False)
            if any(errs.values()):
                raise RuntimeError(f"right motor hardware errors during move: {errs}")
            target = {n: action[f"left_{n}.pos"] for n in JOINT_NAMES}
            actual = bus.sync_read("Present_Position")
            if max(abs(target[n] - actual[n]) for n in JOINT_NAMES) > 15:
                raise RuntimeError("right: excessive tracking error; move aborted")
            bus.sync_write("Goal_Position", target)
            return action

        robot = SimpleNamespace(left_arm=arm, send_action=send)
        for label, pose, seconds in segments:
            print(f"[RIGHT][ARM] {label}", flush=True)
            return_to_start(robot, SimpleNamespace(
                return_via=list(pose), start_pose=list(pose), return_via_time=seconds, return_home_time=0.3,
                return_tolerance=2.0, return_settle_time=4.0, fps=fps))
        finished = True
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=enabled and finished and disable_torque_at_end)


def log_move(side):
    def move(segments, disable_torque_at_end):
        for label, pose, seconds in segments:
            print(f"[{side.upper()}][ARM] {label}  [no motors] {[round(v, 1) for v in pose]}", flush=True)
            time.sleep(min(seconds, 0.5))
        if disable_torque_at_end:
            print(f"[{side.upper()}][TORQUE] off  [no motors]", flush=True)
    return move


# ---- options -----------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--callback-url", default=os.environ.get("END_POINT_CALLBACK_URL") or None)
    p.add_argument("--emr-api", default=None, help="on success GET URL/robot/<request_id>/end-point")
    p.add_argument("--auto", action="store_true", help="no typed confirmations (needed with two arms)")
    p.add_argument("--sim", action="store_true", help="no camera, no motors, fake detections")
    p.add_argument("--dry-run", action="store_true", help="real YOLO and click-pick plans, no motor port")
    p.add_argument("--sim-seconds", type=float, default=0.5, help="--sim/--dry-run: seconds per stage")
    p.add_argument("--sim-fail", default=None, metavar="ARM:STAGE",
                   help="--sim test: that arm fails at that stage, e.g. left:DROP_RELEASE")
    p.add_argument("--pinky", action="store_true", help="both-arm pinky sequence after a successful command")
    p.add_argument("--pinky-sequence", default=None)
    p.add_argument("--frames", type=int, default=5)
    p.add_argument("--save-dir", default=str(yb.YOLO_DIR / "outputs/api"))
    p.add_argument("--cam-top", default="/dev/cam_top")
    p.add_argument("--top-exposure", type=int, default=90)
    p.add_argument("--device", default="0")
    p.add_argument("--yolo-python", default=str(yb.DEFAULT_PYTHON))
    p.add_argument("--to-calib", default="2.25,2.25,240,0")
    p.add_argument("--return-home-time", type=float, default=4.0)
    p.add_argument("--click-skip", nargs="*", default=["LIFT", "DROP_RETREAT"], metavar="STAGE")
    # speed (both arms; omx_click_pick.json is not changed)
    p.add_argument("--stage-seconds", type=float, default=None,
                   help="seconds per click-pick arm stage (config default 4.0); smaller = faster")
    p.add_argument("--slow-seconds", type=float, default=None,
                   help="seconds for --slow-stages (default: same as --stage-seconds)")
    p.add_argument("--slow-stages", nargs="+", default=["APPROACH", "HOVER", "PICK"], metavar="STAGE")
    p.add_argument("--gripper-seconds", type=float, default=None, help="gripper open / close seconds (config 0.8)")
    # pick options: both arms (same meaning as eval_bi_api_yolo.py); --right-* overrides the right arm
    p.add_argument("--left-targets", nargs="+", default=["green"], help="command keys the left arm picks")
    p.add_argument("--right-targets", nargs="+", default=["blue"], help="command keys the right arm picks")
    p.add_argument("--weights", default=str(yb.DEFAULT_WEIGHTS))
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--roi", default="0,0.5,0.4,1.0", help="left arm's part of the 640x480 picture")
    p.add_argument("--obb-rotate", action="store_true")
    p.add_argument("--wrist-deg", type=float, default=0.0)
    p.add_argument("--max-wrist-deg", type=float, default=45.0)
    p.add_argument("--no-posture", action="store_true")
    p.add_argument("--close-extra", type=int, default=0)
    p.add_argument("--open-scale", type=float, default=1.0)
    p.add_argument("--slide", type=int, default=0, metavar="PULSES",
                   help="after CLOSE turn ID11 this many pulses (green -> picture right, blue -> left)")
    p.add_argument("--joint-offset", nargs="*", default=[], metavar="ID:PULSES")
    p.add_argument("--offset-stages", nargs="+", default=["APPROACH"], metavar="STAGE")
    # right arm
    p.add_argument("--no-right", action="store_true", help="left arm only")
    p.add_argument("--right-weights", default=None, help="right arm YOLO (default: --weights)")
    p.add_argument("--right-conf", type=float, default=None, help="default: --conf")
    p.add_argument("--right-roi", default=yb.ROI_DEFAULT["right"], help="right arm's part of the 640x480 picture")
    p.add_argument("--right-omx", default=None,
                   help="old way: a copy of omxtest-main for the right arm (default: omxtest-main --arm right)")
    p.add_argument("--right-poses", default=str(HERE / "click_pick_poses_right.json"),
                   help="right arm carry_high etc. (record_click_pose.py --arm right)")
    p.add_argument("--right-joint-offset", nargs="*", default=None, metavar="ID:PULSES", help="default: --joint-offset")
    p.add_argument("--right-offset-stages", nargs="+", default=None, metavar="STAGE", help="default: --offset-stages")
    p.add_argument("--right-open-scale", type=float, default=None, help="default: --open-scale")
    p.add_argument("--right-close-extra", type=int, default=None, help="default: --close-extra")
    p.add_argument("--right-slide", type=int, default=None, help="default: --slide")
    p.add_argument("--right-wrist-deg", type=float, default=None, help="default: --wrist-deg")
    p.add_argument("--right-no-obb-rotate", action="store_true", help="right arm without --obb-rotate")
    p.add_argument("--right-no-posture", action="store_true", help="right arm with --no-posture")
    return p.parse_args(argv)


def left_home_pose(sim):
    """eval_bi.DEFAULT_START_POSE; --sim reads the same pose from pinky_sequence.json (no lerobot import)."""
    if not sim:
        from eval_bi import DEFAULT_START_POSE
        return list(DEFAULT_START_POSE)
    data = json.loads((HERE / "pinky_sequence.json").read_text())
    return list(data["return"]["left"]["start"]) + [float(data["gripper"]["left"]["rest"])]


def build_arms(o):
    sim, dry = o.sim, o.dry_run
    mode = ["--sim"] if sim else ["--dry"] if dry else []
    mode += ["--sim-seconds", str(o.sim_seconds)] if (sim or dry) else []
    skip = ["--skip", *o.click_skip] if o.click_skip else []
    fail_arm, _, fail_stage = (o.sim_fail or "").partition(":")

    def lane_mode(side):
        return mode + (["--sim-fail", fail_stage] if sim and side == fail_arm else [])

    speed = (["--stage-seconds", str(o.stage_seconds)] if o.stage_seconds else []) \
        + (["--slow-seconds", str(o.slow_seconds), "--slow-stages", *o.slow_stages] if o.slow_seconds else []) \
        + (["--gripper-seconds", str(o.gripper_seconds)] if o.gripper_seconds else [])

    def common(det, log):
        return ["--uv", f"{det['grasp_uv'][0]:.1f}", f"{det['grasp_uv'][1]:.1f}", "--output", str(log)] \
            + ([] if (sim or dry) else ["--live", "--auto"]) + skip + speed

    def pick_args(open_scale, close_extra, slide, joint_offset, offset_stages, obb_rotate, wrist_deg, no_posture):
        def args_for(det, log):
            args = common(det, log) + ["--open-scale", f"{open_scale:.4f}", "--close-extra", str(close_extra)]
            if slide:
                args += ["--slide", str(slide), "--label", det["label"]]
            if joint_offset:
                args += ["--joint-offset", *joint_offset, "--offset-stages", *offset_stages]
            wrist = []
            if obb_rotate and det.get("grasp_edge"):
                wrist += ["--edge", *(f"{v:.1f}" for pt in det["grasp_edge"] for v in pt)]
            if wrist_deg:
                wrist += ["--wrist-deg", f"{wrist_deg:.1f}"]
            if wrist:
                wrist += ["--max-wrist-deg", f"{o.max_wrist_deg:.1f}"]
            return args + wrist + (["--no-posture"] if no_posture else [])
        return args_for

    def pick(value, default):
        return default if value is None else value

    left_args = pick_args(o.open_scale, o.close_extra, o.slide, o.joint_offset, o.offset_stages,
                          o.obb_rotate, o.wrist_deg, o.no_posture)
    right_args = pick_args(pick(o.right_open_scale, o.open_scale), pick(o.right_close_extra, o.close_extra),
                           pick(o.right_slide, o.slide), pick(o.right_joint_offset, o.joint_offset),
                           pick(o.right_offset_stages, o.offset_stages), o.obb_rotate and not o.right_no_obb_rotate,
                           pick(o.right_wrist_deg, o.wrist_deg), o.no_posture or o.right_no_posture)

    shared = None
    if not sim:  # one YOLO process for both arms; each request carries its arm's ROI / region / conf
        w = yb.YoloWorker(o.yolo_python, o.weights, o.cam_top, None, o.conf, o.top_exposure, o.device,
                          o.roi, o.to_calib)
        w.cmd.append("--keep-open")
        shared = YoloQueue(w)

    def area(weights, roi, region, conf):
        out = {"roi": [float(v) for v in roi.split(",")], "region": region, "conf": conf}
        if weights and Path(weights).resolve() != Path(o.weights).resolve():
            out["weights"] = str(weights)
        return out

    left_region = None if sim else yb.work_area()[0]  # omxtest-main single (yb defaults)
    left = Arm("left", shared, dict(LEFT_TARGETS),
               [("HOME", left_home_pose(sim), o.return_home_time)], left_args, ["--arm", "left", *lane_mode("left")],
               log_move("left") if (sim or dry) else yb.move_left, area(None, o.roi, left_region, o.conf))
    right = None
    if not o.no_right:
        region = None
        if o.right_omx:  # old way: the right arm's own copy of omxtest-main
            cfg = Path(o.right_omx).expanduser() / "config/omx_click_pick.json"
            lane = ["--arm", "right", "--omx-root", o.right_omx, "--poses", o.right_poses]
        else:
            cfg = yb.OMX / "config/arms/right/omx_click_pick.json"
            lane = ["--arm", "right", "--poses", o.right_poses]
        if not sim:
            if not cfg.exists():
                sys.exit(f"right arm click-pick config not found: {cfg}\n"
                         "set up the right arm first (RIGHT_ARM.md), or start with --no-right / --sim")
            region = json.loads(cfg.read_text())["regions_uv"][0]
            if not dry:
                yb.check_right_port()
        right = Arm("right", shared, dict(RIGHT_TARGETS), right_home_segments(o.return_home_time),
                    right_args, [*lane, *lane_mode("right")],
                    log_move("right") if (sim or dry) else move_right,
                    area(o.right_weights, o.right_roi, region, pick(o.right_conf, o.conf)))
    return {"left": left, "right": right}


def build_app(options, runner, **create_kwargs):
    base.CommandRequest = MultiCommandRequest  # create_app's /command and the controller use this name
    app = base.create_app(options.callback_url, policy_runner=runner, **create_kwargs)
    controller = app.state.controller
    if not options.pinky:
        controller._grab = lambda: None

    def on_update(fields):
        with controller.lock:
            controller.current.update(fields)
            return controller.current.get("request_id")

    runner.on_update = on_update

    @app.get("/detection")
    def get_detection():
        return runner.last_result

    return app


if __name__ == "__main__":
    import uvicorn
    options = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    set_targets(options.left_targets, options.right_targets)
    if not (options.auto or options.sim or options.dry_run):
        sys.exit("two arms share this terminal: use --auto (or --sim / --dry-run)")
    if options.pinky_sequence:
        from pinky_move import load_sequence
        load_sequence(options.pinky_sequence)
        base.PINKY_SEQUENCE = options.pinky_sequence
    arms = build_arms(options)
    runner = BothArmRunner(arms, options.frames, None if options.sim else (options.save_dir or None),
                           sim=options.sim)
    runner.preload()
    base.app.state.controller.close()
    extra = {}
    if options.emr_api:
        if options.callback_url:
            sys.exit("use either --callback-url or --emr-api")
        options.callback_url = options.emr_api
        extra["sender"] = yb.emr_sender
    if options.sim or options.dry_run:
        for key in ("pinky_motion", "release_motion", "home_motion"):
            extra[key] = (lambda name: lambda: print(f"[PINKY] {name}  [no motors]", flush=True))(key)
    logging.info("arms: left %s %s, right %s %s; %s", "on", list(LEFT_TARGETS), "on" if arms["right"] else "off",
                 list(RIGHT_TARGETS),
                 "SIM (no camera, no motors)" if options.sim else "DRY RUN (no motors)" if options.dry_run
                 else "LIVE")
    app = build_app(options, runner, **extra)
    try:
        uvicorn.run(app, host=options.host, port=options.port, workers=1)
    finally:
        if arms["left"].worker is not None:
            arms["left"].worker.close()  # the one shared YOLO worker
