#!/usr/bin/env python3
"""Two OMX-F arms (left/right) on a board, working on the floor + camera bridges (+ dual MoveIt).

World frame = table frame on the floor. See vla_dual_description/urdf/omx_dual.urdf.xacro.
"""
import os
import sys
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction,
                            RegisterEventHandler, SetEnvironmentVariable)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
import xacro

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_common import wrist_camera_urdf  # noqa: E402

ARMS = ('left', 'right')


def arm_pose_mappings(path):
    """xacro mappings from a vla_calibration arm_poses.yaml ({left: {x, y, yaw}, right: ...})."""
    if not path or not os.path.exists(os.path.expanduser(path)):
        return {}
    import yaml
    with open(os.path.expanduser(path)) as f:
        poses = yaml.safe_load(f) or {}
    return {f'{arm}_{k}': str(v) for arm, p in poses.items() for k, v in p.items()}


def robot_nodes(context):
    sep = LaunchConfiguration('base_separation').perform(context)
    desc = xacro.process_file(
        os.path.join(get_package_share_directory('vla_dual_description'), 'urdf', 'omx_dual.urdf.xacro'),
        mappings={'use_sim': 'true', 'base_separation': sep,
                  **arm_pose_mappings(LaunchConfiguration('arm_poses').perform(context))}
    ).toprettyxml(indent='  ')
    for side in ARMS:
        desc = desc.replace('</robot>', wrist_camera_urdf(f'{side}_', f'{side}/wrist_camera') + '</robot>')

    rsp = Node(package='robot_state_publisher', executable='robot_state_publisher', output='screen',
               parameters=[{'robot_description': desc, 'use_sim_time': True}])
    spawn = Node(package='ros_gz_sim', executable='create', output='screen',
                 arguments=['-string', desc, '-name', 'omx_dual', '-x', '0', '-y', '0', '-z', '0',
                            '-allow_renaming', 'true'])
    jsb = Node(package='controller_manager', executable='spawner',
               arguments=['joint_state_broadcaster'], output='screen')
    controllers = Node(package='controller_manager', executable='spawner', output='screen',
                       arguments=[f'{s}_{k}_controller' for s in ARMS for k in ('arm', 'gripper')])
    return [
        rsp, spawn,
        RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=[jsb])),
        RegisterEventHandler(OnProcessExit(target_action=jsb, on_exit=[controllers])),
    ]


def generate_launch_description():
    sim_share = get_package_share_directory('vla_sim')
    desc_share = get_package_share_directory('open_manipulator_description')
    world = os.path.join(sim_share, 'worlds', 'vla_floor.sdf')
    headless = LaunchConfiguration('headless')

    resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=os.path.join(sim_share, 'models') + ':' + str(Path(desc_share).parent.resolve()))

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py')),
        launch_arguments=[('gz_args', [
            PythonExpression(["'-s ' if '", headless, "' == 'true' else ''"]),
            world, ' -v 1 -r'])])

    bridge = Node(
        package='ros_gz_bridge', executable='parameter_bridge', output='screen',
        arguments=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
                   '/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image',
                   '/camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo']
        + [f'/{s}/wrist_camera/{t}' for s in ARMS for t in (
            'image_raw@sensor_msgs/msg/Image[gz.msgs.Image',
            'camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo')],
        parameters=[{'use_sim_time': True}])

    moveit = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('vla_dual_moveit_config'), 'launch', 'dual_moveit.launch.py')),
        launch_arguments=[('use_sim', 'true'), ('start_rviz', LaunchConfiguration('rviz')),
                          ('base_separation', LaunchConfiguration('base_separation')),
                          ('arm_poses', LaunchConfiguration('arm_poses'))],
        condition=IfCondition(LaunchConfiguration('moveit')))

    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument('moveit', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('base_separation', default_value='0.33',
                              description='distance between the two link0 origins [m]'),
        DeclareLaunchArgument('arm_poses', default_value='',
                              description='arm base poses file; in sim leave empty (the sim is the truth)'),
        resource_path,
        gazebo,
        bridge,
        OpaqueFunction(function=robot_nodes),
        moveit,
    ])
