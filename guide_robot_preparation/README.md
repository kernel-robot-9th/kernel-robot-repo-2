# guide_robot 준비 작업 (Pinky)

메인 **guide_robot** (Pinky 안내원 로봇) 프로젝트 전에 한 준비 작업입니다: 노트북 ↔ Pinky ROS 2 연결, 센서 확인, 카메라 캘리브레이션, 비주얼 SLAM (RTAB-Map). 여기 있는 스크립트와 결과는 guide_robot에서 그대로 사용합니다.

현재 상태와 결과: [progress.md](progress.md).

## 단계 순서

| # | 문서 | 내용 |
|---|---|---|
| 1 | [checking_connection.md](checking_connection.md) | 노트북 ↔ Pinky ROS 2 연결: `ROS_DOMAIN_ID`, `ROS_STATIC_PEERS`, talker/listener |
| 2 | [checking_sensors.md](checking_sensors.md) | LiDAR, 카메라, IMU, 오도메트리, 배터리, TF 확인 |
| 3 | [calibration.md](calibration.md) | ChArUco 보드로 카메라 캘리브레이션 → `~/pinky_camera.yaml` |
| 4 | [vslam.md](vslam.md) | 비주얼 SLAM: RTAB-Map (카메라 + LiDAR + 바퀴 오도메트리) |

## 파일

| 파일 | 용도 |
|---|---|
| `robot/check_sensors.py` | 모든 센서 (LiDAR, 카메라, IMU, 오도메트리...)와 TF를 자동 확인; `--motion`으로 회전 테스트 |
| `robot/imu_fix.py` | IMU 자이로 단위를 deg/s → rad/s로 변환해 `/imu/data`로 다시 발행 |
| `robot/cam_preview.py` | 노트북에서 카메라를 보기 위한 작은 JPEG 스트림 (Wi-Fi에 가벼움) |
| `robot/calibrate_camera.py` | ChArUco 보드로 카메라 캘리브레이션 → `~/pinky_camera.yaml` |
| `robot/camera_tilt.py` | 보드로 카메라가 아래로 기운 각도 측정 (`cam_pitch`) |
| `robot/vslam_camera.py` | SLAM용 카메라 영상: 180° 회전, 속도 제한, `camera_info` 발행 |
| `robot/launch/vslam.launch.py` | RTAB-Map 실행 (카메라 + LiDAR + 오도메트리) |
| `docs/charuco_board_9x7_25mm_5x5_A4.pdf` | 캘리브레이션 보드 (ChArUco, A4) |
| `docs/calibration_board_9x7_25mm_A4.pdf` | 일반 체스보드 (예비) |

코드의 식별자와 터미널 로그 메시지는 영어이고, 주석과 문서는 한국어입니다 (guide_robot과 같은 방식).

## Pinky 시작하기 (매번)

Pinky에서 터미널 3개, 모두 열어 둡니다:

```bash
ros2 launch pinky_bringup bringup_robot.launch.xml   # 모터, 오도메트리, LiDAR, TF, 배터리
ros2 run pinky_imu_bno055 main_node                  # IMU -> /imu_raw
python3 ~/marker_follow/cam_pub.py                   # 카메라 -> /camera/image_raw (30 Hz)
```

Pinky로 폴더 복사 (노트북에서, zip을 푼 곳에서):

```bash
scp -r guide_robot_preparation/ko pinky@PINKY_IP:~/guide_robot_preparation
```

필요한 패키지: ROS 2 Jazzy, `opencv-contrib-python` (`cv2.aruco`), `ros-jazzy-rtabmap-ros`.
