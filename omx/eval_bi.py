"""Run a trained ACT / SmolVLA checkpoint on the bimanual OMX robot (no dataset recording).

Standalone version of the policy branch of `lerobot-record` (LeRobot v0.4.4,
src/lerobot/scripts/lerobot_record.py: record() + record_loop()), so it can be imported or
merged into other code. Same behaviour as eval_bi.sh, minus saving an eval dataset.

Usage:
  python eval_bi.py --policy-path ~/main_project/outputs/train/act_bi_lift_box/checkpoints/last/pretrained_model
  python eval_bi.py --policy-path .../smolvla_bi_gauze/checkpoints/last/pretrained_model \
      --task "pick and place blue gauze" --episode-time 60 --top-mask --top-exposure 90
  python eval_bi.py --policy-path ... --dry-run     # no robot: random observations, checks the model runs

Camera keys must match what the policy was trained on. Default "auto": SmolVLA -> camera1/2/3
(train_bi.sh renames top/wrist_left/wrist_right to these), anything else -> top/wrist_left/wrist_right.
Stop early with Ctrl+C; the arms are disconnected (torque off) on exit.

Optional return motion:
  --return-via <6 left values> --start-pose <6 left values>
  --return-via-time 2 --return-home-time 2
Values are LEFT arm only, ordered:
shoulder_pan shoulder_lift elbow_flex wrist_flex wrist_roll gripper.
Use LeRobot normalized units (body -100..100, gripper 0..100), NOT degrees/radians.
Measured left poses are defaults. Normal episode completion returns via the waypoint to home.
Only the left arm receives commands. Right joint feedback is read for the bimanual
model, without configuring the right motors or changing their torque.
No return motion is performed on Ctrl+C or an error.
Imported callers can pass should_return=lambda obs: event.is_set() to run_episode().
The callback must be non-blocking; it may also use obs to implement a release detector.
This is a direct LeRobot motor path, not a ROS2 trajectory client. A 0.4 s response
is not guaranteed: camera reads and in-flight policy inference may delay callbacks.

Matches eval_bi.sh (2026-10-20):
- torch CPU threads limited to 4 (--torch-threads). With the default (one per core, 24 on max)
  converting the 3 camera images took 30-45 ms per step and the loop ran at 12-15 Hz instead of 30;
  with 4 threads a whole step is ~10 ms. Must be set before torch is imported, so it is done first.
- motor preflight (clear_motor_errors.py on both followers) before connecting; skip with --no-preflight.
- --top-exposure 90 for models trained on exposure-90 data, --top-mask for *_masked datasets.
- if disconnecting fails (e.g. a motor latched an overload error), torque is switched off directly.
"""
import argparse
import logging
import math
import os
import subprocess
import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path


def _early_threads(argv):
    """Read --torch-threads before torch is imported (default 4)."""
    n = "4"
    if "--torch-threads" in argv:
        i = argv.index("--torch-threads")
        if i + 1 < len(argv):
            n = argv[i + 1]
    return n


_THREADS = _early_threads(sys.argv)
os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
os.environ.setdefault("MKL_NUM_THREADS", _THREADS)

import numpy as np
import torch

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets.utils import build_dataset_frame, combine_feature_dicts, hw_to_dataset_features
from lerobot.policies.factory import get_policy_class, make_pre_post_processors
from lerobot.policies.utils import make_robot_action
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.control_utils import predict_action
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import get_safe_torch_device, init_logging

torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
register_third_party_plugins()
from lerobot_robot_bi_omx.bi_omx import BiOmxFollower, BiOmxFollowerConfig  # noqa: E402

# Same keep-rectangle as masking/mask_dataset_stream.py and eval_bi.sh TOP_MASK=1 (x1 y1 x2 y2).
TOP_MASK_ROI = [0, 200, 400, 480]
# Helper scripts (set_top_exposure.sh, clear_motor_errors.py): next to this file, else ~/main_project.
PROJECT_DIR = Path.home() / "main_project"
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
POSE_KEYS = tuple(f"left_{joint}.pos" for joint in JOINT_NAMES)
# Measured from the user's left follower; raw records kept alongside this file.
DEFAULT_RETURN_VIA = [-2.90598290598291, -20.586080586080584, 16.776556776556788,
                      50.13431013431014, -0.073260073260073, 49.5970695970696]
