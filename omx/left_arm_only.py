"""Make omxtest-main's click-pick code use only the left follower when both arms are connected.

omx_arm_config.single_profile() refuses to run when more than one OpenRB is plugged in.
Import this module after the omxtest-main paths are on sys.path and before profile_for(None):
it narrows the port scan to the device behind /dev/omx_follower_left.
"""
from pathlib import Path

import omx_arm_config

LEFT = Path("/dev/omx_follower_left")
_scan = omx_arm_config.connected_serial_ports


def left_only():
    ports = _scan()
    if not LEFT.exists():
        raise RuntimeError(f"{LEFT} not found: is the left follower plugged in?")
    left = [p for p in ports if Path(p).resolve() == LEFT.resolve()]
    if not left:
        raise RuntimeError(f"no OpenRB port matches {LEFT} ({LEFT.resolve()}); found {ports}")
    return left


omx_arm_config.connected_serial_ports = left_only
