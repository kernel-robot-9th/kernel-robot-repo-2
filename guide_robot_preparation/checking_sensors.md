# Pinky 센서 확인 (SLAM 전에)

목표: 지도를 그리기 전에 Pinky의 각 센서가 동작하는지, 올바른 주기로 데이터를 보내는지, TF 트리가 올바른지 확인하는 것. 먼저 연결이 설정되어 있어야 합니다: [checking_connection.md](checking_connection.md).

마지막 업데이트: 2026-10-21. 이 환경의 실제 결과는 아래 **"이 Pinky의 결과"** 절에 있습니다.

## 1단계. Pinky 전체 실행

Pinky에 접속합니다 (`ssh pinky@192.168.129.116`). 명령마다 별도 터미널에서 실행하고 터미널은 열어 둡니다:

```bash
# 터미널 1: 모터, 오도메트리, LiDAR, TF, 배터리
ros2 launch pinky_bringup bringup_robot.launch.xml

# 터미널 2: IMU (BNO055) -> /imu_raw
ros2 run pinky_imu_bno055 main_node

# 터미널 3: 카메라 -> /camera/image_raw (640x480, ~30 Hz)
python3 ~/marker_follow/cam_pub.py
```

알아 두면 좋은 점:

* 워크스페이스는 `~/pinky_pro`이고 `.bashrc`에서 이미 source되어 있습니다.
* bringup 파일은 `.xml` 형식입니다. `ros2 launch pinky_bringup` 다음에 **파일 이름**을 반드시 써야 합니다. 안 쓰면 `file 'None' was not found` 오류가 납니다. Tab 자동 완성을 쓰려면 패키지 이름 뒤에 공백을 넣으세요.
* 카메라는 bringup에 포함되어 있지 않습니다. 카메라는 한 번에 한 프로그램만 쓸 수 있습니다 (`play_cam.py`나 `rtsp_server_pinky.py`가 실행 중이면 먼저 멈추세요).
* 카메라는 Pinky에 **180° 거꾸로** 달려 있습니다. `cam_pub.py`는 영상을 회전하지 않고, `robot/vslam_camera.py`, `cam_preview.py`, `calibrate_camera.py`가 직접 회전합니다 (`--no-rotate`로 끔).
* IMU 패키지에는 launch 파일이 없으므로 `ros2 run`으로 실행합니다.

확인 (Pinky에서): `ros2 topic list -t`에 다음이 보여야 합니다:

```
/scan              sensor_msgs/msg/LaserScan
/odom              nav_msgs/msg/Odometry
/tf, /tf_static
/joint_states      sensor_msgs/msg/JointState
/imu_raw           sensor_msgs/msg/Imu
/camera/image_raw  sensor_msgs/msg/Image
/battery/percent   std_msgs/msg/Float32
/battery/voltage   std_msgs/msg/Float32
```

`/scan`이나 `/odom`이 없으면 bringup이 멈춘 것입니다. 터미널 1의 오류를 읽고 bringup을 다시 실행하세요.

## 2단계. 주기 확인 (`ros2 topic hz`)

`ros2 topic hz`는 멈출 때까지 계속 실행됩니다. 명령은 **하나씩** 입력하고 각각 끝나면 **Ctrl+C**를 누르세요. 여러 명령을 한꺼번에 붙여 넣으면 첫 번째만 실행됩니다.

```bash
ros2 topic hz /scan
ros2 topic hz /camera/image_raw
ros2 topic hz /imu_raw
ros2 topic hz /odom
```

먼저 **Pinky에서**, 그다음 **노트북에서** 확인하세요. 차이로 문제 위치를 알 수 있습니다:

* Pinky에서 없음 → 드라이버나 터미널 문제.
* Pinky에서는 있는데 노트북에서 없거나 끊김 → Wi-Fi 문제.

## 3단계. 자동 확인: `check_sensors.py`

로봇이 움직이지 않는 상태에서. **이 Pinky용 명령:**