DEFAULT_START_POSE = [-5.543345543345552, -59.51159951159951, 51.30647130647131,
                      50.23199023199024, -0.073260073260073, 49.5970695970696]


class LeftOnlyBiOmxFollower(BiOmxFollower):
    """Preserve bimanual model observations, with writes restricted to the left arm."""

    def connect(self, calibrate=True):
        try:
            self.left_arm.connect(calibrate)
            # Do not use right_arm.connect(): it configures motors and changes torque.
            self.right_arm.bus.connect()
            for camera in self.cameras.values():
                camera.connect()
        except BaseException:
            self.disconnect()
            raise

    def send_action(self, action):
        left = {key.removeprefix("left_"): value for key, value in action.items()
                if key.startswith("left_")}
        if not left:
            raise ValueError("no left-arm action supplied")
        sent = self.left_arm.send_action(left)
        return {f"left_{key}": value for key, value in sent.items()}

    def disconnect(self):
        errors = []
        for resource, kwargs in (
            (self.left_arm.bus, {"disable_torque": True}),
            (self.right_arm.bus, {"disable_torque": False}),
            *((camera, {}) for camera in self.cameras.values()),
        ):
            if resource.is_connected:
                try:
                    resource.disconnect(**kwargs)
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]


def helper(name):
    here = Path(__file__).resolve().parent / name
    return here if here.exists() else PROJECT_DIR / name


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--policy-path", required=True, help="checkpoint folder: .../checkpoints/<step>/pretrained_model")
    p.add_argument("--task", default="", help="instruction text (SmolVLA: use the exact sentence from recording)")
    p.add_argument("--stages", default=None,
                   help='stage sentences in order, separated by "|" (models trained on *_stages datasets); '
                        'press the space bar in this terminal to move to the next stage')
    # Gripper switching is off for now (2026-10-23): stages move only on space / POST /next-stage.
    p.add_argument("--stage-switch", choices=("space", "gripper", "both"), default="space",
                   help="how --stages advance: space bar, the left gripper command (same rule as the "
                        "stage labels: search -> grasp when it opens, grasp -> carry when it closes), or both")
    p.add_argument("--stage-open-delta", type=float, default=6.0,
                   help="gripper switch: opening counts once the command is this much above its start value")
    p.add_argument("--stage-min-grasp-time", type=float, default=2.0,
                   help="gripper switch: stay in the grasp stage at least this long (s); training grasps took 2.2-4.3 s")
    p.add_argument("--stage-close-hold", type=int, default=5,
                   help="gripper switch: steps in a row the command must stay closed before grasp -> carry")
    p.add_argument("--no-end-on-release", dest="end_on_release", action="store_false",
                   help="keep running after the gripper opens in the last stage (default: that ends the model)")
    p.add_argument("--release-hold-steps", type=int, default=15,
                   help="steps kept after the release before the model stops (training kept 15 = 0.5 s)")
    p.add_argument("--episode-time", type=float, default=60, help="seconds per episode")
    p.add_argument("--episodes", type=int, default=1)
    p.add_argument("--reset-time", type=float, default=10, help="pause between episodes (s)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--device", default=None, help="cuda / cpu (default: from the checkpoint)")
    p.add_argument("--robot-id", default="omx_bi_follower", help="calibration id used when recording")
    p.add_argument("--left-port", default="/dev/omx_follower_left")
    p.add_argument("--right-port", default="/dev/omx_follower")
    p.add_argument("--cam-top", default="/dev/cam_top")
    p.add_argument("--cam-wrist-left", default="/dev/cam_wrist_left")
    p.add_argument("--cam-wrist-right", default="/dev/cam_wrist")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--cam-keys", default="auto",
                   help='"auto", or three comma-separated names for top,wrist_left,wrist_right')
    p.add_argument("--top-mask", action="store_true", help="black out top camera outside --top-mask-roi")
    p.add_argument("--top-mask-roi", type=int, nargs=4, default=TOP_MASK_ROI, metavar=("X1", "Y1", "X2", "Y2"))
    p.add_argument("--top-exposure", type=int, default=None,
                   help="manual top-camera exposure, e.g. 90 (default: auto); match the recording")
    p.add_argument("--torch-threads", type=int, default=4,
                   help="torch CPU threads (default 4; more threads slows the control loop on max)")
    p.add_argument("--no-preflight", action="store_true", help="skip clear_motor_errors.py before connecting")
    p.add_argument("--dry-run", action="store_true", help="no robot; feed random observations")
    p.add_argument("--return-via", type=float, nargs=6, metavar="Q",
                   help="6 left normalized joint values; default: measured waypoint")
    p.add_argument("--start-pose", type=float, nargs=6, metavar="Q",
                   help="6 left normalized joint values; default: measured home")
    p.add_argument("--no-return", action="store_true", help="disable automatic return after evaluation")
    p.add_argument("--return-via-time", type=float, default=2.0, help="waypoint trajectory duration (s)")
    p.add_argument("--return-home-time", type=float, default=2.0, help="home trajectory duration (s)")
    p.add_argument("--return-tolerance", type=float, default=2.0, help="arrival tolerance in normalized units")
    p.add_argument("--return-settle-time", type=float, default=3.0, help="arrival timeout after each segment (s)")
    args = p.parse_args(argv)
    if args.no_return:
        if args.return_via is not None or args.start_pose is not None:
            p.error("--no-return cannot be combined with pose overrides")
    elif args.return_via is None and args.start_pose is None:
        args.return_via = DEFAULT_RETURN_VIA.copy()
        args.start_pose = DEFAULT_START_POSE.copy()
    try:
        validate_return_args(args)
        for name in ("fps", "episode_time", "episodes"):
            value = getattr(args, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(args.reset_time) or args.reset_time < 0:
            raise ValueError("reset_time must be non-negative and finite")
    except ValueError as exc:
        p.error(str(exc))
    return args


def pose_action(values):
    """Validate a left pose before any motor connection or movement."""
    if len(values) != len(POSE_KEYS):
        raise ValueError("a pose requires 6 LEFT joint values")
    pose = dict(zip(POSE_KEYS, values))
    for key, value in pose.items():
        low = 0 if key.endswith("gripper.pos") else -100
        if not math.isfinite(value) or not low <= value <= 100:
            raise ValueError(f"{key} must be finite and in [{low}, 100], got {value}")
    return pose


def validate_return_args(args):
    """Also supports older imported callers that don't configure return motion."""
    via, home = getattr(args, "return_via", None), getattr(args, "start_pose", None)
    if (via is None) != (home is None):
        raise ValueError("--return-via and --start-pose must be supplied together")
    if via is None:
        return None
    poses = (pose_action(via), pose_action(home))
    for name in ("return_via_time", "return_home_time", "return_tolerance", "return_settle_time"):
        value = getattr(args, name, None)
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    return poses


def read_joint_positions(robot):
    """Read feedback without waiting for cameras; only the control thread owns the buses."""
    positions = {}
    for side in ("left",):
        values = getattr(robot, f"{side}_arm").bus.sync_read("Present_Position")
        positions.update({f"{side}_{joint}.pos": value for joint, value in values.items()})
    for key in POSE_KEYS:
        if key not in positions or not math.isfinite(positions[key]):
            raise RuntimeError(f"invalid joint feedback: {key}")
    return positions


def return_to_start(robot, args, dry_run=False):
    """Move through two timed segments; never advance if the waypoint isn't reached.

    This function must run on the same thread as policy motor writes. Other threads
    should signal should_return instead of calling this function concurrently.
    """
    poses = validate_return_args(args)
    if poses is None:
        raise ValueError("return requested without --return-via and --start-pose")
    if dry_run:
        logging.info("[dry-run] return via %s -> home %s (no motor commands)", *poses)
        return poses[1]
    for label, target, duration in zip(
        ("via", "home"), poses, (args.return_via_time, args.return_home_time)
    ):
        initial = read_joint_positions(robot)
        started = time.perf_counter()
        logging.info("return %s: duration %.3fs", label, duration)
        while True:
            tick = time.perf_counter()
            fraction = min((tick - started) / duration, 1.0)
            # Smoothstep avoids a step change in commanded position at segment boundaries.
            blend = fraction * fraction * (3 - 2 * fraction)
            command = {key: initial[key] + blend * (target[key] - initial[key]) for key in POSE_KEYS}
            robot.send_action(command)
            if fraction >= 1:
                break
            precise_sleep(max(0, 1 / args.fps - (time.perf_counter() - tick)))
        deadline = time.perf_counter() + args.return_settle_time
        stable_samples = 0
        while True:
            actual = read_joint_positions(robot)
            error = max(abs(actual[key] - target[key]) for key in POSE_KEYS)
            stable_samples = stable_samples + 1 if error <= args.return_tolerance else 0
            if stable_samples >= 3:
                break
            if time.perf_counter() >= deadline:
                raise TimeoutError(f"return {label}: arrival not confirmed (max joint error {error:.3f})")
            precise_sleep(1 / args.fps)
        logging.info("return %s reached", label)
    return poses[1]


def load_policy(path, device=None):
    """Load policy + its saved pre/post-processors (normalization stats come from the checkpoint)."""
    cfg = PreTrainedConfig.from_pretrained(path)
    cfg.pretrained_path = path
    if device:
        cfg.device = device
    policy = get_policy_class(cfg.type).from_pretrained(path, config=cfg)
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg,
        pretrained_path=path,
        preprocessor_overrides={"device_processor": {"device": cfg.device}},
    )
    return policy, preprocessor, postprocessor


