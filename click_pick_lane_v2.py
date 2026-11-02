#!/usr/bin/env python3
"""click_pick_lane.py + safety pause (eval_bi_api_yolo_botharm_v2.py starts this one).

Same arguments and behaviour as click_pick_lane.py. Every arm / gripper ramp of the click pick
checks safety_pause.PAUSE_FILE each 50 ms step: while paused the arm holds its last goal (torque on),
and the ramp goes on from the same point when resumed. --sim stages pause the same way.
"""
import sys

import click_pick_lane as lane
import safety_pause


class _SimTime:
    """--sim / --dry stage timing that also waits while paused."""
    def __getattr__(self, name):
        import time
        return getattr(time, name)

    @staticmethod
    def sleep(seconds):
        import time
        safety_pause.wait_while_paused("sim stage")
        time.sleep(seconds)


def _patch_after_import():
    import pick_robot  # omxtest picking (already on sys.path via click_pick_yolo)
    safety_pause.patch_ramp(pick_robot.MotionController)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    lane.time = _SimTime()
    own = argv[:argv.index("--")] if "--" in argv else argv
    if "--omx-root" in own:  # old right-arm copy: patch after it is loaded
        load = lane.load_right_omx

        def load_and_patch(root):
            load(root)
            _patch_after_import()
        lane.load_right_omx = load_and_patch
    elif "--sim" not in own:
        import click_pick_yolo  # noqa: F401  puts omxtest-main on sys.path (left_arm_only too, as in lane)
        _patch_after_import()
    return lane.main(argv)


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
