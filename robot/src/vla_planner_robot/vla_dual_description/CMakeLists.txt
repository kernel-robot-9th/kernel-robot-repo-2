cmake_minimum_required(VERSION 3.8)
project(vla_dual_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY urdf config DESTINATION share/${PROJECT_NAME})

ament_package()
