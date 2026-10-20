#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Train ACT on a bimanual dataset recorded with record_bi.sh (course PDF 09, bi_omx version).
# Usage: ./train_bi.sh <dataset_name> [steps]
# Example: ./train_bi.sh bi_lift_box 100000
# Optional env: BATCH_SIZE=16 SAVE_FREQ=10000 HF_USER=<hf name> (default: local)
#   POLICY=smolvla -> fine-tune lerobot/smolvla_base (language-conditioned, uses each episode's task text)
#   AUGMENT=1 -> LeRobot image augmentation (random brightness/contrast/saturation/hue/sharpness/small shift)
#   OUT_SUFFIX=_aug -> separate output folder, e.g. to train the same dataset with and without augmentation
set -e
NAME=${1:?dataset name}
STEPS=${2:-100000}

source ~/anaconda3/etc/profile.d/conda.sh
conda activate main_project
cd ~/main_project
# Dataset owner: same rule as record_bi.sh (HF login name, or "local" when not logged in).
# Override with HF_USER=local for datasets recorded before logging in (bi_gauze, bi_lift_box).
if [ -z "$HF_USER" ]; then
  HF_USER=$(hf auth whoami 2>/dev/null | head -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F': ' '{print $2}' | xargs)
  [ -d ~/.cache/huggingface/lerobot/${HF_USER}/${NAME} ] || HF_USER=local
fi
echo "dataset: ${HF_USER}/${NAME}"
POLICY=${POLICY:-act}
OUT=outputs/train/${POLICY}_${NAME}${OUT_SUFFIX}
# SmolVLA base expects cameras named camera1..3, so map our camera keys onto them.
RENAME_MAP='{"observation.images.top": "observation.images.camera1", "observation.images.wrist_left": "observation.images.camera2", "observation.images.wrist_right": "observation.images.camera3"}'
EXTRA=()
[ -n "$AUGMENT" ] && EXTRA+=(--dataset.image_transforms.enable=true)
if [ "$POLICY" = smolvla ]; then
  POLICY_ARGS="--policy.path=lerobot/smolvla_base"
  EXTRA+=(--rename_map="${RENAME_MAP}")
else
  POLICY_ARGS="--policy.type=act"
fi

lerobot-train \
  --dataset.repo_id="${HF_USER}/${NAME}" \
  ${POLICY_ARGS} \
  --output_dir="${OUT}" \
  --job_name="${POLICY}_${NAME}${OUT_SUFFIX}" \
  --policy.device=cuda \
  --wandb.enable=false \
  --policy.push_to_hub=false \
  --batch_size="${BATCH_SIZE:-16}" \
  --save_freq="${SAVE_FREQ:-10000}" \
  --steps="${STEPS}" \
  "${EXTRA[@]}" \
  ${RESUME:+--resume=true --config_path=${OUT}/checkpoints/last/pretrained_model/train_config.json}
