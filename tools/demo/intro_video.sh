#!/bin/bash
# =============================================================================
# 배송 웹 소개 영상 (2026-11-02) — intro_cursor.mjs로 찍고, 빠르게(SPEED배) + 아래 자막 띠를 붙여 mp4로 만든다
#   자막은 화면을 가리지 않게 영상 아래에 띠(1280×72)를 덧붙여 넣는다. 자막 시각은 녹화기가 남긴 captions.json
#   ⚠️ 녹화기는 '신청'을 누르지 않는다(실제 Pinky). DB·FMS는 바꾸지 않는다
#   실제 배송 중이면 도착 창이 녹화를 가린다 — 실물 시험이 없을 때 찍는다
# bash intro_video.sh <out.mp4> [작업 폴더]     env SPEED(기본 1.55 → 약 1분), NO_RECORD=1(작업 폴더의 frames·captions.json을 다시 씀)
# =============================================================================
set -euo pipefail
OUT=$(realpath -m "$1")
WORK=${2:-$(mktemp -d)}
SPEED=${SPEED:-1.55}
HERE=$(cd "$(dirname "$0")" && pwd)

if [ "${NO_RECORD:-0}" != 1 ]; then
  rm -rf "$WORK/frames"
  node "$HERE/intro_cursor.mjs" "$WORK/frames"
fi

# captions.json → ASS (자막 시각을 SPEED로 나눔. 다음 자막이 나오기 전까지 보인다)
/usr/bin/python3 - "$WORK/frames/captions.json" "$SPEED" > "$WORK/captions.ass" <<'EOF'
import json, sys
data = json.load(open(sys.argv[1])); speed = float(sys.argv[2])
end = data["frames"] / data["fps"] / speed
ts = lambda s: "%d:%02d:%05.2f" % (s // 3600, s % 3600 // 60, s % 60)
print("""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 872

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline, Shadow
Style: Bar, Noto Sans CJK KR, 25, &H00FFFFFF, &H00000000, &H00000000, 1, 2, 20, 20, 23, 1, 0, 0

[Events]
Format: Layer, Start, End, Style, Text""")
caps = data["captions"]
for i, c in enumerate(caps):
    start = max(0.0, c["t"] / speed)
    stop = caps[i + 1]["t"] / speed if i + 1 < len(caps) else end
    print("Dialogue: 0,%s,%s,Bar,%s" % (ts(start), ts(stop), c["text"]))
EOF

N=$(ls "$WORK/frames" | grep -c '\.jpg$')
DUR=$(/usr/bin/python3 -c "print(round($N / 10 / $SPEED, 2))")
FADE_OUT=$(/usr/bin/python3 -c "print(round($DUR - 0.6, 2))")
ffmpeg -v error -y -framerate "$(/usr/bin/python3 -c "print(10 * $SPEED)")" -i "$WORK/frames/f%05d.jpg" \
  -vf "pad=1280:872:0:0:color=0x0f172a,subtitles=$WORK/captions.ass,fade=t=in:st=0:d=0.4,fade=t=out:st=$FADE_OUT:d=0.6,format=yuv420p" \
  -r 30 -c:v libx264 -crf 20 -preset slow -movflags +faststart "$OUT"
echo "만듦 $OUT (${DUR}초, 작업 폴더 $WORK)"
