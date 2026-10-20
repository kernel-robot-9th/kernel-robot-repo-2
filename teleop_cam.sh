#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Right pair teleop with cameras + rerun viewer (course PDF 05).
# Device names come from 99-omx.rules (udev, matched by serial number / USB port).
source ~/anaconda3/etc/profile.d/conda.sh
conda activate main_project
cd ~/il_ws/src/lerobot
lerobot-teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/omx_follower \
  --robot.id=omx_follower_arm \
  --robot.cameras="{top: {type: opencv, index_or_path: '/dev/cam_top', width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: '/dev/cam_wrist', width: 640, height: 480, fps: 30, fourcc: MJPG}}" \
  --teleop.type=omx_leader \
  --teleop.port=/dev/omx_leader \
  --teleop.id=omx_leader_arm \
  --display_data=true
