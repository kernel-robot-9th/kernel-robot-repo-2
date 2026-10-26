"""Both arms pick sequence for the pinky cycle, then return both arms to the start pose.

pick():        above target (grippers open 2/3 on the way) -> close grippers -> lift -> open grippers
return_home(): both arms -> via pose -> start pose (grippers close to the start-pose value on the way)

Poses come from pinky_sequence.json (LeRobot normalized joint values, same units as
left_start_pose_measured.json). While "placeholder" is true the robot is never moved.
Both arms move at the same time, step by step; the next step starts only after both arrive.

Run by hand (no API):   python pinky_move.py pick | grab | release | return  [sequence.json]
                        (pick = grab + release; the API runs grab, waits for pinky_arrive, then release)
Validate the file only: python pinky_move.py --check [sequence.json]

Torque stays ON after each phase so the grasped object is held. On error or Ctrl+C the
torque is turned off on both arms (same as test_left_return_once.py): a held object drops.
"""
from contextlib import contextmanager
import json
import logging
import math
import os
import subprocess
import sys
import time
from pathlib import Path

JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
BODY = JOINT_NAMES[:5]
SIDES = ("left", "right")
ARMS = {"left": ("/dev/omx_follower_left", "omx_bi_follower_left"),
        "right": ("/dev/omx_follower", "omx_bi_follower_right")}
DEFAULT_SEQUENCE = Path(__file__).with_name("pinky_sequence.json")
FPS = 30
TOLERANCE = 4.0          # joint arrival tolerance (normalized units); 2 failed from gravity sag
SETTLE_TIME = 4.0        # seconds allowed to confirm arrival after each step
MAX_TRACKING_ERROR = 15  # abort if a joint lags its command by more than this


def _value(name, value, gripper=False):
    low = 0 if gripper else -100
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= 100:
        raise ValueError(f"{name} must be a number in [{low}, 100], got {value!r}")
    return float(value)


def _body(name, side, values):
    if not isinstance(values, list) or len(values) != 5:
        raise ValueError(f"{name}.{side}: needs 5 values {BODY}")
    return {f"{side}_{j}": _value(f"{name}.{side}.{j}", v) for j, v in zip(BODY, values)}


