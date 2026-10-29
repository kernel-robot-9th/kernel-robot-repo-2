# 로봇 ROS 환경 (서비스·실행 스크립트가 source). ROS_DOMAIN_ID 는 ~/.bashrc 의 마지막 export 를 따름 (BLE 프로비저닝이 바꿈), 없으면 56
source /opt/ros/jazzy/setup.bash
[ -f ~/pinky_pro/install/setup.bash ] && source ~/pinky_pro/install/setup.bash
_dom=$(grep -E '^\s*export ROS_DOMAIN_ID=' ~/.bashrc 2>/dev/null | tail -1 | sed 's/.*=//; s/[^0-9]//g')
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-${_dom:-56}}
unset _dom