def make_robot(args, policy_type):
    if args.cam_keys == "auto":
        keys = ["camera1", "camera2", "camera3"] if policy_type == "smolvla" else ["top", "wrist_left", "wrist_right"]
    else:
        keys = [k.strip() for k in args.cam_keys.split(",")]
    devs = [args.cam_top, args.cam_wrist_left, args.cam_wrist_right]
    cameras = {
        k: OpenCVCameraConfig(index_or_path=d, width=args.width, height=args.height, fps=args.fps, fourcc="MJPG")
        for k, d in zip(keys, devs)
    }
    cfg = BiOmxFollowerConfig(
        id=args.robot_id,
        left_arm_port=args.left_port,
        right_arm_port=args.right_port,
        cameras=cameras,
        mask_rois={keys[0]: list(args.top_mask_roi)} if args.top_mask else {},
    )
    return LeftOnlyBiOmxFollower(cfg)


def setup_top_exposure(args):
    """Same as eval_bi.sh: auto exposure first; a manual value is applied by set_top_exposure.sh
    in the background once the stream has started (the camera resets exposure on stream start)."""
    subprocess.run(["v4l2-ctl", "-d", args.cam_top, "-c", "auto_exposure=3"], check=False)
    if args.top_exposure is None:
        logging.info("[top cam] auto exposure")
        return None
    return subprocess.Popen([str(helper("set_top_exposure.sh")), str(args.top_exposure)])


