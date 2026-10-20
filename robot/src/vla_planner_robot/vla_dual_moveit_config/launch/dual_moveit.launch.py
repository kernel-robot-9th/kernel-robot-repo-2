#!/usr/bin/env python3
"""move_group (+ RViz) for the two-arm OMX-F setup (groups left_arm, right_arm, both_arms).

Based on open_manipulator_moveit_config/launch/omx_f_moveit.launch.py.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def arm_pose_mappings(path):
    """xacro mappings from a vla_calibration arm_poses.yaml ({left: {x, y, yaw}, right: ...})."""
    if not path or not os.path.exists(os.path.expanduser(path)):
        return {}
    import yaml
    with open(os.path.expanduser(path)) as f:
        poses = yaml.safe_load(f) or {}
    return {f'{arm}_{k}': str(v) for arm, p in poses.items() for k, v in p.items()}


def moveit_config(base_separation='0.33', use_sim='true', arm_poses=''):
    xacro_file = os.path.join(get_package_share_directory('vla_dual_description'),
                              'urdf', 'omx_dual.urdf.xacro')
    return (
        MoveItConfigsBuilder(robot_name='omx_dual', package_name='vla_dual_moveit_config')
        .robot_description(file_path=xacro_file,
                           mappings={'use_sim': use_sim, 'base_separation': base_separation,
                                     **arm_pose_mappings(arm_poses)})
        .robot_description_semantic('config/omx_dual.srdf')
        .joint_limits('config/joint_limits.yaml')
        .trajectory_execution('config/moveit_controllers.yaml')
        .robot_description_kinematics('config/kinematics.yaml')
        .to_moveit_configs()
    )


def nodes(context):
    use_sim = LaunchConfiguration('use_sim').perform(context)
    cfg = moveit_config(LaunchConfiguration('base_separation').perform(context), use_sim,
                        LaunchConfiguration('arm_poses').perform(context))
    sim_time = {'use_sim_time': use_sim == 'true'}
    move_group = Node(
        package='moveit_ros_move_group', executable='move_group', output='screen',
        parameters=[cfg.to_dict(), sim_time, {'publish_robot_description_semantic': True}])
    rviz = Node(
        package='rviz2', executable='rviz2', name='rviz2_moveit', output='log',
        condition=IfCondition(LaunchConfiguration('start_rviz')),
        arguments=['-d', os.path.join(get_package_share_directory('vla_dual_moveit_config'),
                                      'config', 'moveit.rviz')],
        parameters=[cfg.robot_description, cfg.robot_description_semantic,
                    cfg.robot_description_kinematics, cfg.planning_pipelines, cfg.joint_limits,
                    sim_time])
    return [move_group, rviz]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('start_rviz', default_value='true'),
        DeclareLaunchArgument('use_sim', default_value='true'),
        DeclareLaunchArgument('base_separation', default_value='0.33',
                              description='distance between the two link0 origins [m]'),
        DeclareLaunchArgument('arm_poses', default_value='',
                              description='vla_calibration arm_poses.yaml (measured base poses)'),
        OpaqueFunction(function=nodes),
    ])
