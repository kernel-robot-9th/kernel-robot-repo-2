#!/bin/bash
# Re-run with bash if started as "sh script.sh" (sh cannot load conda).
[ -z "$BASH_VERSION" ] && exec bash "$0" "$@"
# Weekend SmolVLA runs, split across the two OMEN laptops. Runs one after another; a failed run is
# logged and the next one still starts.
#   ./train_group.sh A    # first OMEN  (max):           runs 1, 2, 3
#   ./train_group.sh B    # second OMEN (fastcamp1):     runs 4, 5, 6
#   ./train_group.sh 3    # a single run by number
# Optional env: STEPS=30000 BATCH_SIZE=16 SAVE_FREQ=2000 DRY_RUN=1 (print commands only)
#
#  no | dataset (HF jaewoo112/...)        | augmentation | output folder (outputs/train/...)
#   1 | bi_gauze_one_exposure             | no           | smolvla_bi_gauze_one_exposure
#   2 | bi_gauze_one_exposure_masked      | no           | smolvla_bi_gauze_one_exposure_masked
#   3 | bi_gauze_one_exposure             | yes          | smolvla_bi_gauze_one_exposure_aug
#   4 | bi_gauze_one_exposure_masked      | yes          | smolvla_bi_gauze_one_exposure_masked_aug
#   5 | bi_gauze_mix_masked               | no           | smolvla_bi_gauze_mix_masked
#   6 | bi_gauze_mix_masked               | yes          | smolvla_bi_gauze_mix_masked_aug
cd "$(dirname "$0")"
case "$1" in
  A) RUNS="1 2 3" ;;
  B) RUNS="4 5 6" ;;
  [1-6]) RUNS="$1" ;;
  *) echo "usage: $0 A|B|<1-6>"; exit 1 ;;
esac

dataset() { case $1 in 1|3) echo bi_gauze_one_exposure ;; 2|4) echo bi_gauze_one_exposure_masked ;; 5|6) echo bi_gauze_mix_masked ;; esac; }
augmented() { case $1 in 3|4|6) return 0 ;; *) return 1 ;; esac; }

mkdir -p logs
for n in $RUNS; do
  ds=$(dataset "$n")
  if augmented "$n"; then aug=(AUGMENT=1 OUT_SUFFIX=_aug); else aug=(); fi
  cmd=(env HF_USER=jaewoo112 POLICY=smolvla BATCH_SIZE="${BATCH_SIZE:-16}" SAVE_FREQ="${SAVE_FREQ:-2000}" "${aug[@]}"
       ./train_bi.sh "$ds" "${STEPS:-30000}")
  log=logs/run${n}_${ds}$([ ${#aug[@]} -gt 0 ] && echo _aug).log
  echo "=== run $n: ${cmd[*]}  (log: $log) $(date '+%m-%d %H:%M')"
  [ -n "$DRY_RUN" ] && continue
  "${cmd[@]}" 2>&1 | tee "$log"
  echo "=== run $n finished with status ${PIPESTATUS[0]} $(date '+%m-%d %H:%M')"
done