def preflight(args):
    """clear_motor_errors.py on both followers (leaders are not used); stops here if a motor is dead."""
    r = subprocess.run([sys.executable, str(helper("clear_motor_errors.py")), args.left_port])
    if r.returncode != 0:
        raise SystemExit("motor preflight failed (see above) - check 12V power / cables, then retry")


def torque_off(args):
    """Fallback when robot.disconnect() fails: reboot latched motors and switch torque off directly."""
    import dynamixel_sdk as dxl
    subprocess.run([sys.executable, str(helper("clear_motor_errors.py")), args.left_port])
    for port in (args.left_port,):
        ph = dxl.PortHandler(port)
        if not ph.openPort():
            continue
        ph.setBaudRate(1_000_000)
        pk = dxl.PacketHandler(2.0)
        for motor_id in range(11, 17):
            pk.write1ByteTxRx(ph, motor_id, 64, 0)  # Torque_Enable = 0
        ph.closePort()
    logging.warning("torque switched off directly after a failed disconnect")


class SpaceKey:
    """Counts space-bar presses in this terminal without Enter (background thread, cbreak mode)."""

    def __init__(self):
        self.presses = 0
        self._stop = threading.Event()
        self._fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        if self._fd is None:
            logging.warning("stdin is not a terminal: stage switching by space bar is off")
            return
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0] and sys.stdin.read(1) == " ":
                self.presses += 1

    def close(self):
        self._stop.set()
        if self._fd is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)


def fake_observation(robot):
    """Random observation with the robot's feature layout (for --dry-run)."""
    obs = {}
    for k, ft in robot.observation_features.items():
        obs[k] = np.random.randint(0, 256, ft, dtype=np.uint8) if isinstance(ft, tuple) else float(np.random.randn())
    return obs