```bash
# 노트북에서 (카메라를 Wi-Fi로 받지 않음):
python3 robot/check_sensors.py --gyro-deg --skip-camera

# Pinky에서 (카메라도 확인). 폴더는 ~/guide_robot_preparation에 복사되어 있어야 함:
cd ~/guide_robot_preparation && python3 robot/check_sensors.py --gyro-deg
```

옵션:

| 옵션 | 하는 일 |
|---|---|
| `--gyro-deg` | IMU 자이로가 deg/s임을 반영 (이 Pinky가 그러함). 없으면 정지한 로봇에서도 "드리프트" 경고가 나옴 |
| `--skip-camera` | 카메라 영상을 구독하지 않음. 노트북에서 필요: 640x480 영상이 Wi-Fi를 차지해서 LiDAR가 끊김 |
| `--seconds 10` | 더 오래 수신 (기본 5 s) |
| `--motion` | 회전 테스트 (4단계) |

스크립트가 하는 일:

* 토픽을 **최대 10초** 찾습니다. Wi-Fi로는 검색이 느리기 때문입니다. 예전 버전은 2초만 찾아서 매번 토픽을 2–3개만 찾았으니 새 버전을 쓰세요: 먼저 "Discovering topics..."를 출력합니다.
* 모든 센서 토픽을 **타입으로** 찾습니다: LiDAR, 카메라, 카메라 캘리브레이션, IMU, 오도메트리, 거리 센서, 배터리 (`BatteryState`와 Pinky의 `/battery/*` Float32), 바퀴, 3D 점.
* 각각에 대해 **주기 (Hz)**, **가장 긴 끊김** (`max gap`), **데이터 타당성**을 확인합니다. 끊김이 0.5 s를 넘으면 경고합니다: Wi-Fi로 실행 중이라면 SLAM을 Pinky에서 실행해야 한다는 뜻입니다.

| 센서 | 확인 내용 | 좋은 결과 |
|---|---|---|
| LiDAR | 점 개수, 유효한 점 비율, 가장 가까운/먼 거리 | ≥ 4 Hz, 유효 ≥ 50%, 가장 가까운 점 > 5 cm |
| 카메라 | 크기, 형식, 밝기 | ≥ 5 Hz, 너무 어둡지도 하얗지도 않음 |
| 카메라 캘리브레이션 | `fx`와 왜곡 계수가 있는지 | 캘리브레이션됨 (비주얼 SLAM에 필수) |
| IMU | 가속도 크기, 자이로 드리프트 | 정지 시 \|a\| ≈ 9.8 m/s², 자이로 작음, ≥ 30 Hz |
| 오도메트리 | 위치, 속도, 프레임 이름 | ≥ 10 Hz, 정지 시 속도 0 |
| 거리 센서 | 값이 범위 안에 있는지 | min–max 범위 안 |
| 배터리 | 전압, 퍼센트 | > 20% |

* **TF 트리**를 확인합니다: `odom → base_footprint`와 `base_footprint → 각 센서 프레임`. SLAM에 필수입니다.

`!`로 시작하는 줄이 무엇을 고쳐야 하는지 알려 줍니다.

## 4단계. 회전 테스트 (오도메트리 ↔ IMU ↔ LiDAR)

Pinky 주변을 비우세요. 제자리에서 약 90° 회전합니다:

```bash
python3 robot/check_sensors.py --motion --gyro-deg --skip-camera
# 베이스가 TwistStamped를 기대하면 --stamped 추가
```

예상 결과 (이 Pinky):

```
Motion test: Pinky turns in place for 3 s (clear the area around it)...
  odometry: +85° (command ~+86°)
  IMU gyro: +85°          <- --gyro-deg 사용 시. 없으면 ~+4800°
  LiDAR change: mean 0.30 m
  OK: odometry, IMU and LiDAR agree
```

Pinky는 0.5 rad/s로 3초 회전한 뒤 멈춥니다. 스크립트가 비교하는 것:

* **오도메트리**가 몇 도 회전했는지 (≈ +86° 예상; 왼쪽 회전이 양수).
* **IMU 자이로**도 그만큼 회전했는지 (차이 30% 미만이어야 함). ~57배 크면 스크립트가 "deg/s"라고 알려 줍니다.
* **LiDAR** 스캔이 바뀌었는지.

