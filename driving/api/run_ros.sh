#!/bin/bash
# 서비스용 ros2 launch 실행기. 사용: run_ros.sh <ros2 launch 인자...>   |   run_ros.sh --wait-scan [초]  (/scan 이 나올 때까지 기다림)
D="$(dirname "$(readlink -f "$0")")"
source "$D/ros_env.sh"
if [ "$1" = "--wait-scan" ]; then
  end=$(( $(date +%s) + ${2:-90} ))
  until timeout 6 ros2 topic echo /scan --once --no-arr > /dev/null 2>&1; do
    [ "$(date +%s)" -ge "$end" ] && { echo "/scan 안 나옴 (${2:-90}s) — bringup 확인"; exit 1; }
    sleep 2
  done
  echo "/scan 확인"; exit 0
fi
exec ros2 launch "$@"
