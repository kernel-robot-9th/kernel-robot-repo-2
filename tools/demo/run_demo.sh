#!/bin/bash
# =============================================================================
# 데모 영상 녹화 (2026-11-02) — 시나리오 ① 여러 병동 신청 → 묶음 배송, 실물 Pinky + 실물 OMX
#   1) 점검(preflight.py, 읽기만) → 2) 두 화면 녹화 시작(병원 지도 | 물품 신청, record_ui.mjs)
#   3) 간호사 화면에서 '+ 요청하기 → 즉시 → 병동·물품 → N개 병동 신청'을 녹화기가 직접 누름 → EMR이 FMS·OMX로 보냄
#   4) 자막·기록(caption.py) — 모두 받음이면 끝 → 5) mp4 두 개(10배속·5배속)와 기록
# ⚠ --dry-run이 아니면 실제 Pinky와 OMX 로봇팔이 움직인다. 이 스크립트는 EMR 화면만 누르고 Pinky·OMX API는 부르지 않는다.
#
# tools/demo/run_demo.sh [--dry-run] [--force] [--wards 12:3:1,20:5:1] [--nurse N002]
#   --dry-run  '신청'을 누르지 않고 폼만 채웠다 닫는다. 40초 녹화 → 녹화·자막·영상 만들기 시험 (로봇 안 움직임)
#   --force    점검에 실패해도 진행
#   --wards    장소id:비품id:개수 (기본 105호 C 약품 1개 · 103호 이불 1개 — 약품 1 + 비품 1이라 OMX 시연 명령 blue 1·green 1과 같다)
# 녹화 중 멈추려면: touch <출력 폴더>/stop
# =============================================================================
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DRY=0; FORCE=0; WARDS=12:3:1,20:5:1; NURSE=N002
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) DRY=1 ;;
    --force) FORCE=1 ;;
    --wards) WARDS=$2; shift ;;
    --nurse) NURSE=$2; shift ;;
    *) echo "모르는 옵션 $1"; exit 64 ;;
  esac
  shift
done
STAMP=$(date +%Y%m%d_%H%M%S)
OUT=$HOME/demo_rec/${STAMP}$([ $DRY = 1 ] && echo _dry)
LOGS=$HERE/../../docs/scenarios/logs/$(date +%Y-%m-%d)_real/demo_$(date +%H%M%S)
mkdir -p "$OUT/frames"

echo "== 점검"
if ! /usr/bin/python3 "$HERE/preflight.py" --wards "$WARDS"; then
  if [ $FORCE = 0 ] && [ $DRY = 0 ]; then echo "점검 실패 — 고친 뒤 다시, 또는 --force"; exit 1; fi
  echo "(점검 실패지만 진행: dry-run 또는 --force)"
fi

export TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d "{\"employee_no\":\"$NURSE\",\"password\":\"nurse1234\"}" | /usr/bin/python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
[ -n "$TOKEN" ] || { echo "간호사 $NURSE 로그인 실패"; exit 1; }

echo "곧 시작합니다 — 병원 지도(왼쪽) · 물품 신청(오른쪽)" > "$OUT/caption.txt"
[ $DRY = 1 ] && export NO_SUBMIT=1
INTERVAL_MS=1000 node "$HERE/record_ui.mjs" "$OUT/frames" "$OUT/caption.txt" "$OUT/stop" "$OUT/commands.jsonl" "$OUT/ui_actions.log" > "$OUT/record.log" 2>&1 &
REC=$!
echo "== 녹화 시작 (pid $REC) — 출력 $OUT"
sleep 8

# 신청 한 건 = 화면에서 한 번 (병동 여러 곳)
/usr/bin/python3 -c "import json,sys; print(json.dumps({'wards': [[int(v) for v in w.split(':')] for w in sys.argv[1].split(',')]}))" "$WARDS" > "$OUT/commands.jsonl"

if [ $DRY = 1 ]; then
  /usr/bin/python3 "$HERE/caption.py" "$OUT/caption.txt" "$OUT/stop" "$OUT" --wards "$WARDS" --timeout-min 0.6 > "$OUT/caption.log" 2>&1
else
  echo "== 진행 중 — 실제 Pinky·OMX가 움직입니다. 멈추려면 touch $OUT/stop"
  /usr/bin/python3 "$HERE/caption.py" "$OUT/caption.txt" "$OUT/stop" "$OUT" --wards "$WARDS" --timeout-min 30 > "$OUT/caption.log" 2>&1
fi
echo "caption exit $?" >> "$OUT/caption.log"
touch "$OUT/stop"; wait $REC

echo "== 영상 만들기"
FRAMES=$(ls "$OUT/frames" | grep -c '^a_')
for SPEED in 10 5; do
  (cd "$OUT/frames" && ffmpeg -y -loglevel error -framerate $SPEED -i a_%05d.jpg -framerate $SPEED -i b_%05d.jpg \
    -filter_complex "[0][1]hstack,scale=1920:-2" -c:v libx264 -pix_fmt yuv420p -crf 23 "$OUT/demo_x${SPEED}.mp4")
done
if [ $DRY = 0 ]; then
  mkdir -p "$LOGS" && cp "$OUT"/{summary.md,timeline.log,state.jsonl,ui_actions.log,caption.log} "$LOGS"/ 2>/dev/null
  echo "기록 $LOGS"
fi
echo "프레임 $FRAMES장 (1초에 1장) → $OUT/demo_x10.mp4 (10배속), $OUT/demo_x5.mp4 (5배속)"
tail -2 "$OUT/caption.log"
