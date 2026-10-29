#!/usr/bin/env bash
# 핑키 배터리 보기 (PC 에서 실행, 로봇에 SSH 로 들어가 /battery/percent, /battery/voltage 를 읽음. 로봇은 5초마다 냄)
#   tools/battery.sh               # 한 번
#   tools/battery.sh -w            # 10초마다 계속 (Ctrl+C 로 끝)
#   tools/battery.sh -w 30 192.168.129.107   # 30초마다, 다른 로봇 (ROS_DOMAIN_ID 는 로봇 ~/.bashrc 값)
HOST=10.42.0.171   # 지금 쓰는 로봇 pinky_6364 (10-28 iptime team2 망. 10-27 까지 FASTCAMPUS 192.168.129.68)
WATCH=0; EVERY=10
if [ "$1" = "-w" ]; then
  WATCH=1; shift
  if [[ "$1" =~ ^[0-9]+$ ]]; then EVERY=$1; shift; fi
fi
[ -n "$1" ] && HOST=$1

read_once() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 "pinky@$HOST" '
    source /opt/ros/jazzy/setup.bash
    export ROS_DOMAIN_ID=$(grep -oP "^export ROS_DOMAIN_ID=\K[0-9]+" ~/.bashrc | tail -1)
    p=$(timeout 8 ros2 topic echo --once --field data /battery/percent 2>/dev/null | head -1)
    v=$(timeout 8 ros2 topic echo --once --field data /battery/voltage 2>/dev/null | head -1)
    echo "$p $v"' 2>/dev/null
}

while true; do
  read -r P V <<< "$(read_once)"
  NOW=$(date +%H:%M:%S)
  if [ -z "$P" ]; then
    echo "$NOW  $HOST  배터리 못 읽음 (로봇 꺼짐/네트워크/bringup 확인)"
  else
    WARN=""
    (( $(printf '%.0f' "$P") <= 20 )) && WARN="  ⚠️ 20% 이하 — 충전 필요"
    printf '%s  %s  배터리 %5.1f %%  %5.2f V%s\n' "$NOW" "$HOST" "$P" "$V" "$WARN"
  fi
  [ "$WATCH" = 1 ] || break
  sleep "$EVERY"
done
