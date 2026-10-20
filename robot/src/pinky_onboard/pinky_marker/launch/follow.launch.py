# 간호사 따라가기 (선택 기능): Pinky에서 bringup이 떠 있을 때
#   ros2 launch pinky_marker follow.launch.py                 # 카메라 + 따라가기
#   ros2 launch pinky_marker follow.launch.py camera:=false   # 카메라 노드를 따로 띄운 경우
#   ros2 service call /nurse_follower/enable std_srvs/srv/SetBool "{data: false}"   # 끄기
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config = PathJoinSubstitution([FindPackageShare('pinky_marker'), 'config', 'follower.yaml'])
    registry = PathJoinSubstitution([FindPackageShare('pinky_marker'), 'config', 'nurses.yaml'])
    return LaunchDescription([
        DeclareLaunchArgument('camera', default_value='true', description='카메라 노드도 띄울지'),
        DeclareLaunchArgument('rotate180', default_value='false', description='카메라 영상 180° 회전'),
        Node(package='pinky_marker', executable='camera', name='pinky_camera', output='screen',
             condition=IfCondition(LaunchConfiguration('camera')),
             parameters=[{'rotate180': LaunchConfiguration('rotate180')}]),
        Node(package='pinky_marker', executable='nurse_follower', name='nurse_follower', output='screen',
             parameters=[config, {'registry': registry}]),
    ])
