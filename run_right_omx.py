#!/usr/bin/env python3
"""Run an omxtest tool for the RIGHT arm, with both arms plugged in.

Uses the right arm's copy of omxtest-main (default ~/main_project/omxtest-right, its own
config/single and records/single) and only /dev/omx_follower. Same arguments as the tool.

  python run_right_omx.py tools/measurement/05_omx_xy_calibration.py ...
  python run_right_omx.py tools/picking/omx_click_pick.py setup
  python run_right_omx.py --root ~/main_project/omxtest-right tools/picking/omx_click_pick.py run --uv 1500 700
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
argv = sys.argv[1:]
root = Path.home() / "main_project" / "omxtest-right"
if argv[:1] == ["--root"]:
    root, argv = Path(argv[1]).expanduser(), argv[2:]
if not argv:
    sys.exit(__doc__)
script = Path(argv[0]) if Path(argv[0]).is_absolute() else root / argv[0]
if not script.exists():
    sys.exit(f"not found: {script}")
sys.path[:0] = [str(script.parent), str(root / "tools" / "picking"), str(root / "tools" / "measurement"), str(HERE)]
import omx_arm_config  # noqa: E402  the right copy's
if not str(Path(omx_arm_config.__file__).resolve()).startswith(str(root.resolve())):
    sys.exit(f"omx_arm_config came from {omx_arm_config.__file__}, not {root}")
import right_arm_only  # noqa: E402,F401
print(f"[RIGHT] {script} with {root}, port {right_arm_only.RIGHT}", flush=True)
sys.argv = [str(script), *argv[1:]]
runpy.run_path(str(script), run_name="__main__")
