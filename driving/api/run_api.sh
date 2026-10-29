#!/bin/bash
# 로봇에서 Pinky REST API 띄우기 (기본 0.0.0.0:8080). 인자는 pinky_api.py 로 (--port 등)
# 보통은 부팅 때 사용자 서비스 pinky-api 가 띄움 (install_service.sh). 주행하려면 pinky-bringup·pinky-nav2 + 시작 위치(/set_pose)
D="$(dirname "$(readlink -f "$0")")"
source "$D/ros_env.sh"
cd "$D" && exec python3 pinky_api.py "$@"
