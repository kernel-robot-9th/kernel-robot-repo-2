"""Bimanual OMX for LeRobot v0.4.4.

LeRobot imports this package automatically (third-party plugin, name starts with `lerobot_robot_`),
which registers `--robot.type=bi_omx_follower` and `--teleop.type=bi_omx_leader`.
Modeled on lerobot's bi_so_follower / bi_so_leader.
"""

from .bi_omx import BiOmxFollower, BiOmxFollowerConfig, BiOmxLeader, BiOmxLeaderConfig

__all__ = ["BiOmxFollower", "BiOmxFollowerConfig", "BiOmxLeader", "BiOmxLeaderConfig"]
