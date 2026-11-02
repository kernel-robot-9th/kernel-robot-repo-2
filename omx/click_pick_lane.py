#!/usr/bin/env python3
"""One arm's click pick for eval_bi_api_yolo_botharm.py, with the shared-bin gate.

Same as click_pick_yolo.py (imported, not copied), plus:
  --arm left|right   left = /dev/omx_follower_left with ~/main_project/omxtest-main (as before)
                     right = omxtest-main --arm right (config/arms/right, its registered port) and its
                     carry_high poses --poses (click_pick_yolo.py --arm right);
                     old way: --omx-root <right arm's copy of omxtest-main>
  --gate-fd N        before the first bin stage (CARRY_HIGH) print "BIN_WAIT <stage>" and wait for a
                     line on fd N: "GO" = go on, anything else = stop here (arm stays at RETREAT,
                     torque on, exit 3). After the last bin stage (RETURN_HIGH) print "BIN_FREE".
  --sim              no omxtest, no motors: print the stages with --sim-seconds each (order/lock test)
  --dry              plan only through click_pick_yolo.py (no motors), then the stages as in --sim

Everything after "--" goes to click_pick_yolo.py (e.g. --uv 1004 739 --live --auto --skip LIFT).
Exit code: 0 done, 3 cancelled / bin stop, 2 error (same as click_pick_yolo.py).
"""
import argparse
import functools
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN_STAGES = ("CARRY_HIGH", "DROP_RELEASE", "RELEASE", "RETURN_HIGH", "DROP_RETREAT")
ALL_STAGES = ["HIGH", "OPEN", "APPROACH", "HOVER", "PICK", "CLOSE", "LIFT", "RETREAT",
              "CARRY_HIGH", "DROP_RELEASE", "RELEASE", "RETURN_HIGH", "DROP_RETREAT"]


class BinGate:
    """Waits at the first bin stage until the server says GO; reports when the last bin stage is done."""
    def __init__(self, fd, stage_names):
        self.stream = os.fdopen(fd, "r") if fd is not None else None
        names = [n for n in stage_names if n in BIN_STAGES]
        self.first = names[0] if names else None
        self.last = names[-1] if names else None

    def before(self, name):
        if self.stream is None or name != self.first:
            return
        print(f"BIN_WAIT {name}", flush=True)
        answer = self.stream.readline().strip()
        if answer != "GO":
            raise RuntimeError(f"통 대기 취소 ({answer or 'server gone'}): arm held before {name}, torque on")

    def after(self, name):
        if self.stream is not None and name == self.last:
            print(f"BIN_FREE {name}", flush=True)


def simulate(stages, gate, seconds, fail=None):
    for name in stages:
        gate.before(name)
        if name == fail:
            raise RuntimeError(f"--sim-fail: simulated error at {name}")
        print(f"STAGE {name}", flush=True)
        print(f"[{'GRIPPER' if name in ('OPEN', 'CLOSE', 'RELEASE') else 'ARM'}] {name}  [sim]", flush=True)
        time.sleep(seconds)
        gate.after(name)
    print("[DONE] sim", flush=True)
    return 0


def skip_list(rest):
    """--skip values from the click_pick_yolo.py arguments."""
    if "--skip" not in rest:
        return []
    out = []
    for value in rest[rest.index("--skip") + 1:]:
        if value.startswith("--"):
            break
        out.append(value)
    return out


def load_right_omx(root):
    """Load the right arm's omxtest copy (its own config/single + records/single) before
    click_pick_yolo.py imports omxtest-main, so its modules (and ROOT) are the right arm's."""
    root = Path(root).expanduser()
    if not (root / "tools" / "picking" / "omx_click_pick.py").exists():
        raise OSError(f"right arm omxtest copy not found: {root} (see BOTHARM.md)")
    sys.path.insert(0, str(root / "tools" / "measurement"))
    sys.path.insert(0, str(root / "tools" / "picking"))
    import omx_click_pick  # noqa: F401  cached: click_pick_yolo.py gets this copy
    import right_arm_only  # noqa: F401  /dev/omx_follower only
    if not str(Path(omx_click_pick.__file__).resolve()).startswith(str(root.resolve())):
        raise RuntimeError(f"omx_click_pick loaded from {omx_click_pick.__file__}, not {root}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    own = argv[:argv.index("--")] if "--" in argv else argv
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", choices=("left", "right"), required=True)
    p.add_argument("--gate-fd", type=int, default=None)
    p.add_argument("--sim", action="store_true")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--sim-seconds", type=float, default=0.5)
    p.add_argument("--sim-fail", default=None, metavar="STAGE", help="--sim: fail at this stage (test)")
    p.add_argument("--omx-root", default=None,
                   help="--arm right, old way: the right arm's copy of omxtest-main (default: omxtest-main --arm right)")
    p.add_argument("--poses", type=Path, default=HERE / "click_pick_poses_right.json",
                   help="record_click_pose.py poses for --arm right (carry_high)")
    args = p.parse_args(own)
    skip = skip_list(rest)
    stages = [s for s in ALL_STAGES if s not in skip]
    gate = BinGate(args.gate_fd, stages)
    if args.sim:
        return simulate(stages, gate, args.sim_seconds, args.sim_fail)

    copy = args.arm == "right" and args.omx_root
    if copy:
        load_right_omx(args.omx_root)
    import click_pick_yolo as cpy  # left: omxtest-main + left_arm_only (right copy: already loaded above)
    ocp = cpy.ocp
    if copy:
        import right_arm_only
        right_arm_only.apply()  # again: click_pick_yolo.py just applied left_arm_only
        cpy.apply_saved_poses = functools.partial(cpy.apply_saved_poses, path=args.poses)
    elif args.arm == "right":
        cpy.RIGHT_POSES_FILE = args.poses
        rest = ["--arm", "right", *rest]  # omxtest-main --arm right
    if args.dry:
        rest = [a for a in rest if a not in ("--live", "--auto", "--step")]
        code = cpy.main(rest)  # plan only: prints the plan, opens no port
        if code != 0:
            return code
        return simulate(stages, gate, args.sim_seconds)

    plain_execute = ocp.execute_click

    def execute_click(plan, driver, emit=lambda *a: None, ask=input):
        bins = [s["name"] for s in plan["stages"] if s["name"] in BIN_STAGES]  # the real plan, after --skip
        gate.first, gate.last = (bins[0], bins[-1]) if bins else (None, None)

        def gated(event, stage):
            if event == "stage_start":
                gate.before(stage["name"])  # after the DROP confirmation, before CARRY_HIGH moves
            emit(event, stage)
            if event == "stage_done":
                gate.after(stage["name"])
        return plain_execute(plan, driver, gated, ask=ask)

    ocp.execute_click = execute_click
    return cpy.main(rest)


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