class GripperStages:
    """Advance stages from the left gripper command, like stages/find_stages.py labels them.

    stage 0 -> 1 when the command opens past start + delta; 1 -> 2 when it falls back below
    halfway between its start and the widest opening seen. Later stages need space / API.
    """
    def __init__(self, delta, min_grasp_steps=0, hold_steps=1):
        self.delta, self.closed, self.peak, self.count = delta, None, None, 0
        # grasp -> carry only after min_grasp_steps in grasp and hold_steps in a row below the line,
        # so a small wobble right after opening cannot cut the grasp short.
        self.min_grasp_steps, self.hold_steps = min_grasp_steps, hold_steps
        self.grasp_steps = self.below = 0

    def update(self, gripper):
        if gripper is None:
            return self.count
        # Closed value = lowest command seen while searching: the first command can sit a few
        # points high (50.4 then ~47.5 on the robot), which pushed the threshold out of reach.
        if self.count == 0:
            self.closed = gripper if self.closed is None else min(self.closed, gripper)
        if self.count == 0 and gripper > self.closed + self.delta:
            self.count, self.peak = 1, gripper
        elif self.count == 1:
            self.peak = max(self.peak, gripper)
            self.grasp_steps += 1
            self.below = self.below + 1 if gripper < (self.closed + self.peak) / 2 else 0
            if self.grasp_steps >= self.min_grasp_steps and self.below >= self.hold_steps:
                self.count = 2
        elif self.count == 2 and gripper > (self.closed + self.peak) / 2:
            self.count = 3  # released over the box (same "release" rule as the labels)
        return self.count


def run_episode(robot, policy, preprocessor, postprocessor, features, args, dry_run=False,
                should_return=None, next_stage=None, on_stage=None):
    """Evaluate then optionally return; preserve the (policy_steps, last_action) API.

    should_return(obs) is polled before and after inference. It must be non-blocking
    and latched until observed (e.g. threading.Event). After it returns True,
    no further policy action is sent. No automatic gripper/B-area detector is assumed.
    """
    return_poses = validate_return_args(args)
    if should_return is not None and return_poses is None:
        raise ValueError("should_return requires return_via and start_pose")
    policy.reset()
    preprocessor.reset()
    postprocessor.reset()
    device = get_safe_torch_device(policy.config.device)
    stages = [t.strip() for t in args.stages.split("|")] if args.stages else [args.task]
    switch = getattr(args, "stage_switch", "space")
    multi = len(stages) > 1
    keys = SpaceKey() if multi and switch in ("space", "both") else None
    grip = GripperStages(getattr(args, "stage_open_delta", 6.0),
                         int(getattr(args, "stage_min_grasp_time", 2.0) * args.fps),
                         getattr(args, "stage_close_hold", 5)) if multi and switch in ("gripper", "both") else None
    stage = 0
    logging.info(f"stage 1/{len(stages)}: {stages[0]!r}")
    if on_stage is not None:
        on_stage(0, stages[0])
    start = time.perf_counter()
    steps = slow = 0
    second_max = None
    released_at = None  # step at which the gripper opened in the last stage
    args.end_reason = "time"
    end_on_release = getattr(args, "end_on_release", True)
    action = {}
    try:
        while time.perf_counter() - start < args.episode_time:
            t0 = time.perf_counter()
            obs = fake_observation(robot) if dry_run else robot.get_observation()
            if should_return is not None and should_return(obs):
                logging.info("external return requested before inference")
                args.end_reason = "gripper_open"
                break
            if released_at is not None and steps - released_at >= getattr(args, "release_hold_steps", 15):
                logging.info(">>> MODEL DONE: gripper opened in the last stage")
                args.end_reason = "released"
                break
            # Any source may move on: space presses, API next-stage requests, the gripper rule.
            sources = {"space": keys.presses if keys is not None else 0,
                       "api": next_stage() if next_stage is not None else 0,
                       "gripper": grip.count if grip is not None else 0}
            wanted = max(sources.values())
            if multi and stage == len(stages) - 1 and max(sources["space"], sources["api"]) > stage:
                # One more space / next-stage in the last stage = the task is done.
                logging.info(">>> MODEL DONE: next pressed in the last stage")
                args.end_reason = "next_stage"
                break
            if wanted > stage and stage < len(stages) - 1:
                stage += 1
                policy.reset()  # drop the actions planned for the previous stage
                by = ", ".join(k for k, v in sources.items() if v >= stage)
                logging.info(f">>> STAGE {stage + 1}/{len(stages)}: {stages[stage]!r}  (by {by}, "
                             f"{time.perf_counter() - start:.1f}s)")
                if on_stage is not None:
                    on_stage(stage, stages[stage])
            observation_frame = build_dataset_frame(features, obs, prefix=OBS_STR)
            action_values = predict_action(
                observation=observation_frame,
                policy=policy,
                device=device,
                preprocessor=preprocessor,
                postprocessor=postprocessor,
                use_amp=policy.config.use_amp,
                task=stages[stage],
                robot_type=robot.robot_type,
            )
            # A request arriving during inference must not be followed by another policy write.
            if should_return is not None and should_return(obs):
                logging.info("external return requested during inference")
                args.end_reason = "gripper_open"
                break
            action = make_robot_action(action_values, features)  # {"left_shoulder_pan.pos": ..., ...}
            if grip is not None:
                g = action.get("left_gripper.pos")
                grip.update(g)
                if (end_on_release and released_at is None and grip.count >= 3
                        and stage == len(stages) - 1):
                    released_at = steps
                    logging.info(f">>> RELEASE detected in the last stage (command {g:.1f}); "
                                 f"stopping after {getattr(args, 'release_hold_steps', 15)} more steps")
                if g is not None:
                    second_max = g if second_max is None else max(second_max, g)
                if steps % args.fps == 0 and g is not None:  # about once a second
                    if grip.count == 0:
                        rule = f"opens past {grip.closed + grip.delta:.1f}"
                    elif grip.count >= 2 and stage == len(stages) - 1:
                        rule = (f"opens past {(grip.closed + grip.peak) / 2:.1f} (release ends the model)"
                                if grip.count == 2 else "released")
                    elif grip.count == 1:
                        left = max(0.0, (grip.min_grasp_steps - grip.grasp_steps) / args.fps)
                        rule = (f"closes below {(grip.closed + grip.peak) / 2:.1f} (peak {grip.peak:.1f}) "
                                f"for {grip.hold_steps} steps" + (f", earliest in {left:.1f}s" if left else ""))
                    else:
                        rule = "done"
                    logging.info(f"stage {stage + 1}/{len(stages)} | left gripper command {g:.1f} "
                                 f"(max in last 1s {second_max:.1f}) | next switch when it {rule}")
                    second_max = None
            if not dry_run:
                robot.send_action(action)
            steps += 1
            dt = time.perf_counter() - t0
            if dt > 1 / args.fps:
                slow += 1
                logging.warning(f"loop {1 / dt:.1f} Hz is slower than target {args.fps} Hz")
            precise_sleep(max(1 / args.fps - dt, 0.0))
    finally:
        if keys is not None:
            keys.close()
        elapsed = time.perf_counter() - start
        if steps:
            logging.info(f"episode: {steps} steps in {elapsed:.1f}s = average {steps / elapsed:.1f} Hz "
                         f"(target {args.fps}), slow loops {slow} ({100 * slow / steps:.0f}%)")
    if return_poses is not None:
        action = return_to_start(robot, args, dry_run=dry_run)
    return steps, action


