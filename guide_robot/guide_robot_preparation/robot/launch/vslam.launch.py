"""Pinky의 비주얼 SLAM: 카메라 (루프 클로저) + LiDAR (스캔 매칭) + 바퀴 오도메트리를 쓰는 RTAB-Map.

Pinky에서 실행, bringup, cam_pub.py, 캘리브레이션 다음에:
  ros2 launch ~/guide_robot_preparation/robot/launch/vslam.launch.py                         # 매핑
  ros2 launch ~/guide_robot_preparation/robot/launch/vslam.launch.py localization:=true      # 나중에, Nav2와 함께
  ros2 launch ~/guide_robot_preparation/robot/launch/vslam.launch.py cam_x:=0.06 cam_z:=0.09  # 측정한 카메라 위치

노트북: ros2 run rtabmap_viz rtabmap_viz  (또는 RViz: /map, /rtabmap/cloud_map)
데이터베이스는 ~/.ros/rtabmap.db; delete_db:=false면 기존 지도에 계속 추가함.

이렇게 조합한 이유: Pinky에는 (모노) 카메라 하나뿐이라 카메라만으로는 깊이나 스케일을 잴 수 없음.
RTAB-Map은 카메라로 본 적 있는 장소를 인식하고 (루프 클로저), LiDAR로 정확한 기하를 얻음.
"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration as C
from launch_ros.actions import Node

HERE = os.path.dirname(os.path.realpath(__file__))
ROBOT = os.path.dirname(HERE)


def generate_launch_description():
    args = [
        DeclareLaunchArgument("localization", default_value="false"),
        DeclareLaunchArgument("delete_db", default_value="true", description="새 지도 시작"),
        DeclareLaunchArgument("cam_hz", default_value="10"),
        # base_footprint 기준 카메라 위치 (m), 이 Pinky에서 2026-10-22 측정; pitch: robot/camera_tilt.py
        DeclareLaunchArgument("cam_x", default_value="0.03"),
        DeclareLaunchArgument("cam_y", default_value="0.0"),
        DeclareLaunchArgument("cam_z", default_value="0.062"),
        DeclareLaunchArgument("cam_pitch", default_value="0.0", description="+ = 아래로 기울어짐, rad"),
        DeclareLaunchArgument("use_imu", default_value="true"),
    ]

    params = {
        "frame_id": "base_footprint",
        "odom_frame_id": "odom",            # bringup의 바퀴 오도메트리 (정확했음: +86°에 +85°)
        "subscribe_rgb": True,
        "subscribe_depth": False,
        "subscribe_scan": True,
        "approx_sync": True,
        "sync_queue_size": 20,
        "wait_imu_to_init": False,
        # LiDAR (ICP)로 정합, 카메라 특징점은 장소 인식에만 사용
        "Reg/Strategy": "1",
        "Reg/Force3DoF": "true",
        "RGBD/NeighborLinkRefining": "true",
        "RGBD/ProximityBySpace": "true",
        "RGBD/LinearUpdate": "0.05",         # 작은 필드: 5 cm / ~3°마다 노드 추가
        "RGBD/AngularUpdate": "0.05",
        "Icp/VoxelSize": "0.02",
        "Icp/MaxCorrespondenceDistance": "0.1",
        "Icp/PointToPlane": "false",
        "Kp/MaxFeatures": "400",
        "Vis/MinInliers": "12",
        "Grid/Sensor": "0",                  # LiDAR로 점유 지도 생성
        "Grid/CellSize": "0.025",
        "Grid/RangeMax": "3.0",
        "Rtabmap/DetectionRate": "2",
    }
    remaps = [
        ("rgb/image", "/vslam/image_raw"),
        ("rgb/camera_info", "/vslam/camera_info"),
        ("scan", "/scan"),
        ("imu", "/imu/data"),
    ]

    camera = ExecuteProcess(
        cmd=["python3", os.path.join(ROBOT, "vslam_camera.py"), "--hz", C("cam_hz")], output="screen")
    imu = ExecuteProcess(
        cmd=["python3", os.path.join(ROBOT, "imu_fix.py")], output="screen", condition=IfCondition(C("use_imu")))
    # base_footprint -> camera_link (x 앞, z 위) -> camera_optical_frame (z 앞, x 오른쪽, y 아래)
    tf_cam = Node(package="tf2_ros", executable="static_transform_publisher", arguments=[
        "--x", C("cam_x"), "--y", C("cam_y"), "--z", C("cam_z"), "--pitch", C("cam_pitch"),
        "--frame-id", "base_footprint", "--child-frame-id", "camera_link"])
    tf_opt = Node(package="tf2_ros", executable="static_transform_publisher", arguments=[
        "--roll", "-1.5708", "--yaw", "-1.5708",
        "--frame-id", "camera_link", "--child-frame-id", "camera_optical_frame"])

    mapping = Node(
        package="rtabmap_slam", executable="rtabmap", namespace="rtabmap", output="screen",
        parameters=[params, {"Mem/IncrementalMemory": "true"}], remappings=remaps,
        arguments=["-d"], condition=IfCondition(C("delete_db")))
    mapping_keep = Node(
        package="rtabmap_slam", executable="rtabmap", namespace="rtabmap", output="screen",
        parameters=[params, {"Mem/IncrementalMemory": "true"}], remappings=remaps,
        condition=UnlessCondition(C("delete_db")))
    # 위치 추정: 같은 지도, 새 노드 없음; map->odom TF와 /rtabmap/localization_pose 발행
    localize = Node(
        package="rtabmap_slam", executable="rtabmap", namespace="rtabmap", output="screen",
        parameters=[params, {"Mem/IncrementalMemory": "false", "Mem/InitWMWithAllNodes": "true"}],
        remappings=remaps)

    return LaunchDescription(args + [
        camera, imu, tf_cam, tf_opt,
        GroupAction([mapping, mapping_keep], condition=UnlessCondition(C("localization"))),
        GroupAction([localize], condition=IfCondition(C("localization"))),
    ])
