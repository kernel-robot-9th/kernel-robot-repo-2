# [②] FollowPath 전용 Nav2: 위치 추정(map_server + amcl) + 경로 추종(controller_server + velocity_smoother)
# 경로 계획기 / BT / 전역 costmap 없음. 관제가 nav2_msgs/action/FollowPath 로 경로를 통째로 보낸다.
# 사용: ros2 launch ~/pinky_map_rev3/launch/nav2_followpath.launch.py [map:=...] [params_file:=...]
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)


def generate_launch_description():
    ns = LaunchConfiguration('namespace')
    map_yaml = LaunchConfiguration('map')
    params = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')
    log_level = LaunchConfiguration('log_level')
    common = [params, {'use_sim_time': use_sim_time}]
    tf = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
    args = ['--ros-args', '--log-level', log_level]

    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('map', default_value=os.path.join(ROOT, 'maps', 'map_drawn.yaml')),
        DeclareLaunchArgument('params_file', default_value=os.path.join(ROOT, 'config', 'nav2_params_followpath.yaml')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('log_level', default_value='info'),
        GroupAction([
            PushRosNamespace(ns),
            # 위치 추정
            Node(package='nav2_map_server', executable='map_server', name='map_server', output='screen',
                 parameters=common + [{'yaml_filename': map_yaml}], remappings=tf, arguments=args),
            Node(package='nav2_amcl', executable='amcl', name='amcl', output='screen',
                 parameters=common, remappings=tf, arguments=args),
            Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
                 name='lifecycle_manager_localization', output='screen',
                 parameters=[{'use_sim_time': use_sim_time, 'autostart': True,
                              'node_names': ['map_server', 'amcl']}]),
            # 경로 추종: controller -> cmd_vel_nav -> velocity_smoother -> cmd_vel
            Node(package='nav2_controller', executable='controller_server', output='screen',
                 parameters=common, remappings=tf + [('cmd_vel', 'cmd_vel_nav')], arguments=args),
            Node(package='nav2_velocity_smoother', executable='velocity_smoother', name='velocity_smoother',
                 output='screen', parameters=common,
                 remappings=tf + [('cmd_vel', 'cmd_vel_nav'), ('cmd_vel_smoothed', 'cmd_vel')], arguments=args),
            Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
                 name='lifecycle_manager_navigation', output='screen',
                 parameters=[{'use_sim_time': use_sim_time, 'autostart': True,
                              'node_names': ['controller_server', 'velocity_smoother']}]),
        ]),
    ])
