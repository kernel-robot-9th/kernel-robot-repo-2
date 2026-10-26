#!/usr/bin/env python3
"""omx_click_pick.py run --live, but the grasp point comes from YOLO instead of a click.

Same config, calibration, plan and motion code as
  ~/main_project/omxtest-main/tools/picking/omx_click_pick.py run --live
(imported, not copied). Only the click is replaced by --uv (1920x1080 pixel).

  python click_pick_yolo.py --uv 1004 739            # dry run: print the plan, no motors
  python click_pick_yolo.py --uv 1004 739 --live     # move; asks MOVE / PICK / DROP in this terminal
  python click_pick_yolo.py --uv 1004 739 --live --auto   # move without typed confirmations
  python click_pick_yolo.py --uv 1004 739 --live --step   # SPACE before every stage, q = stop

Stages: HIGH -> OPEN -> APPROACH -> HOVER -> PICK -> CLOSE -> LIFT -> RETREAT -> CARRY_HIGH
        -> DROP_RELEASE -> RELEASE -> RETURN_HIGH -> DROP_RETREAT. Torque stays on at the end.
Each stage start prints a line "STAGE <name>" (eval_bi_api_yolo.py turns it into /status phase).
Exit code 0 = all stages sent, 3 = cancelled at a confirmation, 2 = error.
"""
import argparse
import json
import sys
from pathlib import Path

OMX = Path.home() / "main_project" / "omxtest-main"
sys.path.insert(0, str(OMX / "tools" / "picking"))

import omx_click_pick as ocp  # noqa: E402  (needs the path above)
from step_key import wait_space  # noqa: E402  (this folder)
import left_arm_only  # noqa: E402,F401  (left follower only, even with both arms plugged in)
from omx_pick import Journal, profile_for, saved_for  # noqa: E402

PROMPT_WORDS = ("MOVE", "PICK", "DROP")
POSES_FILE = Path(__file__).with_name("click_pick_poses.json")  # record_click_pose.py
REPLACEABLE = ("HIGH", "CARRY_HIGH", "DROP_RELEASE", "RETURN_HIGH")


def pick_xyz(pulse_list):
    """Model XYZ (mm) of an arm pose, same forward kinematics as omx_click_pick."""
    from omx_pick import legacy
    from omx_tool_direction import pulse_to_q
    xyz, _ = legacy("02_omx_xyz_offline.py", "click_posture_fk").forward(pulse_to_q(list(pulse_list)))
    return [round(float(v) * 1000, 1) for v in xyz]


def apply_stage_offsets(plan, offsets, stages=("APPROACH",)):
    """--joint-offset 12:-40 14:20 -> add pulses to those motor IDs in the --offset-stages stages."""
    from pick_core import pulses
    delta = [0] * 5
    for item in offsets:
        motor, _, value = item.partition(":")
        motor, value = int(motor), int(value)
        if motor not in (11, 12, 13, 14, 15) or abs(value) > 227:
            raise ValueError(f"--joint-offset {item}: ID 11-15, at most ±227 pulses (±20 deg)")
        delta[motor - 11] += value
    for stage in plan["stages"]:
        if stage["name"] in stages and stage["kind"] == "arm":
            before = list(stage["target"])
            values = [int(v) + d for v, d in zip(before, delta)]
            values[4] %= 4096
            stage["target"] = pulses(values)
            print(f"{stage['name']} offset {delta}: pulses {before} -> {values}; "
                  f"model XYZ mm {pick_xyz(before)} -> {pick_xyz(values)}", flush=True)
    plan["stage_offsets"] = {"stages": list(stages), "delta_pulses": delta}


def apply_saved_poses(plan, path=POSES_FILE):
    """Replace fixed-pose stages with poses saved by record_click_pose.py (e.g. carry_high)."""
    from pick_core import pulses
    if not path.exists():
        return []
    saved = json.loads(path.read_text()).get("poses", {})
    replaced = []
    for stage in plan["stages"]:
        pose = saved.get(stage["name"].lower())
        if pose and stage["name"] in REPLACEABLE and stage["kind"] == "arm":
            stage["target"] = pulses(pose["arm_pulses"])
            replaced.append(stage["name"])
    plan["replaced_stages"] = replaced
    return replaced


def typed_answer(prompt):
    """input() with the prompt on its own line, so a parent reading stdout line by line shows it."""
    print(prompt, flush=True)
    answer = input()
    print(f"  -> {answer.strip()}", flush=True)
    return answer


def auto_answer(prompt):
    """Answer the confirmation word the prompt asks for (used with --auto)."""
    for word in PROMPT_WORDS:
        if f"{word} 입력" in prompt:
            print(prompt + word + "  [auto]", flush=True)
            return word
    raise RuntimeError(f"unexpected prompt in --auto mode: {prompt}")


