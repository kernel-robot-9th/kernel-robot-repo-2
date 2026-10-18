#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Run a trained bimanual ACT checkpoint on the robot (course PDF 09 inference, bi_omx version).
# The policy moves both followers by itself; leader arms are not used.
# Usage: ./eval_bi.sh <dataset_name> [checkpoint_step] ["task text"]   (step like 040000, default: last)
# Example: ./eval_bi.sh bi_lift_box 040000
#          POLICY=smolvla ./eval_bi.sh bi_gauze last "pick and place blue gauze"
# For SmolVLA the task text is the instruction the robot follows; use the exact sentence from recording.
# Optional env: POLICY=act|smolvla EPISODE_TIME=60 EPISODES=1 TOP_EXPOSURE=90 (match the recording)
#   OUT_SUFFIX=_aug -> use the augmented run; TOP_MASK=1 -> black out the top camera outside x0-400 y200-480, for models trained on *_masked datasets
set -e
NAME=${1:?dataset name used for training}
CKPT=${2:-last}
TASK=${3:-eval ${NAME}}
RUN_DIR=~/main_project/outputs/train/${POLICY:-act}_${NAME}${OUT_SUFFIX}  # OUT_SUFFIX=_aug for augmented runs
POLICY_DIR=${RUN_DIR}/checkpoints/${CKPT}/pretrained_model
[ -d "$POLICY_DIR" ] || { echo "No checkpoint at $POLICY_DIR"; ls "${RUN_DIR}/checkpoints"; exit 1; }

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
# Camera keys must match what the policy was trained on. SmolVLA was trained with
# top/wrist_left/wrist_right renamed to camera1/2/3; lerobot-record v0.4.4 does not pass
# --dataset.rename_map to make_policy, so name the cameras camera1..3 directly instead.
if [ "${POLICY:-act}" = smolvla ]; then
  K_TOP=camera1; K_WL=camera2; K_WR=camera3
else
  K_TOP=top; K_WL=wrist_left; K_WR=wrist_right
fi
EXTRA=()
# Same keep-rectangle as masking/mask_dataset_stream.py (x1 y1 x2 y2).
[ -n "$TOP_MASK" ] && EXTRA+=(--robot.mask_rois="{${K_TOP}: [0, 200, 400, 480]}") && echo "[top cam] masked to x0-400 y200-480"
CAMS="{${K_TOP}: {type: opencv, index_or_path: '/dev/cam_top', width: 640, height: 480, fps: 30, fourcc: MJPG}, ${K_WL}: {type: opencv, index_or_path: '/dev/cam_wrist_left', width: 640, height: 480, fps: 30, fourcc: MJPG}, ${K_WR}: {type: opencv, index_or_path: '/dev/cam_wrist', width: 640, height: 480, fps: 30, fourcc: MJPG}}"

# Each run is saved as its own eval dataset so runs never collide (needs the eval_ prefix).
lerobot-record \
  --robot.type=bi_omx_follower \
  --robot.id=omx_bi_follower \
  --robot.left_arm_port=/dev/omx_follower_left \
  --robot.right_arm_port=/dev/omx_follower \
  --robot.cameras="${CAMS}" \
  --display_data=true \
  --policy.path="${POLICY_DIR}" \
  --dataset.repo_id="local/eval_${NAME}_${CKPT}_$(date +%H%M%S)" \
  --dataset.single_task="${TASK}" \
  --dataset.num_episodes="${EPISODES:-1}" \
  --dataset.episode_time_s="${EPISODE_TIME:-60}" \
  --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false \
  "${EXTRA[@]}"