이것들이 맞지 않으면 지도가 기울거나 "이중으로" 그려집니다. 흔한 원인: 바퀴 반지름이나 바퀴 사이 거리가 틀림, IMU 축이 반대거나 단위가 다름, LiDAR 프레임이 회전됨.

## 5단계. 눈으로 확인 (RViz)

노트북에서:

```bash
rviz2                       # Fixed Frame = odom
```

추가: **LaserScan** (`/scan`), **TF**, **Odometry**, **RobotModel**. 노트북에서는 **Image**를 추가하지 마세요: 카메라 영상을 Wi-Fi로 받으면 네트워크를 차지해서 LiDAR가 더 끊깁니다. 카메라는 짧게 확인할 때만 보세요: `ros2 run rqt_image_view rqt_image_view`.

* teleop으로 Pinky를 회전시키세요: LiDAR 점은 벽 위에 **고정되어** 있어야 하고 로봇과 함께 돌면 안 됩니다. 벽이 돌면 오도메트리나 LiDAR TF가 틀린 것입니다.
* 로봇 앞의 벽은 RViz에서도 로봇 **앞쪽**에 보여야 합니다.

유용한 명령:

```bash
ros2 topic list -t                      # 모든 토픽과 타입
ros2 topic echo /imu_raw --once         # 메시지 하나
ros2 run tf2_tools view_frames          # TF 트리 -> frames.pdf
```

## 6단계. 카메라 캘리브레이션 (ChArUco 보드)

비주얼 SLAM (RTAB-Map)은 캘리브레이션 없이 동작하지 않습니다. 카메라로 거리나 위치를 계산하는 이후의 모든 노드도 fx/fy, cx/cy에 의존합니다. 자세한 단계별 기록: [calibration.md](calibration.md).

**보드:** [docs/charuco_board_9x7_25mm_5x5_A4.pdf](docs/charuco_board_9x7_25mm_5x5_A4.pdf). 9x7 칸 (25 mm), 흰 칸 안에 18 mm ArUco 마커. 마커는 `DICT_5X5_100` 사전에서 가져왔으므로 다른 용도의 `DICT_4X4_50` 마커와 섞이지 않습니다 (확인함: 4x4 검출기는 보드에서 아무것도 찾지 못함).

일반 체스보드보다 좋은 점: 보드가 화면에 다 들어오지 않거나 일부가 가려져도 코너를 찾습니다. Pinky 카메라는 낮은 위치에서 가까운 거리로 동작하므로 편리합니다.

**인쇄:**

1. **100% / 실제 크기**, "페이지에 맞춤"은 끔.
2. 자로 재세요: 칸 25 mm, 마커 18 mm여야 합니다. 다르면 잰 값을 `--square`와 `--marker`에 넣으세요.
3. 종이를 판지에 평평하게 붙이세요.

**캘리브레이션** (Pinky에서, `cam_pub.py` 실행 중; 화면 불필요):

```bash
python3 robot/calibrate_camera.py
# 칸이 24.5 mm로 나왔다면:
python3 robot/calibrate_camera.py --square 0.0245 --marker 0.0176
```

보드를 카메라 앞에서 **천천히** 움직이세요: 가까이와 멀리 (20–60 cm), 화면의 왼쪽, 오른쪽, 위, 아래에서, 기울여서. 터미널에 `TAKEN 1/25`, `TAKEN 2/25`, ...가 나옵니다. 25프레임이 모이면 스크립트가 직접 계산합니다:

```
Result: reprojection error 0.32 px (excellent)
  fx=499.6 fy=504.8 cx=322.3 cy=235.3  (horizontal field of view 65.3°)
Saved: /home/pinky/pinky_camera.yaml
```

오차 **< 0.5 px** 매우 좋음, **< 1 px** 좋음. 그보다 크면 다시 하세요: 보드는 평평하게, 조명은 좋게, 움직임은 천천히.

스크립트는 먼저 영상을 180° 회전합니다. `vslam_camera.py`도 똑같이 하므로 캘리브레이션이 SLAM이 보는 영상과 정확히 맞습니다.

