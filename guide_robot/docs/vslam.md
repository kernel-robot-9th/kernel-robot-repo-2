# Pinky의 비주얼 SLAM (RTAB-Map)

센서 확인과 카메라 캘리브레이션 ([calibration.md](calibration.md))이 끝난 다음 단계입니다.

## 왜 RTAB-Map이고, 왜 LiDAR와 함께 쓰는가

Pinky에는 **카메라가 하나 (모노)**뿐입니다. 모노 카메라는 혼자서 깊이나 거리 스케일을 잴 수 없어서, 카메라만 쓰는 SLAM (ORB-SLAM3 모노)은 이 환경 (작은 필드, 카펫, 반복되는 장소가 많음)에서 불안정합니다.

선택한 방법: Jazzy용 기성 패키지인 **RTAB-Map** (`ros-jazzy-rtabmap-ros`).

| 센서 | 역할 |
|---|---|
| 카메라 | 장소 "인식" (루프 클로저): 영상으로 로봇이 와 본 곳에 돌아왔음을 알고 지도를 보정 |
| LiDAR | 정확한 기하 (ICP)와 2D 지도 |
| 바퀴 오도메트리 | 스텝 사이의 이동 (여기서는 정확함: 86° 명령에 85°) |
| IMU (`/imu/data`) | 중력 방향, 선택 사항 |

결과: 일반 `/map`과 카메라 특징점이 더해진 데이터베이스 `~/.ros/rtabmap.db`.

ORB-SLAM3 (모노-관성)는 선택하지 않았습니다: Jazzy 패키지가 없고, Pi에서 소스 빌드가 무겁고, 카메라-IMU 캘리브레이션 (Kalibr)이 필요하며, 2D 지도를 주지 않습니다.

## 모두 Pinky에서 실행

Wi-Fi로는 LiDAR가 최대 2초까지 끊겼고, 원본 카메라는 ~27 MB/s입니다. 그래서 RTAB-Map, 카메라, LiDAR는 Pinky에서 실행합니다. 노트북은 보기 전용입니다 (`rtabmap_viz` 또는 RViz).

## 0. 준비 (한 번)

**Pinky에서** (전체 패키지는 2026-10-22 설치: 183 MB뿐, 5.3 GB 여유):
```bash
sudo apt install ros-jazzy-rtabmap-ros
ros2 pkg list | grep rtabmap        # rtabmap_slam, rtabmap_sync, rtabmap_util ... 이 보여야 함
```
`guide_robot` 폴더는 Pinky의 `~/guide_robot`으로 복사해 둡니다.

**노트북에서:** `sudo apt install ros-jazzy-rtabmap-ros` (전체 패키지, 보기용 `rtabmap_viz`).

**카메라 캘리브레이션은 필수입니다.** 비주얼 SLAM은 `camera_info` 없이는 동작하지 않습니다. `python3 robot/calibrate_camera.py` -> `~/pinky_camera.yaml`. 오차는 1 px 미만이어야 합니다.

**카메라 위치 측정** (`base_footprint`, 즉 두 바퀴 사이의 바닥 점 기준):
* `cam_x`: 앞으로 몇 미터 (예: 0.05)
* `cam_z`: 바닥에서의 높이 (예: 0.10)
* `cam_pitch`: 카메라가 아래로 기울어진 경우 (라디안, + = 아래). 자로 재기 어려우므로 카메라 자체로 잽니다: 보드를 Pinky 앞 30–40 cm에 **똑바로 세우고** (박스나 벽에 붙임) `python3 robot/camera_tilt.py`를 실행합니다 (`cam_pub.py` 실행 중). `cam_pitch:=...` 값을 출력합니다.

이 Pinky의 측정값 (2026-10-22), launch 기본값으로 설정됨: `cam_x:=0.03 cam_z:=0.062 cam_pitch:=0.072` (아래로 4.1°, 옆으로 -1.2°).

## 1. 실행 (Pinky, 터미널 각각)

```bash
ros2 launch pinky_bringup bringup_robot.launch.xml           # 1: LiDAR, 오도메트리, TF
ros2 run pinky_imu_bno055 main_node                          # 2: IMU
python3 ~/guide_robot/robot/cam_pub.py                           # 3: 카메라
ros2 launch ~/guide_robot/robot/launch/vslam.launch.py       # 4: SLAM (카메라 위치는 기본값)
```

4번 launch는 자동으로 `vslam_camera.py` (영상 180° 회전, 속도 제한, `camera_info` 추가), `imu_fix.py`, 카메라 TF, RTAB-Map을 시작합니다. 실행할 때마다 새 지도를 시작합니다 (`delete_db:=false`면 이전 지도를 이어감).

확인 (Pinky에서):
```bash
ros2 topic hz /vslam/image_raw     # ~7 Hz
ros2 topic hz /rtabmap/map         # 가끔씩 업데이트
```

## 2. 지도 그리기 (수동)

노트북에서: `ros2 run rtabmap_viz rtabmap_viz` (또는 RViz: Fixed frame `map`, `/rtabmap/map` 추가).

Pinky를 천천히 조종합니다 (노트북에서 teleop):
```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```
* 카메라 영상이 흐려지지 않도록 속도를 낮게 유지하세요 (`z`로 줄임).
* 필드를 한 바퀴 돈 뒤 **출발점으로 돌아오세요**: 거기서 루프 클로저가 일어나 지도가 "닫힙니다".
* 카메라에는 볼 벽/물체가 필요합니다: 아무것도 없는 흰 벽은 장소 인식에 도움이 안 됩니다. 필드 가장자리에 사진이나 표지판 몇 개가 도움이 됩니다.

(안내원 모드에는 이 과정이 필요 없습니다: 어디에 두든 실시간으로 지도를 만듭니다. [README.md](../README.md) 참고.)

## 3. 저장

RTAB-Map은 데이터베이스를 `~/.ros/rtabmap.db`에 자동으로 씁니다 (launch 종료 시). 2D 지도도 저장하려면:
```bash
mkdir -p ~/maps
ros2 run nav2_map_server map_saver_cli -f ~/maps/map1 --ros-args -r map:=/rtabmap/map
cp ~/.ros/rtabmap.db ~/maps/map1.db
```

## 4. 위치 추정 모드

```bash
ros2 launch ~/guide_robot/robot/launch/vslam.launch.py localization:=true database_path:=/home/pinky/maps/map1.db
```
이 모드에서는 지도가 바뀌지 않고, RTAB-Map이 `map -> odom` TF와 `/rtabmap/localization_pose`를 제공합니다 (AMCL 대신).

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `pinky_camera.yaml not found` | 먼저 카메라 캘리브레이션 |
| `camera 640x480, calibration ...: mismatch` | 다른 해상도로 캘리브레이션함: 다시 캘리브레이션 |
| RTAB-Map "Did not receive data since 5 seconds" | 어떤 토픽이 오지 않음: `ros2 topic hz /vslam/image_raw /vslam/camera_info /scan /odom` |
| 지도가 "이중으로" 그려짐 | 더 천천히 주행; 루프 클로저를 위해 출발점으로 돌아오기 |
| Pi가 매우 뜨겁거나 느림 | `cam_hz:=5` |