def main(argv=None):
    args = parse_args(argv)
    init_logging()
    policy, preprocessor, postprocessor = load_policy(args.policy_path, args.device)
    robot = make_robot(args, policy.config.type)
    # Feature layout used to pack observations and unpack the action vector (names in robot order).
    features = combine_feature_dicts(
        hw_to_dataset_features(robot.action_features, ACTION),
        hw_to_dataset_features(robot.observation_features, OBS_STR),
    )
    logging.info(f"torch threads: {torch.get_num_threads()}")
    if not args.dry_run:
        if not args.no_preflight:
            preflight(args)
        setup_top_exposure(args)
        robot.connect()
    try:
        for ep in range(args.episodes):
            logging.info(f"episode {ep + 1}/{args.episodes}: {args.task!r}")
            steps, action = run_episode(robot, policy, preprocessor, postprocessor, features, args, args.dry_run)
            logging.info(f"episode {ep + 1} done, {steps} steps; last action: {action}")
            if ep < args.episodes - 1:
                logging.info(f"reset the scene ({args.reset_time}s)")
                time.sleep(args.reset_time)
    except KeyboardInterrupt:
        logging.info("stopped by user")
    finally:
        if not args.dry_run and robot.is_connected:
            try:
                robot.disconnect()
            except Exception as e:  # noqa: BLE001 - never leave the arms with torque on
                logging.error(f"disconnect failed: {e}")
                torque_off(args)


if __name__ == "__main__":
    main()
