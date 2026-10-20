#!/usr/bin/env python3
"""OMX-F in the VLA tabletop world + camera bridge (+ MoveIt by default).

Based on open_manipulator_bringup/omx_f_gazebo.launch.py, with our own world,
model path and camera bridge.
"""
import os
import re
import sys
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            RegisterEventHandler, SetEnvironmentVariable)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder
import xacro

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_common import wrist_camera_urdf  # noqa: E402


def generate_launch_description():
    sim_share = get_package_share_directory('vla_sim')
    desc_share = get_package_share_directory('open_manipulator_description')
    moveit_share = get_package_share_directory('open_manipulator_moveit_config')

    headless = LaunchConfiguration('headless')
    use_moveit = LaunchConfiguration('moveit')
    world = os.path.join(sim_share, 'worlds', 'vla_table.sdf')

    resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=os.path.join(sim_share, 'models') + ':' +
        str(Path(desc_share).parent.resolve()))

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py')),
        launch_arguments=[('gz_args', [
            PythonExpression(["'-s ' if '", headless, "' == 'true' else ''"]),
            world, ' -v 1 -r'])],
    )

    robot_desc = xacro.process_file(
        os.path.join(desc_share, 'urdf', 'omx_f', 'omx_f.urdf.xacro'),
        mappings={'use_sim': 'true'}).toprettyxml(indent='  ')
    # use our controller params (adds the gz_ros2_control position gain)
    robot_desc = robot_desc.replace(
        os.path.join(get_package_share_directory('open_manipulator_bringup'),
                     'config', 'omx_f', 'hardware_controller_manager.yaml'),
        os.path.join(sim_share, 'config', 'omx_f_sim_controllers.yaml'))
    # wrist camera on the gripper base, looking down the tool axis between the fingers
    robot_desc = robot_desc.replace('</robot>', wrist_camera_urdf() + '</robot>')
    # drop the red marker cube drawn at end_effector_link: it sits between the fingers in
    # the wrist view and would look like a grasped red block (the real robot has none)
    robot_desc = re.sub(r'(<link name="end_effector_link">).*?(</link>)', r'\1\2',
                        robot_desc, flags=re.S)

    rsp = Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_desc, 'use_sim_time': True}])

    spawn = Node(
        package='ros_gz_sim', executable='create', output='screen',
        arguments=['-string', robot_desc, '-name', 'omx_f',
                   '-x', '0', '-y', '0', '-z', '0', '-allow_renaming', 'true'])

    jsb = Node(package='controller_manager', executable='spawner',
               arguments=['joint_state_broadcaster'], output='screen')
    arm = Node(package='controller_manager', executable='spawner',
               arguments=['arm_controller'], output='screen')
    gripper = Node(package='controller_manager', executable='spawner',
                   arguments=['gripper_controller'], output='screen')

    bridge = Node(
        package='ros_gz_bridge', executable='parameter_bridge', output='screen',
        arguments=[
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
            '/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image',
            '/camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo',
            '/wrist_camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image',
            '/wrist_camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo',
        ],
        parameters=[{'use_sim_time': True}])

    moveit = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(moveit_share, 'launch', 'omx_f_moveit.launch.py')),
        launch_arguments=[('use_sim', 'true'), ('start_rviz', 'false')],
        condition=IfCondition(use_moveit))

    # our RViz instead of the ROBOTIS one: same MoveIt panel plus the camera images
    # (top-camera detections, raw top camera, wrist grasp check)
    mcfg = (MoveItConfigsBuilder(robot_name='omx_f', package_name='open_manipulator_moveit_config')
            .robot_description_semantic(str(Path('config') / 'omx_f' / 'omx_f.srdf'))
            .joint_limits(str(Path('config') / 'omx_f' / 'joint_limits.yaml'))
            .trajectory_execution(str(Path('config') / 'omx_f' / 'moveit_controllers.yaml'))
            .robot_description_kinematics(str(Path('config') / 'omx_f' / 'kinematics.yaml'))
            .to_moveit_configs())
    rviz = Node(
        package='rviz2', executable='rviz2', name='rviz2_moveit', output='log',
        condition=IfCondition(PythonExpression(["'", use_moveit, "' == 'true' and '",
                                                LaunchConfiguration('rviz'), "' == 'true'"])),
        arguments=['-d', os.path.join(sim_share, 'rviz', 'vla_single.rviz')],
        parameters=[{'robot_description': robot_desc}, mcfg.robot_description_semantic,
                    mcfg.robot_description_kinematics, mcfg.planning_pipelines, mcfg.joint_limits,
                    {'use_sim_time': True}])

    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument('moveit', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        resource_path,
        gazebo,
        bridge,
        rsp,
        spawn,
        RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=[jsb])),
        RegisterEventHandler(OnProcessExit(target_action=jsb, on_exit=[arm, gripper])),
        moveit,
        rviz,
    ])
