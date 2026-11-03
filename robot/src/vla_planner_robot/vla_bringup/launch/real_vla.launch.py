#!/usr/bin/env python3
"""Whole VLA pipeline on the REAL right arm: cameras + follower + perception + executor + planner.

Same nodes as sim_vla.launch.py; the real parts are configured, not new code paths:
  - follower: ROBOTIS omx_f_follower_ai (init_position false: holds its pose, never stretches up);
    the executor drives its arm_controller directly (motion_backend direct, no MoveIt)
  - top camera -> camera_node; perception reads calib/top_intrinsics.yaml + top_homography.yaml
  - wrist camera -> camera_node; the executor centres on the block with it before every grasp
Start with the arm folded and teleop stopped (they share the follower port). Then: ros2 run vla_planner cli
"""
import glob
import os
import subprocess
import sys

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def cfg(pkg, name):
    return os.path.join(get_package_share_directory(pkg), 'config', name)


def teleop_arms():
    with open(cfg('vla_teleop', 'arms.yaml')) as handle:
        return yaml.safe_load(handle)


def leftover_processes():
    """An earlier pipeline, a simulation or a teleop session would fight over the follower port or topics."""
    pat = (r'lib/vla_executor/executor_node|lib/vla_perception/perception_node|lib/vla_perception/camera_node|'
           r'omx_f_follower_ai|omx_l_leader_ai|gz sim .*vla_(table|floor)\.sdf')
    out = subprocess.run(['pgrep', '-af', pat], capture_output=True, text=True).stdout
    me = str(os.getpid())
    return [line[:110] for line in out.splitlines() if line.strip() and line.split()[0] != me]


def generate_launch_description():
    left = leftover_processes()
    if left and os.environ.get('VLA_ALLOW_RUNNING') != '1':
        raise RuntimeError('still running (stop teleop / the simulation first):\n  ' + '\n  '.join(left)
                           + '\n  ros2 run vla_teleop teleop stop   |   ros2 run vla_bringup stop_vla.sh')
    env = os.environ.get('CONDA_PREFIX') or os.environ.get('VIRTUAL_ENV')
    if env:
        print(f'[vla] WARNING: python environment active ({env}); run "conda deactivate" / "deactivate" first.',
              file=sys.stderr)
    arms = teleop_arms()
    arm = arms['arms']['right']
    ports = glob.glob(f'/dev/serial/by-id/*OpenRB-150_{arm["follower_serial"]}*')
    if not ports:
        raise RuntimeError(f'right follower OpenRB {arm["follower_serial"]} is not connected')
    calib_dir = os.path.expanduser('~/dev_ws/robot/calib')

    follower = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('open_manipulator_bringup'), 'launch', 'omx_f_follower_ai.launch.py')),
        launch_arguments=[('port_name', ports[0]), ('init_position', 'false'), ('start_rviz', 'false')])
    # UVC cameras forget their fixed settings when unplugged: re-apply calib/camera_settings.yaml (focus)
    camera_lock = ExecuteProcess(cmd=['ros2', 'run', 'vla_teleop', 'teleop', 'camera'], output='screen')
    top_camera = Node(package='vla_perception', executable='camera_node', name='top_camera', output='screen',
                      parameters=[{'device': arms['top_camera'], 'width': 1920, 'height': 1080, 'rate': 5.0,
                                   'topic': '/camera/image_raw', 'frame_id': 'top_camera',
                                   'intrinsics_file': os.path.join(calib_dir, 'top_intrinsics.yaml')}])
    wrist_camera = Node(package='vla_perception', executable='camera_node', name='wrist_camera', output='screen',
                        parameters=[{'device': arm['wrist_camera'], 'width': 640, 'height': 480, 'rate': 10.0,
                                     'topic': '/wrist_camera/image_raw', 'frame_id': 'wrist_camera'}])
    perception = Node(package='vla_perception', executable='perception_node', output='screen',
                      parameters=[cfg('vla_perception', 'perception_real.yaml')])
    executor = Node(package='vla_executor', executable='executor_node', output='screen',
                    parameters=[cfg('vla_executor', 'executor_real.yaml'),
                                {'observe_on_start': LaunchConfiguration('fold_on_start')}])
    planner = Node(package='vla_planner', executable='planner_node', output='screen',
                   parameters=[cfg('vla_planner', 'planner_real.yaml'),
                               {'model': LaunchConfiguration('model'), 'dry_run': LaunchConfiguration('dry_run')}])
    return LaunchDescription([
        DeclareLaunchArgument('model', default_value='gemma4:e2b', description='Ollama model'),
        DeclareLaunchArgument('dry_run', default_value='false', description='plan only, no motion'),
        DeclareLaunchArgument('fold_on_start', default_value='true',
                              description='executor moves the arm to the folded observe pose at start'),
        camera_lock, follower,
        TimerAction(period=3.0, actions=[top_camera, wrist_camera, perception]),
        # the follower needs a few seconds for torque on + arm_controller active
        TimerAction(period=10.0, actions=[executor, planner]),
    ])
