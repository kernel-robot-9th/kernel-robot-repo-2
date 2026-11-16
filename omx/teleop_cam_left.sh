#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Left pair teleop (no cameras/rerun). Device names come from 99-omx.rules.
source ~/anaconda3/etc/profile.d/conda.sh
conda activate main_project
cd ~/il_ws/src/lerobot
lerobot-teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/omx_follower_left \
  --robot.id=omx_follower_arm_left \
  --teleop.type=omx_leader \
  --teleop.port=/dev/omx_leader_left \
  --teleop.id=omx_leader_arm_left \
  --display_data=false
