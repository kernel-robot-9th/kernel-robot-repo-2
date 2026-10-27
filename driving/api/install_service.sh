#!/bin/bash
# 로봇에서 한 번: bringup + Nav2(FollowPath) + REST API 를 부팅 때 자동 실행 (사용자 systemd 서비스, sudo 필요 없음)
#   pinky-bringup → (/scan 나오면) pinky-nav2,  pinky-api (따로, 8080)
set -e
D="$(dirname "$(readlink -f "$0")")"
mkdir -p ~/.config/systemd/user
for s in pinky-bringup pinky-nav2 pinky-api; do ln -sf "$D/$s.service" ~/.config/systemd/user/$s.service; done
loginctl enable-linger "$USER"          # 로그인 안 해도 부팅 때 사용자 서비스가 뜨게
# 손으로 띄운 것이 있으면 끔 (bringup 이 두 개면 모터·라이다를 서로 잡음, API 는 8080 겹침)
# setsid nohup 으로 띄운 launch 는 SIGINT 를 무시하고, launch 만 죽이면 자식 노드가 남음 → 그 세션 전체에 SIGTERM
for p in "[p]inky_api.py" "[r]os2 launch .*nav2_followpath" "[r]os2 launch pinky_bringup"; do
  for pid in $(pgrep -f "$p" || true); do
    sid=$(ps -o sid= -p "$pid" | tr -d ' ')
    if [ "$sid" = "$pid" ]; then pkill -TERM -s "$sid" || true; else kill -TERM "$pid" || true; fi
  done
done
sleep 6
for p in "[p]inky_api.py" "[r]os2 launch" "[p]inky_bringup" "[a]mcl" "[c]ontroller_server" "[m]ap_server" "[v]elocity_smoother" "[s]llidar" "[r]obot_state_publisher" "[b]attery_publisher" "[l]ifecycle_manager"; do
  if pgrep -f "$p" > /dev/null; then echo "아직 남음: $p → SIGKILL"; pkill -9 -f "$p" || true; fi
done
systemctl --user daemon-reload
systemctl --user enable pinky-bringup pinky-nav2 pinky-api
systemctl --user restart pinky-bringup pinky-api
systemctl --user start pinky-nav2      # /scan 기다렸다가 뜸 (최대 2분)
systemctl --user --no-pager status pinky-bringup pinky-nav2 pinky-api | grep -E "●|Active:"
