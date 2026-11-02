#!/usr/bin/env python3
"""omx_click_pick.py run --live, but the grasp point comes from YOLO instead of a click.

Same config, calibration, plan and motion code as
  ~/main_project/omxtest-main/tools/picking/omx_click_pick.py run --live
(imported, not copied). Only the click is replaced by --uv (1920x1080 pixel).

  python click_pick_yolo.py --uv 1004 739            # dry run: print the plan, no motors
  python click_pick_yolo.py --uv 1004 739 --live     # move; asks MOVE / PICK / DROP in this terminal
  python click_pick_yolo.py --uv 1004 739 --live --auto   # move without typed confirmations
  python click_pick_yolo.py --uv 1004 739 --live --step   # SPACE before every stage, q = stop
  python click_pick_yolo.py --uv 1004 739 --edge 1000 700 990 780   # + wrist turned to the YOLO edge
  python click_pick_yolo.py --uv 1004 739 --wrist-deg 20 --no-posture   # manual wrist test, no y correction
  python click_pick_yolo.py --arm right --uv 1340 760   # right arm: omxtest-main --arm right
                                                         # (config/arms/right, click_pick_poses_right.json)

Stages: HIGH -> OPEN -> APPROACH -> HOVER -> PICK -> CLOSE -> LIFT -> RETREAT -> CARRY_HIGH
        -> DROP_RELEASE -> RELEASE -> RETURN_HIGH -> DROP_RETREAT. Torque stays on at the end.
Each stage start prints a line "STAGE <name>" (eval_bi_api_yolo.py turns it into /status phase).
Exit code 0 = all stages sent, 3 = cancelled at a confirmation, 2 = error.
"""
import argparse
import json
import sys
import time
from pathlib import Path

OMX = Path.home() / "main_project" / "omxtest-main"
sys.path.insert(0, str(OMX / "tools" / "picking"))

import omx_click_pick as ocp  # noqa: E402  (needs the path above)
from step_key import wait_space  # noqa: E402  (this folder)
import left_arm_only  # noqa: E402,F401  (left follower only, even with both arms plugged in)
from omx_pick import Journal, profile_for, saved_for  # noqa: E402

PROMPT_WORDS = ("MOVE", "PICK", "DROP")
POSES_FILE = Path(__file__).with_name("click_pick_poses.json")  # record_click_pose.py (left)
RIGHT_POSES_FILE = Path(__file__).with_name("click_pick_poses_right.json")  # record_click_pose.py --arm right
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


CALIBRATION = OMX / "config" / "single" / "omx_xy_calibration.json"
SLIDE_RIGHT_LABELS = ("green_gauze",)  # pushed to the image's right; other labels (blue) to the left


def add_slide(plan, label, pulses_abs, joint=11, with_close=True, calibration=CALIBRATION):
    """Turn joint ID11 by +-pulses_abs from the PICK pose. with_close: in the same motion as the
    gripper CLOSE (both ramp together); otherwise as a separate SLIDE stage after CLOSE.

    Direction is chosen in the camera picture: green_gauze -> right (u grows), blue_gauze -> left.
    """
    import numpy as np
    from pick_core import pulses
    stages = plan["stages"]
    names = [s["name"] for s in stages]
    if "CLOSE" not in names or "PICK" not in names:
        raise ValueError("--slide needs PICK and CLOSE stages")
    pick = list(stages[names.index("PICK")]["target"])
    H = np.linalg.inv(np.array(json.loads(Path(calibration).read_text())["matrix_3x3"], float))

    def to_px(xyz):
        q = H @ [xyz[0], xyz[1], 1.0]
        return q[:2] / q[2]

    base_xyz, base_px = pick_xyz(pick), to_px(pick_xyz(pick))
    trial = list(pick)
    trial[joint - 11] += pulses_abs
    du = to_px(pick_xyz(trial))[0] - base_px[0]  # how +pulses moves in the picture (u = right)
    want_right = label in SLIDE_RIGHT_LABELS
    sign = 1 if (du > 0) == want_right else -1
    target = list(pick)
    target[joint - 11] += sign * pulses_abs
    target[4] %= 4096
    end_xyz = pick_xyz(target)
    end_px = to_px(end_xyz)
    if with_close:
        stages[names.index("CLOSE")]["slide"] = {str(joint): int(target[joint - 11])}
    else:
        stages.insert(names.index("CLOSE") + 1, {"name": "SLIDE", "kind": "arm", "target": pulses(target)})
    print(f"SLIDE{' (with CLOSE)' if with_close else ''} ({label}, {'right' if want_right else 'left'}): ID{joint} {sign * pulses_abs:+d} pulses, "
          f"gripper moves {np.round(np.subtract(end_xyz, base_xyz), 1).tolist()} mm, "
          f"picture u {base_px[0]:.0f} -> {end_px[0]:.0f} (1920x1080)", flush=True)
    plan["slide"] = {"label": label, "joint": joint, "pulses": sign * pulses_abs}


