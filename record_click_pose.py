#!/usr/bin/env python3
"""Save the left arm's current pose for a click-pick stage (read-only: nothing is written to the motors).

Like measure_pose.py, but in click-pick units (raw motor pulses, IDs 11-15) so the pose can
replace a stage in click_pick_yolo.py / eval_bi_api_yolo.py.

  conda activate main_project
  cd ~/kernel-robot-repo-2-il
  python record_click_pose.py                 # print the current pose only
  python record_click_pose.py carry_high      # save it as CARRY_HIGH
  python record_click_pose.py --remove carry_high   # go back to the click-pick default

Move the arm by hand with torque OFF first (the API server turns torque off at home after a run).
Stop the API server's motion and anything else using the arm port (one program per port).
Saved to click_pick_poses.json next to this file. Stages that can be replaced (fixed poses):
  HIGH, CARRY_HIGH, DROP_RELEASE, RETURN_HIGH
(by default CARRY_HIGH, HIGH and RETURN_HIGH all use click pick's hover_high).
"""
import argparse
import json
import sys
from pathlib import Path

OMX = Path.home() / "main_project" / "omxtest-main"
sys.path.insert(0, str(OMX / "tools" / "picking"))

from omx_pick import profile_for  # noqa: E402
from omx_pick_setup import read_snapshot  # noqa: E402
import left_arm_only  # noqa: E402,F401  (left follower only, even with both arms plugged in)

OUT = Path(__file__).with_name("click_pick_poses.json")
STAGES = ("high", "carry_high", "drop_release", "return_high")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", nargs="?", choices=STAGES)
    p.add_argument("--remove", action="store_true", help="delete the saved pose for NAME")
    args = p.parse_args()
    data = json.loads(OUT.read_text()) if OUT.exists() else {"note": __doc__.splitlines()[0], "poses": {}}

    if args.remove:
        if not args.name:
            p.error("--remove needs a NAME")
        removed = data["poses"].pop(args.name, None)
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"removed {args.name}" if removed else f"{args.name} was not saved")
        return

    snap = read_snapshot(profile_for(None))
    pose = {"arm_pulses": snap["arm_pulses"], "model_xyz_mm": [round(v, 1) for v in snap["model_xyz_mm"]],
            "gripper_pulse": snap["motors"][-1]["position"], "recorded_at": snap["recorded_at"]}
    print("arm pulses (ID11-15):", pose["arm_pulses"])
    print("model XYZ mm:", pose["model_xyz_mm"])
    if not args.name:
        return
    old = data["poses"].get(args.name)
    if old:
        print("previous:", old["arm_pulses"], old["model_xyz_mm"])
    data["poses"][args.name] = pose
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"saved {args.name.upper()} -> {OUT}")


if __name__ == "__main__":
    main()
