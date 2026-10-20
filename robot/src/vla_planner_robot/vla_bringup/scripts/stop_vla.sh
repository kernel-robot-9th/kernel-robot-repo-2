#!/bin/bash
# Stop every process of a previous VLA simulation run (Gazebo, MoveIt, RViz, our nodes).
# A half-dead previous run on the same ROS_DOMAIN_ID makes a new launch misbehave
# (duplicate nodes, RViz crash, stray arm goals).
PAT='ros2 launch vla_(bringup|sim) |gz sim .*vla_(table|floor)\.sdf|gz_tools_vendor/bin/gz sim|moveit_ros_move_group/move_group|ros_gz_bridge/parameter_bridge|robot_state_publisher/robot_state_publisher|controller_manager/spawner|lib/vla_(perception|executor|planner|calibration)/|rviz2/rviz2|rqt_image_view'

ancestors() {          # this script and everything that started it must survive
  local p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do echo "$p"; p=$(ps -o ppid= -p "$p" | tr -d ' '); done
}
SELF=" $(ancestors | tr '\n' ' ') "
pids() { for p in $(pgrep -f "$PAT"); do [[ "$SELF" == *" $p "* ]] || echo "$p"; done; }

[ -z "$(pids)" ] && { echo "nothing running"; exit 0; }
for p in $(pids); do kill -INT "$p" 2>/dev/null; done
sleep 5
for p in $(pids); do kill -9 "$p" 2>/dev/null; done
sleep 1
ros2 daemon stop >/dev/null 2>&1
left=$(pids)
if [ -n "$left" ]; then echo "still running:"; ps -o pid,args -p "$(echo $left | tr ' ' ',')"; exit 1; fi
echo "stopped"
