#!/usr/bin/env python3
"""Re-record the both-arm pinky poses straight into pinky_sequence.json (read-only on the motors).

Move the arms by hand with torque OFF, then run one line per pose:
  conda activate main_project
  cd ~/kernel-robot-repo-2-il
  python pinky_record.py                      # just print both arms (nothing saved)
  python pinky_record.py approach_high        # both arms, high over the container wall
  python pinky_record.py above_target         # right arm only (left keeps approach_high), as before
  python pinky_record.py above_target --arms left right   # record both arms here instead
  python pinky_record.py lift                 # both arms, object lifted
  python pinky_record.py hold                 # grippers closed on the object -> close = reading - 5
  python pinky_record.py open                 # grippers opened by hand as wide as wanted -> open (release),
                                              #   approach = rest + 2/3 of (open - rest), as before
  python pinky_record.py show                 # print the poses now in the file
  python pinky_record.py torque-off           # both arms limp (hold them first!) so you can move them by hand
  python pinky_move.py --check                # validate the file afterwards

Before the first change a copy is kept: pinky_sequence.json.<time>.bak (one per run).
The return poses (via / start) and the open / rest / approach gripper values are not touched.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

from measure_pose import PORTS, normalize, read_raw

SEQ = Path(__file__).with_name("pinky_sequence.json")
STEPS = ("approach_high", "above_target", "lift")
DEFAULT_ARMS = {"approach_high": ["left", "right"], "above_target": ["right"], "lift": ["left", "right"]}


def read_both():
    pose = {}
    for side, port in PORTS.items():
        raw, torque = read_raw(port)
        values = normalize(raw)
        pose[side] = values
        print(f"{side:5s} body {values[:5]}  gripper {values[5]}" + ("   (torque ON)" if any(torque) else ""))
    return pose


def backup():
    dst = SEQ.with_name(f"{SEQ.name}.{time.strftime('%Y%m%d_%H%M%S')}.bak")
    shutil.copy2(SEQ, dst)
    print(f"backup: {dst.name}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pose", nargs="?", choices=[*STEPS, "hold", "open", "show", "torque-off"])
    p.add_argument("--arms", nargs="+", choices=["left", "right"], help="arms to save for this pose")
    args = p.parse_args()
    data = json.loads(SEQ.read_text())

    if args.pose == "torque-off":
        import dynamixel_sdk as dxl
        if input("Both arms will go limp and fall. Hold them, then type OFF: ").strip() != "OFF":
            print("cancelled")
            return
        for side, port in PORTS.items():
            ph = dxl.PortHandler(port)
            if not ph.openPort():
                print(f"{side}: cannot open {port} (in use?)")
                continue
            ph.setBaudRate(1_000_000)
            pk = dxl.PacketHandler(2.0)
            for motor_id in range(11, 17):
                pk.write1ByteTxRx(ph, motor_id, 64, 0)  # Torque_Enable = 0
            ph.closePort()
            print(f"{side}: torque off")
        return

    if args.pose == "show":
        for step in data["steps"]:
            print(step["name"], {k: step[k] for k in ("left", "right", "gripper") if k in step})
        print("gripper", data["gripper"])
        return

    pose = read_both()
    if not args.pose:
        return
    backup()
    if args.pose == "hold":
        for side in ("left", "right"):
            g = data["gripper"][side]
            old = (g.get("close"), g.get("measured_hold"))
            g["measured_hold"] = pose[side][5]
            g["close"] = round(pose[side][5] - 5, 2)  # squeeze a little past the measured hold
            print(f"{side} gripper close {old[0]} -> {g['close']} (hold {old[1]} -> {g['measured_hold']})")
    elif args.pose == "open":
        for side in ("left", "right"):
            g = data["gripper"][side]
            old = (g.get("open"), g.get("approach"))
            g["open"] = pose[side][5]
            g["approach"] = round(g["rest"] + (g["open"] - g["rest"]) * 2 / 3, 2)
            print(f"{side} gripper open {old[0]} -> {g['open']}, approach {old[1]} -> {g['approach']}")
    else:
        step = next(s for s in data["steps"] if s["name"] == args.pose)
        for side in args.arms or DEFAULT_ARMS[args.pose]:
            print(f"{args.pose} {side}: {step.get(side)} -> {pose[side][:5]}")
            step[side] = pose[side][:5]
    data["note"] = (data.get("note", "").split(" | re-recorded")[0]
                    + f" | re-recorded {time.strftime('%Y-%m-%d %H:%M')} with pinky_record.py")
    SEQ.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"saved {args.pose} to {SEQ.name}; check with: python pinky_move.py --check")


if __name__ == "__main__":
    main()
