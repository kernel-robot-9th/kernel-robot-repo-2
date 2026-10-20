#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Both arm pairs in one process (bi_omx plugin in ./lerobot_robot_bi_omx) + 3 cameras + rerun viewer.
# Device names come from 99-omx.rules.
source ~/anaconda3/etc/profile.d/conda.sh
conda activate main_project
# Preflight: clear latched motor errors (e.g. voltage error after power-up order) and verify
# every motor answers, so a dead bus is reported here instead of deep inside lerobot.
python ~/main_project/clear_motor_errors.py || exit 1
# Top camera exposure: TOP_EXPOSURE=90 fixes manual exposure (less glare on the gauze bags);
# unset = auto exposure (what bi_gauze was recorded with). Train and run a model with the same setting.
# The camera resets exposure when streaming starts, so the manual value is applied in the background
# right after LeRobot opens it (set_top_exposure.sh).
v4l2-ctl -d /dev/cam_top -c auto_exposure=3
if [ -n "${TOP_EXPOSURE}" ]; then
  ~/main_project/set_top_exposure.sh "${TOP_EXPOSURE}" &
else
  echo "[top cam] auto exposure"
fi
cd ~/il_ws/src/lerobot
lerobot-teleoperate \
  --robot.type=bi_omx_follower \
  --robot.id=omx_bi_follower \
  --robot.left_arm_port=/dev/omx_follower_left \
  --robot.right_arm_port=/dev/omx_follower \
  --robot.cameras="{top: {type: opencv, index_or_path: '/dev/cam_top', width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist_left: {type: opencv, index_or_path: '/dev/cam_wrist_left', width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist_right: {type: opencv, index_or_path: '/dev/cam_wrist', width: 640, height: 480, fps: 30, fourcc: MJPG}}" \
  --teleop.type=bi_omx_leader \
  --teleop.id=omx_bi_leader \
  --teleop.left_arm_port=/dev/omx_leader_left \
  --teleop.right_arm_port=/dev/omx_leader \
  --display_data=true
