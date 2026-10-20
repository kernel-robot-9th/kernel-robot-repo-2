#!/usr/bin/env python3
"""Two-arm VLA pipeline in simulation (left/right OMX-F on a board, floor workspace)."""
import os
import sys
import subprocess

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction,
                            TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# files written by vla_calibration; each one only overrides the params it measured
CALIB_FILES = {
    'vla_perception': ['colors.yaml', 'table.yaml'],
    'vla_executor': ['colors.yaml', 'wrist.yaml'],
}


def cfg(pkg, name):
    return os.path.join(get_package_share_directory(pkg), 'config', name)


def calib(node, calib_dir):
    if not calib_dir:
        return []
    d = os.path.expanduser(calib_dir)
    return [os.path.join(d, f) for f in CALIB_FILES[node] if os.path.exists(os.path.join(d, f))]


def nodes(context):
    calib_dir = LaunchConfiguration('calib_dir').perform(context)
    perception = Node(package='vla_perception', executable='perception_node', output='screen',
                      parameters=[cfg('vla_perception', 'perception_dual.yaml')]
                      + calib('vla_perception', calib_dir))
    executor = Node(package='vla_executor', executable='executor_node', output='screen',
                    parameters=[cfg('vla_executor', 'executor_dual.yaml')]
                    + calib('vla_executor', calib_dir))
    planner = Node(package='vla_planner', executable='planner_node', output='screen',
                   parameters=[cfg('vla_planner', 'planner_dual.yaml'),
                               {'model': LaunchConfiguration('model'),
                                'dry_run': LaunchConfiguration('dry_run')}])
    debug_view = Node(package='rqt_image_view', executable='rqt_image_view',
                      arguments=['/vla/debug_image'],
                      condition=IfCondition(LaunchConfiguration('image_view')))
    return [perception, executor, planner, debug_view]


def leftover_processes():
    """Processes of an earlier run (a second Gazebo/move_group/executor on the same
    ROS_DOMAIN_ID breaks the new run: duplicate nodes, RViz crash, stray arm goals)."""
    pat = (r'gz sim .*vla_(table|floor)\.sdf|moveit_ros_move_group/move_group|'
           r'lib/vla_executor/executor_node|lib/vla_perception/perception_node')
    out = subprocess.run(['pgrep', '-af', pat], capture_output=True, text=True).stdout
    me = str(os.getpid())
    return [line[:110] for line in out.splitlines() if line.strip() and line.split()[0] != me]


def generate_launch_description():
    left = leftover_processes()
    if left and os.environ.get('VLA_ALLOW_RUNNING') != '1':
        raise RuntimeError(
            'a previous VLA simulation is still running:\n  ' + '\n  '.join(left) +
            '\nstop it first:  ros2 run vla_bringup stop_vla.sh'
            '\n(or set VLA_ALLOW_RUNNING=1 to start anyway)')
    # a conda base / venv python in front of /usr/bin breaks the Python ROS tools
    # (rqt_image_view, ros2 run ... cli): rclpy is built for the system python only
    env = os.environ.get('CONDA_PREFIX') or os.environ.get('VIRTUAL_ENV')
    if env:
        print(f'[vla] WARNING: python environment active ({env}). ROS Python tools may fail '
              '(No module named rclpy._rclpy_pybind11). Run "conda deactivate" / "deactivate" first.',
              file=sys.stderr)

    sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('vla_sim'), 'launch', 'dual_sim.launch.py')),
        launch_arguments=[('headless', LaunchConfiguration('headless')),
                          ('rviz', LaunchConfiguration('rviz')),
                          ('base_separation', LaunchConfiguration('base_separation'))])

    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='false', description='Gazebo without GUI'),
        DeclareLaunchArgument('rviz', default_value='true', description='MoveIt RViz'),
        DeclareLaunchArgument('image_view', default_value='false',
                              description='extra rqt window for /vla/debug_image (RViz already shows it)'),
        DeclareLaunchArgument('model', default_value='gemma4:e2b', description='Ollama model'),
        DeclareLaunchArgument('dry_run', default_value='false', description='plan only, no motion'),
        DeclareLaunchArgument('base_separation', default_value='0.33',
                              description='distance between the two arm bases (link0) [m]'),
        DeclareLaunchArgument('calib_dir', default_value='',
                              description='load vla_calibration results from this directory '
                                          '(e.g. ~/dev_ws/robot/calib); empty = config defaults'),
        sim,
        # start our nodes once the robot is spawned and controllers are coming up
        TimerAction(period=8.0, actions=[OpaqueFunction(function=nodes)]),
    ])
