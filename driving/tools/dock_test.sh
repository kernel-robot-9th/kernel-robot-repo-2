#!/bin/bash
# 정밀 주차 반복 시험 (PC 에서): 로봇을 일부러 옮긴 뒤 precise_dock 으로 돌아오게 하고, 라이다 스캔 맞춤으로 따로 확인
#   ./dock_test.sh "-0.03,0.015,4" "-0.05,-0.02,-5" ...
cd "$(dirname "$0")"; source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=56
lidar_pose() {  # 스캔 맞춤 바퀴 축 위치 (AMCL + scan_fit 보정)
  timeout 60 python3 now_pose.py 2>&1 | grep "AMCL" | sed 's/^/    /'
  F=$(ls -t marker_logs/NOW_*.npz | head -1); timeout 60 python3 scan_fit.py $F 2>/dev/null | sed -n 3p | sed 's/^/    /'
}
for mv in "$@"; do
  echo "=== 시험: 옮김 $mv (앞m,왼m,deg)"
  ssh pinky "source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=56; cd ~/pinky_map_rev3/tools && python3 precise_dock.py --move=$mv" 2>&1 | grep -v "^\[INFO\|^\[WARN" | tail -1 | sed 's/^/  /'
  ssh pinky "source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=56; cd ~/pinky_map_rev3/tools && python3 precise_dock.py" 2>&1 | grep -v "^\[INFO\|^\[WARN" | sed 's/^/  /'
  echo "  라이다 확인:"; lidar_pose
done
