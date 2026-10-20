#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Record a bimanual dataset: 12 joint values (left_*/right_*) + 3 cameras (course PDF 07, bi_omx version).
# Usage: ./record_bi.sh <dataset_name> "<task description>" [num_episodes]
# Example: ./record_bi.sh bi_omx_test "Pick up the doll and put it in the cup" 5
# Optional env: EPISODE_TIME=40 RESET_TIME=20 RESUME=true TOP_EXPOSURE=90 ./record_bi.sh ...
set -e
NAME=${1:?dataset name}
TASK=${2:?task description}
EPISODES=${3:-5}

source ~/anaconda3/etc/profile.d/conda.sh
conda activate main_project
# Preflight: clear latched motor errors (e.g. voltage error after power-up order) and verify
# every motor answers, so a dead bus is reported here instead of deep inside lerobot.
python ~/main_project/clear_motor_errors.py
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
HF_USER=$(hf auth whoami 2>/dev/null | head -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F': ' '{print $2}' | xargs)
# Not logged in to Hugging Face -> save locally only (~/.cache/huggingface/lerobot/local/<name>).
PUSH=true
if [ -z "$HF_USER" ]; then HF_USER=local; PUSH=false; echo "HF not logged in: saving locally, no upload"; fi

lerobot-record \
  --robot.type=bi_omx_follower \
  --robot.id=omx_bi_follower \
  --robot.left_arm_port=/dev/omx_follower_left \
  --robot.right_arm_port=/dev/omx_follower \
  --robot.cameras="{top: {type: opencv, index_or_path: '/dev/cam_top', width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist_left: {type: opencv, index_or_path: '/dev/cam_wrist_left', width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist_right: {type: opencv, index_or_path: '/dev/cam_wrist', width: 640, height: 480, fps: 30, fourcc: MJPG}}" \
  --teleop.type=bi_omx_leader \
  --teleop.id=omx_bi_leader \
  --teleop.left_arm_port=/dev/omx_leader_left \
  --teleop.right_arm_port=/dev/omx_leader \
  --display_data=true \
  --dataset.repo_id="${HF_USER}/${NAME}" \
  --dataset.single_task="${TASK}" \
  --dataset.num_episodes="${EPISODES}" \
  --dataset.episode_time_s="${EPISODE_TIME:-30}" \
  --dataset.reset_time_s="${RESET_TIME:-15}" \
  --resume="${RESUME:-false}" \
  --dataset.push_to_hub="${PUSH}" \
  --dataset.private=true
