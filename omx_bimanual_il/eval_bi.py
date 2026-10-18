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
"""
import argparse
import logging
import subprocess
import time
from pathlib import Path

import numpy as np

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

register_third_party_plugins()
from lerobot_robot_bi_omx.bi_omx import BiOmxFollower, BiOmxFollowerConfig  # noqa: E402

# Same keep-rectangle as masking/mask_dataset_stream.py and eval_bi.sh TOP_MASK=1 (x1 y1 x2 y2).
TOP_MASK_ROI = [0, 200, 400, 480]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--policy-path", required=True, help="checkpoint folder: .../checkpoints/<step>/pretrained_model")
    p.add_argument("--task", default="", help="instruction text (SmolVLA: use the exact sentence from recording)")
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
    p.add_argument("--dry-run", action="store_true", help="no robot; feed random observations")
    return p.parse_args(argv)


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
    return BiOmxFollower(cfg)


def setup_top_exposure(args):
    """Same as eval_bi.sh: auto exposure first; a manual value is applied by set_top_exposure.sh
    in the background once the stream has started (the camera resets exposure on stream start)."""
    subprocess.run(["v4l2-ctl", "-d", args.cam_top, "-c", "auto_exposure=3"], check=False)
    if args.top_exposure is None:
        logging.info("[top cam] auto exposure")
        return None
    script = Path(__file__).resolve().parent / "set_top_exposure.sh"
    return subprocess.Popen([str(script), str(args.top_exposure)])


def fake_observation(robot):
    """Random observation with the robot's feature layout (for --dry-run)."""
    obs = {}
    for k, ft in robot.observation_features.items():
        obs[k] = np.random.randint(0, 256, ft, dtype=np.uint8) if isinstance(ft, tuple) else float(np.random.randn())
    return obs


def run_episode(robot, policy, preprocessor, postprocessor, features, args, dry_run=False):
    """One episode of observe -> predict -> act at args.fps (lerobot_record.record_loop, policy branch)."""
    policy.reset()
    preprocessor.reset()
    postprocessor.reset()
    device = get_safe_torch_device(policy.config.device)
    start = time.perf_counter()
    steps = 0
    while time.perf_counter() - start < args.episode_time:
        t0 = time.perf_counter()
        obs = fake_observation(robot) if dry_run else robot.get_observation()
        observation_frame = build_dataset_frame(features, obs, prefix=OBS_STR)
        action_values = predict_action(
            observation=observation_frame,
            policy=policy,
            device=device,
            preprocessor=preprocessor,
            postprocessor=postprocessor,
            use_amp=policy.config.use_amp,
            task=args.task,
            robot_type=robot.robot_type,
        )
        action = make_robot_action(action_values, features)  # {"left_shoulder_pan.pos": ..., ...}
        if not dry_run:
            robot.send_action(action)
        steps += 1
        dt = time.perf_counter() - t0
        if dt > 1 / args.fps:
            logging.warning(f"loop {1 / dt:.1f} Hz is slower than target {args.fps} Hz")
        precise_sleep(max(1 / args.fps - dt, 0.0))
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
    if not args.dry_run:
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
            robot.disconnect()


if __name__ == "__main__":
    main()