**결과 사용:** `vslam_camera.py`와 `camera_tilt.py`가 `~/pinky_camera.yaml`을 자동으로 읽습니다.

나중에 다시 계산하려면 프레임을 저장해 둘 수 있습니다: `--save-frames ~/calib_imgs`. 그다음 `--images ~/calib_imgs`로 ROS 없이 다시 계산합니다.

> 일반 체스보드 ([docs/calibration_board_9x7_25mm_A4.pdf](docs/calibration_board_9x7_25mm_A4.pdf))와 ROS의 `cameracalibrator` 도구도 동작하지만, 보드 전체가 보여야 합니다. `cam_pub.py`가 `camera_info`를 발행하지 않으므로 거기서는 COMMIT이 아니라 SAVE를 누릅니다.

## 이 Pinky의 결과 (2026-10-21)

**주기, Pinky와 노트북에서:**

| 토픽 | Pinky에서 | 노트북에서 (Wi-Fi) | 상태 |
|---|---|---|---|
| `/scan` (LiDAR) | ~10 Hz, 안정 | 평균 ~8.7 Hz, 하지만 **최대 2초 끊김** | ✅ Pinky / ⚠️ Wi-Fi |
| `/camera/image_raw` | 32–34 Hz | 확인 안 함 (필요 없음) | ✅ |
| `/imu_raw` | ~55 Hz | ~55 Hz | ✅ (단위 주의) |
| `/odom` | — | 18–30 Hz | ✅ |
| `/joint_states` | — | 34–50 Hz | ✅ |

**노트북에서 `check_sensors.py --motion` 결과** (`--gyro-deg` 없이, 영어 출력으로 표시):

```
[WARN] IMU                  /imu_raw   54.9 Hz
         |a|=9.58 m/s², gyro=0.325 rad/s, orientation yes, frame=imu_link
[OK  ] Wheels/joints        /joint_states   33.8 Hz
         2: left_wheel_joint, right_wheel_joint
[OK  ] Odometry             /odom   18.3 Hz
         x=-0.00 y=0.00 yaw=-0°, v=-0.00 w=-0.01, odom→base_footprint
TF tree:
[OK  ] odom → base_footprint
[OK  ] base_footprint → imu_link  (-0.044, +0.000, +0.081) m
Motion test:
  odometry: +85° (command ~+86°)
  IMU gyro: +4844°
```

**Pinky 자체에서 전체 확인** (`--gyro-deg`, 터미널 3개 모두 실행 중):

```
[OK  ] LiDAR                /scan   10.0 Hz  (max gap 0.11 s)
         720 points, 360°, valid 98%, 0.27–0.97 m, frame=rplidar_link
[OK  ] Camera               /camera/image_raw   30.8 Hz  (max gap 0.12 s)
         640x480 bgr8, frame=camera, brightness 121/255
[OK  ] IMU                  /imu_raw  100.9 Hz  (max gap 0.02 s)
         |a|=9.58 m/s², gyro=0.012 rad/s, orientation yes, frame=imu_link
[OK  ] Wheels/joints        /joint_states   51.1 Hz  (max gap 0.04 s)
[OK  ] Odometry             /odom   30.0 Hz  (max gap 0.04 s)
[OK  ] Battery              /battery/percent   77%
[OK  ] Battery              /battery/voltage   7.41 V
TF tree:
[OK  ] odom → base_footprint
[----] base_footprint → camera no transform (not needed for SLAM; ...)
[OK  ] base_footprint → imu_link  (-0.044, +0.000, +0.081) m
[OK  ] base_footprint → rplidar_link  (-0.017, +0.000, +0.125) m
```

Pinky에서 모든 센서 ✅, 끊김은 0.12 s를 넘지 않습니다. 카메라 TF가 없는 이유는 `cam_pub.py`가 URDF에 없는 `camera` 프레임을 쓰기 때문입니다. SLAM은 이것이 필요 없습니다 (`vslam.launch.py`가 자체 `camera_link` TF를 추가). RViz에서 로봇 위의 카메라를 보고 싶을 때만 추가하세요 (치수는 자로 확인):