def _time(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 30:
        raise ValueError(f"{name}: time must be in (0, 30] seconds")
    return float(value)


def load_sequence(path=DEFAULT_SEQUENCE):
    """Return (pick_steps, return_steps, placeholder).

    Each step: {"name", "target": {"left_joint": value, ...}, "time", "grip": bool}.
    """
    data = json.loads(Path(path).read_text())
    # Named gripper values per arm, e.g. open, close, approach, rest.
    grip = {side: {kind: _value(f"gripper.{side}.{kind}", value, True)
                   for kind, value in data["gripper"][side].items() if kind != "measured_hold"}
            for side in SIDES}

    def gripper_target(name, kind):
        if not all(kind in grip[side] for side in SIDES):
            raise ValueError(f"{name}: gripper value {kind!r} not defined for both arms")
        return {f"{side}_gripper": grip[side][kind] for side in SIDES}

    pick = []
    for i, raw in enumerate(data["steps"]):
        name = raw.get("name", f"step{i + 1}")
        target = {}
        for side in SIDES:
            if side in raw:
                target.update(_body(name, side, raw[side]))
        if "gripper" in raw:
            target.update(gripper_target(name, raw["gripper"]))
        if not target:
            raise ValueError(f"{name}: needs left/right body values or gripper")
        pick.append({"name": name, "target": target, "time": _time(name, raw.get("time")),
                     "grip": raw.get("gripper") == "close"})
    if not pick:
        raise ValueError("sequence has no steps")
    ret = data["return"]
    duration = _time("return", ret.get("time"))
    home = []
    for pose in ("via", "start"):
        target = {k: v for side in SIDES for k, v in _body(f"return.{pose}", side, ret[side][pose]).items()}
        if f"{pose}_gripper" in ret:  # e.g. close the grippers while moving to start
            target.update(gripper_target(f"return.{pose}", ret[f"{pose}_gripper"]))
        home.append({"name": f"return_{pose}", "time": duration, "grip": False, "target": target})
    return pick, home, bool(data.get("placeholder", True))


def run_sequence(read, write, steps, fps=FPS, tolerance=TOLERANCE, settle_time=SETTLE_TIME,
                 sleep=time.sleep, clock=time.perf_counter, gripper_blocked=None):
    """Interpolate each step from the current position; never advance before arrival.

    read() -> {"left_joint": value, ...}; write({...}) sends only the keys given.
    Joints not named in a step are not commanded, so they hold their last goal. After a
    close step the grippers are expected to stall on the object and are no longer checked.
    """
    blocked = set(gripper_blocked or ())
    for step in steps:
        target = step["target"]
        initial = read()
        started = clock()
        logging.info("pinky %s: %s over %.1fs", step["name"], target, step["time"])
        if not step["grip"]:
            blocked.difference_update(target)  # an open command frees a stalled gripper
        free = [k for k in target if not (k.endswith("_gripper") and (k in blocked or step["grip"]))]
        while True:
            tick = clock()
            fraction = min((tick - started) / step["time"], 1.0)
            blend = fraction * fraction * (3 - 2 * fraction)
            command = {k: initial[k] + blend * (goal - initial[k]) for k, goal in target.items()}
            actual = read()
            if any(abs(command[k] - actual[k]) > MAX_TRACKING_ERROR for k in free):
                raise RuntimeError(f"pinky {step['name']}: excessive tracking error")
            write(command)
            if fraction >= 1:
                break
            sleep(max(0, 1 / fps - (clock() - tick)))
        if step["grip"]:
            blocked.update(k for k in target if k.endswith("_gripper"))
        check = [k for k in target if k not in blocked]
        deadline = clock() + settle_time
        stable = 0
        while check:
            actual = read()
            worst = max(check, key=lambda k: abs(actual[k] - target[k]))
            error = abs(actual[worst] - target[worst])
            stable = stable + 1 if error <= tolerance else 0
            if stable >= 3:
                break
            if clock() >= deadline:
                raise TimeoutError(f"pinky {step['name']}: arrival not confirmed ({worst} off by {error:.2f})")
            sleep(1 / fps)
        if step["grip"]:
            sleep(min(step["time"], 1.0))  # give the grippers time to squeeze
        actual = read()
        offsets = {k: round(actual[k] - target[k], 2) for k in target}
        logging.info("pinky %s done; actual - target: %s", step["name"], offsets)
    return blocked


def check_calibration(side, bus):
    """Like bus.is_calibrated, but motor position limits may be narrower than the file.

    The right follower has extra limits (shoulder_lift 830-3129, elbow_flex 1024-3140) and a
    time-based motion profile (Drive_Mode bit 2). Those are kept as a hardware safety stop.
    Zero offsets and direction must match exactly, so normalized values mean the same thing.
    """
    expected, actual = bus.calibration, bus.read_calibration()
    if set(expected) != set(actual):
        raise RuntimeError(f"{side}: calibration motors differ; no motion performed")
    for motor, want in expected.items():
        got = actual[motor]
        if (got.id != want.id or got.homing_offset != want.homing_offset
                or (got.drive_mode & 1) != (want.drive_mode & 1)
                or got.range_min < want.range_min or got.range_max > want.range_max):
            raise RuntimeError(f"{side}: calibration mismatch on {motor}: motor {got}, file {want}; "
                               "no motion performed")
        if (got.range_min, got.range_max) != (want.range_min, want.range_max):
            logging.info("%s %s: motor limits %d-%d kept", side, motor, got.range_min, got.range_max)


@contextmanager
def connected_arms():
    """Open both follower buses with the same checks as test_left_return_once.py.

    Yields (read, write). Torque stays on after success; any error turns it off.
    """
    if os.environ.get("PINKY_NO_HARDWARE"):
        raise RuntimeError("PINKY_NO_HARDWARE is set; refusing to open robot ports")
    from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig

    buses = {}
    enabled = ok = False
    try:
        for side, (port, calib_id) in ARMS.items():
            if not Path(port).exists():
                raise RuntimeError(f"{side} port not found: {port}")
            occupied = subprocess.run(["fuser", port], capture_output=True, text=True)
            if occupied.returncode != 1:
                raise RuntimeError(f"{side} port busy: {occupied.stdout} {occupied.stderr}")
            bus = OmxFollower(OmxFollowerConfig(id=calib_id, port=port, cameras={})).bus
            bus.connect()  # bus only: no motor configuration or calibration writes
            buses[side] = bus
            check_calibration(side, bus)
            modes = bus.sync_read("Operating_Mode", normalize=False)
            for name, mode in modes.items():
                if mode not in ((3, 5) if name == "gripper" else (3, 4)):
                    raise RuntimeError(f"{side}: unexpected operating mode for {name}: {mode}")
            raw = bus.sync_read("Present_Position", normalize=False)
            if any(not 0 <= value <= 4095 for value in raw.values()):
                raise RuntimeError(f"{side}: position outside calibration range: {raw}")

        def read():
            positions = {}
            for side, bus in buses.items():
                errors = bus.sync_read("Hardware_Error_Status", normalize=False)
                if any(errors.values()):
                    raise RuntimeError(f"{side} motor hardware errors: {errors}")
                positions.update({f"{side}_{j}": v for j, v in bus.sync_read("Present_Position").items()})
            return positions

        def write(command):
            for side, bus in buses.items():
                goal = {k.removeprefix(f"{side}_"): v for k, v in command.items() if k.startswith(f"{side}_")}
                if goal:
                    bus.sync_write("Goal_Position", goal)

        current = read()
        logging.info("current position: %s", current)
        # Seed goals so enabling torque causes no jump. A gripper that is already
        # torqued (holding the object from pick) keeps its squeeze goal.
        seed = dict(current)
        for side, bus in buses.items():
            if bus.sync_read("Torque_Enable", normalize=False)["gripper"]:
                seed.pop(f"{side}_gripper")
        write(seed)
        enabled = True
        for bus in buses.values():
            bus.enable_torque()
        yield read, write
        ok = True
    finally:
        for bus in buses.values():
            if bus.is_connected:
                try:
                    bus.disconnect(disable_torque=enabled and not ok)
                except Exception:
                    logging.exception("disconnect failed")


def _load_real(path):
    pick, home, placeholder = load_sequence(path)
    if placeholder:
        raise RuntimeError(f"{path} still has placeholder poses; measure both arms and set "
                           "\"placeholder\": false before moving the robot")
    return pick, home


RELEASE_STEP = "release_gripper"


def split_pick(steps):
    """(grab steps up to lift, release steps from release_gripper on)."""
    names = [s["name"] for s in steps]
    i = names.index(RELEASE_STEP) if RELEASE_STEP in names else len(steps)
    return steps[:i], steps[i:]


def grab(path=DEFAULT_SEQUENCE):
    """Approach, close and lift; torque stays ON so the object is held until release()."""
    steps, _ = split_pick(_load_real(path)[0])
    with connected_arms() as (read, write):
        run_sequence(read, write, steps)
    logging.info("COMPLETED grab: object lifted and held; torque stays ON")


def release(path=DEFAULT_SEQUENCE):
    """Open the grippers (and any steps after release_gripper)."""
    _, steps = split_pick(_load_real(path)[0])
    with connected_arms() as (read, write):
        run_sequence(read, write, steps)
    logging.info("COMPLETED release: grippers open")


def pick(path=DEFAULT_SEQUENCE):
    steps, _ = _load_real(path)
    with connected_arms() as (read, write):
        run_sequence(read, write, steps)
    logging.info("COMPLETED pick: object lifted; torque stays ON")


def return_home(path=DEFAULT_SEQUENCE):
    _, steps = _load_real(path)
    with connected_arms() as (read, write):
        run_sequence(read, write, steps)
    logging.info("COMPLETED return: both arms at start pose; torque stays ON")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", force=True)
    argv = sys.argv[1:]
    action = argv[0] if argv else "--check"
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SEQUENCE
    if action == "--check":
        pick_steps, home_steps, placeholder = load_sequence(path)
        for s in pick_steps + home_steps:
            print(f"{s['name']:14s} {s['time']:4.1f}s {s['target']}")
        print("PLACEHOLDER: robot will not move" if placeholder else "ready")
    elif action == "pick":
        pick(path)
    elif action == "grab":
        grab(path)
    elif action == "release":
        release(path)
    elif action == "return":
        return_home(path)
    else:
        sys.exit("usage: python pinky_move.py --check | pick | grab | release | return [sequence.json]")