PULSES_PER_DEG = 4096 / 360


def edge_table_angle(calibration, edge):
    """Table-frame rotation (deg, robot XY, + = counter-clockwise seen from above) of a grasp edge
    against an upright edge at the same spot. edge = [[u, v], [u, v]] in 1920x1080, from yolo_worker.

    Both ends go through the click-pick calibration (undistort + homography), so the oblique
    top camera does not bend the angle. Result is wrapped to (-90, 90]: the gripper is symmetric.
    """
    import math
    from pick_core import to_xy
    (u1, v1), (u2, v2) = edge
    mu, mv, half = (u1 + u2) / 2, (v1 + v2) / 2, max(math.hypot(u2 - u1, v2 - v1) / 2, 10.0)
    e = [b - a for a, b in zip(to_xy(calibration, [u1, v1]), to_xy(calibration, [u2, v2]))]
    r = [b - a for a, b in zip(to_xy(calibration, [mu, mv - half]), to_xy(calibration, [mu, mv + half]))]
    deg = math.degrees(math.atan2(r[0] * e[1] - r[1] * e[0], r[0] * e[0] + r[1] * e[1]))
    return (deg + 90) % 180 - 90 if deg != 90 else 90.0


def rotate_reference(cfg, label, table_deg):
    """Turn the recorded grasp direction (grasp_reference_pulses, ID15) by table_deg in robot XY.
    The click-pick IK keeps that direction in APPROACH/HOVER/PICK/LIFT/RETREAT, so the wrist turns
    there and HIGH / carry / drop poses stay as recorded. Returns (old_heading, new_heading, pulses)."""
    import math
    from omx_pick import legacy
    from omx_tool_direction import heading
    fk = legacy("02_omx_xyz_offline.py", "obb_wrist_fk")
    rule = cfg["classes"][label]
    ref = list(rule["grasp_reference_pulses"])
    before = math.degrees(heading(fk, ref))
    trial = list(ref)
    trial[4] = (trial[4] + 100) % 4096
    turn = (math.degrees(heading(fk, trial)) - before + 180) % 360 - 180  # what +100 pulses does
    sign = 1 if turn > 0 else -1
    delta = sign * round(table_deg * PULSES_PER_DEG)
    ref[4] = (ref[4] + delta) % 4096
    after = math.degrees(heading(fk, ref))
    rule["grasp_reference_pulses"] = ref
    return before, after, delta


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
    p.add_argument("--arm", choices=("left", "right"), default="left",
                   help="left = omxtest-main single (as before); right = omxtest-main --arm right "
                        "(config/arms/right, its own port, click_pick_poses_right.json)")
    p.add_argument("--uv", type=float, nargs=2, required=True, help="grasp point, calibration-size pixels")
    p.add_argument("--live", action="store_true", help="move the arm (default: plan only)")
    p.add_argument("--auto", action="store_true", help="skip typed MOVE / PICK / DROP confirmations")
    p.add_argument("--skip", nargs="*", default=[], metavar="STAGE",
                   help="leave these stages out of the plan, e.g. --skip DROP_RETREAT")
    p.add_argument("--joint-offset", nargs="*", default=[], metavar="ID:PULSES",
                   help="add pulses to motor IDs in the --offset-stages stages, e.g. --joint-offset 12:-30 14:20")
    p.add_argument("--offset-stages", nargs="+", default=["APPROACH"], metavar="STAGE",
                   help="stages that get --joint-offset (default: APPROACH)")
    p.add_argument("--slide", type=int, default=0, metavar="PULSES",
                   help="after CLOSE turn ID11 by this many pulses (green -> picture right, blue -> left)")
    p.add_argument("--label", default="green_gauze", help="detected label, sets the --slide direction")
    p.add_argument("--close-extra", type=int, default=0,
                   help="CLOSE target this many pulses past click pick's close_pulse (more squeeze on thin bags)")
    p.add_argument("--open-scale", type=float, default=1.0,
                   help="OPEN stage opening as a fraction of close->open (e.g. 0.667 = 2/3 as wide)")
    p.add_argument("--edge", type=float, nargs=4, metavar=("U1", "V1", "U2", "V2"),
                   help="grasp edge from YOLO (1920x1080, yolo_worker grasp_edge): turn the wrist (ID15) "
                        "to the gauze's table angle in APPROACH..RETREAT")
    p.add_argument("--wrist-deg", type=float, default=0.0,
                   help="extra table-frame wrist turn in deg (+ = counter-clockwise from above); "
                        "alone = manual test without --edge")
    p.add_argument("--max-wrist-deg", type=float, default=45.0,
                   help="refuse a wrist turn larger than this (deg)")
    p.add_argument("--no-posture", action="store_true",
                   help="ignore joint_offset_pulses in omx_click_pick.json (test without the posture/y correction)")
    p.add_argument("--stage-seconds", type=float, default=None,
                   help="seconds per arm stage (default: the config's stage_seconds, 4.0); smaller = faster")
    p.add_argument("--slow-seconds", type=float, default=None,
                   help="seconds for the --slow-stages (default: same as --stage-seconds)")
    p.add_argument("--slow-stages", nargs="+", default=["APPROACH", "HOVER", "PICK"], metavar="STAGE",
                   help="stages that use --slow-seconds (default: APPROACH HOVER PICK)")
    p.add_argument("--gripper-seconds", type=float, default=None,
                   help="seconds to open / close the gripper (default: the config's gripper_seconds)")
    p.add_argument("--step", action="store_true", help="wait for SPACE before every stage (q = stop)")
    p.add_argument("--hover", action="store_true", help="hover 20 mm above, no grip, back to HIGH")
    p.add_argument("--config", type=Path, default=None,
                   help="click-pick config (default: the arm's omx_click_pick.json)")
    p.add_argument("--output", type=Path, help="JSONL log of the live run (must not exist)")
    args = p.parse_args(argv)
    ask = step_answer if args.step else auto_answer if args.auto else typed_answer

    profile = profile_for("right" if args.arm == "right" else None)
    if args.arm == "right":
        print(f"[RIGHT] port {profile.port}, calibration {profile.calibration}", flush=True)
    cfg, calibration = ocp.load_job(args.config or ocp.config_for(profile), profile)
    saved = saved_for(profile, args.hover)
    rule = cfg["classes"][ocp.LABEL]
    # speed: only this run's copy of the config changes, the json file stays as it is
    for name, value in (("--stage-seconds", args.stage_seconds), ("--slow-seconds", args.slow_seconds),
                        ("--gripper-seconds", args.gripper_seconds)):
        if value is not None and not 0.5 <= value <= 10:
            raise ValueError(f"{name} must be 0.5..10 seconds")
    fast = cfg["stage_seconds"] if args.stage_seconds is None else args.stage_seconds
    slow = fast if args.slow_seconds is None else args.slow_seconds
    if args.gripper_seconds is not None:
        cfg["gripper_seconds"] = args.gripper_seconds
    if args.stage_seconds is not None or args.slow_seconds is not None or args.gripper_seconds is not None:
        print(f"SPEED stage {fast:g} s, {'/'.join(args.slow_stages)} {slow:g} s, gripper "
              f"{cfg.get('gripper_seconds', cfg['stage_seconds']):g} s (config stage_seconds {cfg['stage_seconds']:g})",
              flush=True)
    cfg["stage_seconds"] = fast
    if args.no_posture:
        print(f"posture correction off: joint_offset_pulses {rule.get('joint_offset_pulses')} -> [0, 0, 0, 0, 0]",
              flush=True)
        rule["joint_offset_pulses"] = [0] * 5
    wrist = None
    if args.edge or args.wrist_deg:
        table = edge_table_angle(calibration, [args.edge[:2], args.edge[2:]]) if args.edge else 0.0
        total = table + args.wrist_deg
        if abs(total) > args.max_wrist_deg:
            raise ValueError(f"wrist turn {total:+.1f} deg is over --max-wrist-deg {args.max_wrist_deg:g}")
        before, after, delta = rotate_reference(cfg, ocp.LABEL, total)
        wrist = {"edge": args.edge, "table_deg": round(table, 1), "extra_deg": args.wrist_deg,
                 "turn_deg": round(total, 1), "id15_delta_pulses": delta,
                 "heading_deg": [round(before, 1), round(after, 1)]}
        print(f"WRIST gauze table angle {table:+.1f} deg{f' + extra {args.wrist_deg:+.1f}' if args.wrist_deg else ''}"
              f" -> ID15 {delta:+d} pulses, grasp heading {before:.1f} -> {after:.1f} deg", flush=True)
    plan = ocp.plan_for_click(cfg, calibration, saved, args.uv, hover=args.hover)
    plan["obb_wrist"] = wrist
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
    if args.slide:
        if not 0 < args.slide <= 227:
            raise ValueError("--slide must be 1..227 pulses (20 deg)")
        add_slide(plan, args.label, args.slide, calibration=profile.calibration)
    # left: no path argument, so click_pick_lane.py can still swap the file
    replaced = apply_saved_poses(plan, path=RIGHT_POSES_FILE) if args.arm == "right" else apply_saved_poses(plan)
    if replaced:
        print("saved poses used for:", ", ".join(replaced),
              f"({(RIGHT_POSES_FILE if args.arm == 'right' else POSES_FILE).name})", flush=True)
    print("YOLO UV:", args.uv, "pick model XYZ mm:", plan["pick_model_xyz_mm"], flush=True)
    print("stages:", " -> ".join(s["name"] for s in plan["stages"]), flush=True)
    if not args.live:
        print("WRIST path ID15: " + " -> ".join(f"{r['stage']}:{r['id15_unwrapped_pulse']}" for r in plan["wrist_path"]),
              flush=True)
        print(json.dumps({"pick_model_xyz_mm": plan["pick_model_xyz_mm"],
                          "stages": [s["name"] + ("+SLIDE" if s.get("slide") else "") for s in plan["stages"]],
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
                driver.cfg["stage_seconds"] = slow if stage["name"] in args.slow_stages else fast
                if args.step:
                    wait_space(stage["name"])
                print(f"STAGE {stage['name']}", flush=True)  # read by eval_bi_api_yolo.py

        close_slide = next((s.get("slide") for s in plan["stages"] if s["name"] == "CLOSE"), None)
        if close_slide:
            plain_gripper = driver.gripper

            def gripper(name, target):
                if name != "CLOSE":
                    return plain_gripper(name, target)
                # Close the gripper and turn ID11 in one ramp, so the bag is pushed while it is gripped.
                moves = {16: target, **{int(k): v for k, v in close_slide.items()}}
                print(f"[GRIPPER] CLOSE + [ARM] SLIDE {close_slide}", flush=True)
                driver.ramp(moves, max(driver.cfg.get("gripper_seconds", driver.cfg["stage_seconds"]), 1.0))
                time.sleep(driver.cfg["gripper"]["settle_s"])

            driver.gripper = gripper
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
