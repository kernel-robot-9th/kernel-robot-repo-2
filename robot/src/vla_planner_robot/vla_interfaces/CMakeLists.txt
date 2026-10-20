cmake_minimum_required(VERSION 3.8)
project(vla_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Block.msg"
  "msg/BlockArray.msg"
  "action/PickPlace.action"
  "action/ExecuteCommand.action"
  "action/CarryTogether.action"
  DEPENDENCIES std_msgs
)

ament_package()
