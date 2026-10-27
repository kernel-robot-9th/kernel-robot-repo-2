#!/usr/bin/env bash
# IR 센서 실시간 보기 (PC 에서 실행 → 로봇에 SSH 로 들어가 tools/ir_watch.py 를 띄움). 가변저항 맞출 때.
#   tools/ir_watch.sh                    # 지금 쓰는 로봇 pinky_6364
#   tools/ir_watch.sh 192.168.129.107    # 다른 로봇
# IR 노드(pinky_sensor_adc main_node)가 안 떠 있으면 띄워 둔다 (자동 실행에 없음). r = 최소/최대 초기화, q = 끝
HOST=${1:-192.168.129.68}
exec ssh -t -o ConnectTimeout=5 "pinky@$HOST" '
  source ~/pinky_map_rev3/api/ros_env.sh
  if ! pgrep -f "[p]inky_sensor_adc/lib/pinky_sensor_adc/main_node" >/dev/null; then
    echo "IR 노드 띄우는 중…"
    setsid nohup ros2 run pinky_sensor_adc main_node > /tmp/ir_node.log 2>&1 < /dev/null &
    sleep 3
  fi
  exec python3 ~/pinky_map_rev3/tools/ir_watch.py'
