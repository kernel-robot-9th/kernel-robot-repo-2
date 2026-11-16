"""Read both follower arms and save the pose under a name (read-only: nothing is written to the motors).

Usage: python measure_pose.py <name>      e.g. start, via, above_target, descend, lift, gripper_open, gripper_close
       python measure_pose.py             (just print the current pose)
Move the arms by hand with torque OFF, then run. Saved to measured_poses.json next to this file.
Values use the same LeRobot normalization as left_start_pose_measured.json
(calibration range 0..4095: body -100..100, gripper 0..100).
"""
import json
import statistics
import sys
import time
from pathlib import Path

import dynamixel_sdk as dxl

NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
PORTS = {"left": "/dev/omx_follower_left", "right": "/dev/omx_follower"}
OUT = Path(__file__).with_name("measured_poses.json")


def read_raw(port, samples=5):
    ph = dxl.PortHandler(port)
    if not ph.openPort():
        raise RuntimeError(f"cannot open {port}")
    try:
        ph.setBaudRate(1_000_000)
        pk = dxl.PacketHandler(2.0)
        rows = []
        for _ in range(samples):
            row = []
            for motor in range(11, 17):
                value, result, error = pk.read4ByteTxRx(ph, motor, 132)  # Present_Position
                if result != 0:
                    raise RuntimeError(f"{port} id {motor}: read failed")
                row.append(value - 2**32 if value >= 2**31 else value)
            rows.append(row)
            time.sleep(0.02)
        torque = [pk.read1ByteTxRx(ph, m, 64)[0] for m in range(11, 17)]
    finally:
        ph.closePort()
    return [int(statistics.median(col)) for col in zip(*rows)], torque


def normalize(raw):
    return [round(x / 4095 * 200 - 100 if i < 5 else x / 4095 * 100, 2) for i, x in enumerate(raw)]


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    pose = {}
    for side, port in PORTS.items():
        raw, torque = read_raw(port)
        values = normalize(raw)
        pose[side] = {"values": values, "raw": raw}
        print(f"{side:5s} " + "  ".join(f"{n}={v:7.2f}" for n, v in zip(NAMES, values))
              + ("   (torque ON)" if any(torque) else ""))
    if name:
        data = json.loads(OUT.read_text()) if OUT.exists() else {}
        data[name] = {**pose, "joint_names": NAMES, "captured_at_unix": time.time()}
        OUT.write_text(json.dumps(data, indent=2))
        print(f"saved '{name}' to {OUT}")


if __name__ == "__main__":
    main()