def step_answer(prompt):
    """--step: MOVE waits for SPACE; PICK / DROP pass, because every stage already waits for SPACE."""
    for word in PROMPT_WORDS:
        if f"{word} 입력" in prompt:
            if word == "MOVE":
                wait_space("MOVE (torque on, start click pick)")
            return word
    raise RuntimeError(f"unexpected prompt in --step mode: {prompt}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uv", type=float, nargs=2, required=True, help="grasp point, calibration-size pixels")
    p.add_argument("--live", action="store_true", help="move the arm (default: plan only)")
    p.add_argument("--auto", action="store_true", help="skip typed MOVE / PICK / DROP confirmations")
    p.add_argument("--skip", nargs="*", default=[], metavar="STAGE",
                   help="leave these stages out of the plan, e.g. --skip DROP_RETREAT")
    p.add_argument("--joint-offset", nargs="*", default=[], metavar="ID:PULSES",
                   help="add pulses to motor IDs in the --offset-stages stages, e.g. --joint-offset 12:-30 14:20")
    p.add_argument("--offset-stages", nargs="+", default=["APPROACH"], metavar="STAGE",
                   help="stages that get --joint-offset (default: APPROACH)")
    p.add_argument("--close-extra", type=int, default=0,
                   help="CLOSE target this many pulses past click pick's close_pulse (more squeeze on thin bags)")
    p.add_argument("--open-scale", type=float, default=1.0,
                   help="OPEN stage opening as a fraction of close->open (e.g. 0.667 = 2/3 as wide)")
    p.add_argument("--step", action="store_true", help="wait for SPACE before every stage (q = stop)")
    p.add_argument("--hover", action="store_true", help="hover 20 mm above, no grip, back to HIGH")
    p.add_argument("--config", type=Path, default=ocp.DEFAULT_CONFIG)
    p.add_argument("--output", type=Path, help="JSONL log of the live run (must not exist)")
    args = p.parse_args(argv)
    ask = step_answer if args.step else auto_answer if args.auto else typed_answer

    profile = profile_for(None)
    cfg, calibration = ocp.load_job(args.config, profile)
    saved = saved_for(profile, args.hover)
    plan = ocp.plan_for_click(cfg, calibration, saved, args.uv, hover=args.hover)
    unknown = set(args.skip) - {s["name"] for s in plan["stages"]}
    if unknown:
        raise ValueError(f"--skip: no such stage {sorted(unknown)}")
    plan["stages"] = [s for s in plan["stages"] if s["name"] not in args.skip]
    plan["skipped_stages"] = list(args.skip)
    if args.open_scale != 1.0:
        if not 0.2 <= args.open_scale <= 1.0:
            raise ValueError("--open-scale must be between 0.2 and 1.0")
        g = cfg["gripper"]
        target = round(g["close_pulse"] + (g["open_pulse"] - g["close_pulse"]) * args.open_scale)
        for stage in plan["stages"]:
            if stage["name"] == "OPEN":
                stage["target"] = target
        print(f"OPEN gripper pulse {g['open_pulse']} -> {target} ({args.open_scale:.0%} of close {g['close_pulse']}"
              f" -> open {g['open_pulse']}); RELEASE unchanged", flush=True)
    if args.joint_offset:
        names = {s["name"] for s in plan["stages"]}
        if set(args.offset_stages) - names:
            raise ValueError(f"--offset-stages: no such stage {sorted(set(args.offset_stages) - names)}")
        apply_stage_offsets(plan, args.joint_offset, tuple(args.offset_stages))
    if args.close_extra:
        g = cfg["gripper"]
        if not 0 < args.close_extra <= 200:
            raise ValueError("--close-extra must be 1..200 pulses")
        step = -1 if g["open_pulse"] > g["close_pulse"] else 1  # direction from open towards closed
        target = g["close_pulse"] + step * args.close_extra
        for stage in plan["stages"]:
            if stage["name"] == "CLOSE":
                stage["target"] = target
        print(f"CLOSE gripper pulse {g['close_pulse']} -> {target} (current limit {g['current_limit_raw']})", flush=True)
    replaced = apply_saved_poses(plan)
    if replaced:
        print("saved poses used for:", ", ".join(replaced), f"({POSES_FILE.name})", flush=True)
    print("YOLO UV:", args.uv, "pick model XYZ mm:", plan["pick_model_xyz_mm"], flush=True)
    print("stages:", " -> ".join(s["name"] for s in plan["stages"]), flush=True)
    if not args.live:
        print(json.dumps({"pick_model_xyz_mm": plan["pick_model_xyz_mm"],
                          "stages": [s["name"] for s in plan["stages"]],
                          "kinds": [s["kind"] for s in plan["stages"]]}))
        print("[DRY_RUN] motor port not opened")
        return 0

    from pick_robot import DynamixelBus, MotionController
    with Journal(args.output) as journal, DynamixelBus(profile.port) as bus:
        driver = MotionController(bus, cfg, journal.emit)
        driver.prepare(saved["hover_high"], use_gripper=not args.hover)
        journal.emit("plan", {"plan": plan, "config": cfg, "source": "yolo"})
        if ask("경로 확인 후 MOVE 입력 (그 외: 취소): ").strip() != "MOVE":
            print("[CANCELLED] no goal or torque written")
            return 3
        try:
            driver.enable()
        except BaseException:
            driver.hold()
            raise
        def emit(event, stage):
            journal.emit(event, stage)
            if event == "stage_start":
                if args.step:
                    wait_space(stage["name"])
                print(f"STAGE {stage['name']}", flush=True)  # read by eval_bi_api_yolo.py

        ocp.execute_click(plan, driver, emit, ask=ask)
        journal.emit("completed", {"physical_success": "OPERATOR_VERIFY", "source": "yolo"})
    print("[DONE] RETURN_HIGH -> DROP_RETREAT sent; torque kept on", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("[CANCELLED] interrupted; check torque state", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as exc:
        cancelled = "취소" in str(exc)
        print(f"[{'CANCELLED' if cancelled else 'FAIL'}] {exc}", file=sys.stderr)
        sys.exit(3 if cancelled else 2)
    except (OSError, ValueError, KeyError, EOFError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(2)
