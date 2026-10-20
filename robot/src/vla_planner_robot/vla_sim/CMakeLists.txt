cmake_minimum_required(VERSION 3.8)
project(vla_sim)

find_package(ament_cmake REQUIRED)

install(DIRECTORY worlds models launch config rviz DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/gen_markers.py scripts/gen_checkerboard.py scripts/checkerboard_sweep.py
  DESTINATION lib/${PROJECT_NAME})

ament_package()