```bash
ros2 run tf2_ros static_transform_publisher --x 0.05 --z 0.10 \
    --frame-id base_footprint --child-frame-id camera
```

이전 확인의 LiDAR:

```
[OK  ] LiDAR                /scan   10.5 Hz
         720 points, 360°, valid 98%, 0.26–0.92 m, frame=rplidar_link
[OK  ] base_footprint → rplidar_link  (-0.017, +0.000, +0.125) m
```

**결론:**

1. **오도메트리가 정확함.** 86° 명령에 85° 회전. SLAM에 가장 중요한 부분입니다.
2. **LiDAR와 TF가 올바름.** 유효한 점 98%, `odom → base_footprint → rplidar_link` 있음.
3. **IMU 자이로가 rad/s가 아니라 deg/s로 나옴.** 4844° ≈ 85° × 57, 57은 180/π. 정지 상태의 "0.325"는 실제로 0.0057 rad/s, 즉 드리프트 없음. slam_toolbox는 IMU를 쓰지 않으므로 지도에는 영향이 없습니다. IMU를 쓸 때는 `python3 robot/imu_fix.py`를 실행하세요: `/imu/data`를 rad/s로 발행합니다 (`vslam.launch.py`는 자동으로 실행).
4. **Wi-Fi가 LiDAR를 끊어서 전달함** (노트북에서 최대 2초 끊김). 그래서 **SLAM과 Nav2는 Pinky 자체에서** 실행하고, 노트북은 RViz로 보기만 합니다.
5. **카메라는 Pinky에서 잘 동작함** (~33 Hz). 카메라를 쓰는 노드도 Pinky에서 실행하므로 영상을 노트북으로 보낼 필요가 없습니다.
6. **배터리**는 `sensor_msgs/BatteryState`가 아니라 `/battery/percent`와 `/battery/voltage` (Float32)로 나옵니다. 배터리를 읽는 노드는 이 점을 반영해야 합니다.

## SLAM에 필요한 조건

| 조건 | 이유 | 이 Pinky |
|---|---|---|
| LiDAR ≥ 4 Hz, 유효한 점이 많음 | 지도는 바로 이것으로 그려짐 | ✅ 10 Hz, 98% |
| `odom → base` TF 있음 | slam_toolbox가 로봇의 움직임을 여기서 얻음 | ✅ |
| `base → laser` TF가 있고 올바름 | 아니면 벽이 잘못된 위치에 그려짐 | ✅ |
| 회전 테스트에서 오도메트리가 정확함 | 아니면 지도가 기울어짐 | ✅ 85° / 86° |
| LiDAR가 끊김 없이 SLAM에 도착 | 아니면 지도가 "튐" | ✅ SLAM을 Pinky에서 실행하면 |
| 배터리 > 20% | 전압이 떨어지면 모터와 LiDAR가 불안정 | 매번 확인 |

카메라와 IMU는 slam_toolbox에는 필요 없지만 프로젝트에는 필요합니다: 카메라는 비주얼 SLAM과 사람/표지 인식에, IMU는 나중에 오도메트리를 보정하는 데 (EKF).

다음 단계: 카메라 캘리브레이션 ([calibration.md](calibration.md)), 그다음 비주얼 SLAM ([vslam.md](vslam.md)). 전체 상태: [progress.md](progress.md).

### 노트북에서 카메라 보기

원본 카메라 스트림 (640x480, 30 Hz)은 약 27 MB/s로 Wi-Fi에는 너무 무겁습니다. 그래서 Pinky에서 작은 JPEG 미리보기를 만듭니다:

```bash
python3 ~/marker_follow/cam_pub.py         # Pinky, 터미널 1
python3 robot/cam_preview.py               # Pinky, 터미널 2: /camera/preview/compressed (320px, 5 Hz, 180° 보정)
ros2 run rqt_image_view rqt_image_view     # 노트북: 목록에서 /camera/preview/compressed 선택
```

캘리브레이션 중에는 `cam_preview.py`가 필요 없습니다: `calibrate_camera.py`가 직접 `/calib/preview/compressed`를 발행합니다 (찾은 코너는 초록 점, 왼쪽에 저장한 프레임 수).
