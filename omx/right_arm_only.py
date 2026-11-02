"""Make omxtest code use only the right follower (/dev/omx_follower) when both arms are connected.

Like left_arm_only.py. omx_arm_config.single_profile() refuses to run with more than one OpenRB;
apply() narrows its port scan to the device behind /dev/omx_follower. Import after the omxtest
paths are on sys.path (it applies itself on import; call apply() again after left_arm_only).
"""
from pathlib import Path

import omx_arm_config

RIGHT = Path("/dev/omx_follower")
_scan = omx_arm_config.connected_serial_ports
if getattr(_scan, "__name__", "") == "left_only":  # left_arm_only was imported first
    import left_arm_only
    _scan = left_arm_only._scan


def right_only():
    ports = _scan()
    if not RIGHT.exists():
        raise RuntimeError(f"{RIGHT} not found: is the right follower plugged in?")
    right = [p for p in ports if Path(p).resolve() == RIGHT.resolve()]
    if not right:
        raise RuntimeError(f"no OpenRB port matches {RIGHT} ({RIGHT.resolve()}); found {ports}")
    return right


def apply():
    omx_arm_config.connected_serial_ports = right_only


apply()
