"""One explicitly requested slow left-only return test; no policy or cameras.

Torque is disabled on completion/failure/interrupt so the arm can be repositioned.
Uses the saved poses and return implementation in eval_bi.py.
"""
import logging
import subprocess
from types import SimpleNamespace

from eval_bi import (
    DEFAULT_RETURN_VIA, DEFAULT_START_POSE, JOINT_NAMES, return_to_start,
)
from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", force=True)
    port = "/dev/omx_follower_left"
    occupied = subprocess.run(["fuser", port], capture_output=True, text=True)
    if occupied.returncode != 1:
        raise RuntimeError(f"Port busy or ownership check failed: {occupied.stdout} {occupied.stderr}")
    arm = OmxFollower(OmxFollowerConfig(id="omx_bi_follower_left", port=port, cameras={}))
    bus = arm.bus
    completed = False
    enabled = False
    try:
        # Bus connection only: do not configure motors or change calibration/modes.
        bus.connect()
        if not bus.is_calibrated:
            raise RuntimeError("Calibration mismatch; no motion performed")
        modes = bus.sync_read("Operating_Mode", normalize=False)
        for name, mode in modes.items():
            if mode not in ((3, 5) if name == "gripper" else (3, 4)):
                raise RuntimeError(f"Unexpected operating mode for {name}: {mode}")
        raw = bus.sync_read("Present_Position", normalize=False)
        if any(not 0 <= value <= 4095 for value in raw.values()):
            raise RuntimeError(f"Position outside measured calibration range: {raw}")
        errors = bus.sync_read("Hardware_Error_Status", normalize=False)
        if any(errors.values()):
            raise RuntimeError(f"Motor hardware errors: {errors}")
        current = bus.sync_read("Present_Position")
        logging.info("LEFT current position: %s", current)
        # Seed the current position before enabling torque, avoiding a stale goal.
        bus.sync_write("Goal_Position", current)
        enabled = True
        bus.enable_torque()

        def send_left(action):
            errors = bus.sync_read("Hardware_Error_Status", normalize=False)
            if any(errors.values()):
                raise RuntimeError(f"Motor hardware errors during return: {errors}")
            target = {name: action[f"left_{name}.pos"] for name in JOINT_NAMES}
            actual = bus.sync_read("Present_Position")
            if max(abs(target[name] - actual[name]) for name in JOINT_NAMES) > 15:
                raise RuntimeError("Excessive tracking error; aborting return")
            bus.sync_write("Goal_Position", target)
            return action

        robot = SimpleNamespace(left_arm=arm, send_action=send_left)
        args = SimpleNamespace(
            return_via=DEFAULT_RETURN_VIA, start_pose=DEFAULT_START_POSE,
            return_via_time=6.0, return_home_time=6.0,
            return_tolerance=2.0, return_settle_time=4.0, fps=30,
        )
        gripper_open_signal = True
        if gripper_open_signal:
            logging.info("Simulated gripper_open=True: starting one slow return")
            return_to_start(robot, args)
        logging.info("LEFT final position: %s", bus.sync_read("Present_Position"))
        completed = True
        logging.info("COMPLETED: home reached; disabling left torque for manual repositioning")
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=enabled)


if __name__ == "__main__":
    main()
