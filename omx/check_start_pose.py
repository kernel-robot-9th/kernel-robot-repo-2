"""Compare the followers' current joint positions with the start pose of a training dataset (read-only).

Usage: python check_start_pose.py [dataset]   (default: jaewoo112/bi_gauze_one_exposure)
Prints each joint's current value, the training start value, and flags joints that are far off.
Nothing is written to the motors.
"""
import glob
import sys
from pathlib import Path

import dynamixel_sdk as dxl
import numpy as np
import pandas as pd

REPO = sys.argv[1] if len(sys.argv) > 1 else "jaewoo112/bi_gauze_one_exposure"
ROOT = Path.home() / ".cache/huggingface/lerobot" / REPO
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
PORTS = [("left", "/dev/omx_follower_left"), ("right", "/dev/omx_follower")]


def read_norm(port):
    """Present_Position of ids 11-16, normalised like the dataset (range 0..4095 calibration)."""
    ph = dxl.PortHandler(port)
    ph.openPort()
    ph.setBaudRate(1_000_000)
    pk = dxl.PacketHandler(2.0)
    raw = [pk.read4ByteTxRx(ph, i, 132)[0] for i in range(11, 17)]
    ph.closePort()
    raw = [x - 2**32 if x >= 2**31 else x for x in raw]
    return [x / 4095 * 200 - 100 if i < 5 else x / 4095 * 100 for i, x in enumerate(raw)]


data = pd.concat(
    pd.read_parquet(f, columns=["frame_index", "observation.state"]) for f in glob.glob(str(ROOT / "data/*/*.parquet"))
)
start = np.stack(data[data.frame_index == 0]["observation.state"].values)
mean, std = start.mean(0), start.std(0)
now = read_norm(PORTS[0][1]) + read_norm(PORTS[1][1])

print(f"start pose of {REPO} ({len(start)} episodes) vs now")
bad = 0
for i, (v, m, s) in enumerate(zip(now, mean, std)):
    side, joint = PORTS[i // 6][0], NAMES[i % 6]
    off = abs(v - m) > max(3 * s, 8)
    bad += off
    print(f"  {side:5s} {joint:13s} now {v:7.1f}   train {m:7.1f} ±{s:4.1f}   {'<-- move' if off else 'ok'}")
print("all joints close to the training start pose" if not bad else f"{bad} joint(s) far from the training start pose")
