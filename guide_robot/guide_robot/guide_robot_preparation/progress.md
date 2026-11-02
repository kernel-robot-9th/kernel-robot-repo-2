# guide_robot 준비: 지금까지 한 일

마지막 업데이트: 2026-10-22. 단계별 자세한 내용: [checking_connection.md](checking_connection.md), [checking_sensors.md](checking_sensors.md), [calibration.md](calibration.md), [vslam.md](vslam.md).

## 1. 노트북 ↔ Pinky ROS 연결 ✅

| 단계 | 결과 |
|---|---|
| `ROS_DOMAIN_ID` | 9090이었음 (동작 안 함, 최대 232) → 양쪽 **90** |
| `ROS_AUTOMATIC_DISCOVERY_RANGE` | 양쪽 `SUBNET` |
| 노트북 → Pinky ping (192.168.129.116) | 성공 |
| talker (Pinky) → listener (노트북) | 처음엔 조용했음: Pinky에 네트워크가 3개 있음 |
| `ROS_STATIC_PEERS` (노트북 → 192.168.129.116, Pinky → 192.168.129.121) + `ros2 daemon stop` | **성공**, "I heard: Hello World" |

IP: 노트북 `192.168.129.121`, Pinky `192.168.129.116`. Pinky의 다른 네트워크: `192.168.180.53`과 자체 핫스팟 `192.168.4.1`. IP가 바뀌면 `ROS_STATIC_PEERS`도 바꿔야 합니다.

## 2. Pinky의 프로그램 찾기 ✅

* 워크스페이스: `~/pinky_pro` (`.bashrc`에서 이미 source됨).
* 패키지: `pinky_bringup`, `pinky_navigation`, `pinky_description`, `pinky_imu_bno055`, `pinky_sensor_adc`, `pinky_led`, `pinky_lamp_control`, `pinky_emotion`, `pinky_interfaces`, `pinky_gz_sim`, `sllidar_ros2`.
* bringup launch 파일: `bringup_robot.launch.xml` (`.launch.py`가 아니라서 `find`로 못 찾았음).
* 카메라는 bringup에 포함되어 있지 않음: `~/marker_follow/cam_pub.py`로 실행.
* IMU는 launch 파일이 없음: `ros2 run`으로 실행.

## 3. Pinky 전체 실행

Pinky에서 터미널 3개, 모두 열어 둡니다:

```bash
ros2 launch pinky_bringup bringup_robot.launch.xml   # 모터, 오도메트리, LiDAR, TF, 배터리
ros2 run pinky_imu_bno055 main_node                  # IMU -> /imu_raw
python3 ~/marker_follow/cam_pub.py                   # 카메라 -> /camera/image_raw (30 Hz)
```

## 4. 센서 확인 결과 ✅

`python3 robot/check_sensors.py`와 `--motion`으로.

| 센서 | 토픽 | 결과 |
|---|---|---|
| LiDAR | `/scan` (frame `rplidar_link`) | ✅ 10.5 Hz, 720점, 360°, 98% 유효, 0.26–0.92 m |
| 오도메트리 | `/odom` | ✅ 18–30 Hz; 회전 테스트 **+85°** (명령 +86°): 정확함 |
| 바퀴 | `/joint_states` | ✅ 34–50 Hz, `left_wheel_joint`, `right_wheel_joint` |
| IMU | `/imu_raw` (frame `imu_link`) | ⚠️ 55 Hz, \|a\| = 9.58 m/s². **자이로가 deg/s**로 나옴, rad/s가 아님 (회전 테스트에서 4844° ≈ 85° × 57) |
| 배터리 | `/battery/percent`, `/battery/voltage` (Float32) | 있음 |
| 카메라 | `/camera/image_raw` | ✅ Pinky에서 32–34 Hz (640x480). 노트북으로 보낼 필요 없음 |
| TF | `odom → base_footprint → rplidar_link`, `→ imu_link` | ✅ |

발견한 것과 변경 사항:

* **IMU 자이로가 deg/s.** `python3 robot/imu_fix.py`가 rad/s로 바꿔 `/imu/data`로 발행합니다 (`vslam.launch.py`가 자동으로 실행). 정지 상태의 "0.325"는 실제로 0.0057 rad/s, 즉 드리프트 없음.
* **카메라가 180° 거꾸로 달려 있음.** `vslam_camera.py`, `cam_preview.py`, `calibrate_camera.py`가 자동으로 영상을 회전합니다 (`--no-rotate`로 끔).
* **`check_sensors.py`의 예전 버전**은 토픽을 2초만 찾아서 Wi-Fi로는 다 찾지 못했습니다. 새 버전은 최대 10초 기다립니다.

**Pinky 자체에서 최종 확인** (`check_sensors.py --gyro-deg`): LiDAR 10 Hz, 카메라 31 Hz, IMU 101 Hz, 오도메트리 30 Hz, 바퀴 51 Hz, 배터리 77% / 7.41 V. 끊김 ≤ 0.12 s. TF: `odom → base_footprint → rplidar_link / imu_link` ✅. **SLAM 조건을 모두 만족.**

## 5. 카메라 캘리브레이션 ✅ (2026-10-22)

* Pinky에서, ChArUco 보드로, 25프레임: 오차 **0.459 px** (매우 좋음).
* fx=582.5 fy=584.1 cx=313.7 cy=226.3, 수평 시야각 57.6°.
* 파일: Pinky의 `/home/pinky/pinky_camera.yaml`.
* 왜곡 k3=1.6은 조금 큼: 보드가 화면 가장자리에 드물게 있었음. 필요하면 나중에 다시 캘리브레이션.
* 노트북에서 카메라 보기: `robot/cam_preview.py` (`/camera/preview/compressed`), 캘리브레이션 중에는 `/calib/preview/compressed`.

## 6. 비주얼 SLAM 준비 (2026-10-22)

* 선택: **RTAB-Map** (모노 카메라 = 루프 클로저, LiDAR = ICP 기하, 바퀴 오도메트리).
* 추가: `robot/vslam_camera.py`, `robot/launch/vslam.launch.py`, [vslam.md](vslam.md).
* Pinky에 `ros-jazzy-rtabmap-ros` 설치 (183 MB, 여유 공간 5.3 GB).
* 카메라 위치 측정: 바닥에서 6.2 cm, 바퀴 축 중심에서 3 cm 앞, 아래로 기울어짐. 기울기 측정용 `robot/camera_tilt.py` (세운 보드 + solvePnP; 합성 테스트: 0°/8° 정확, 15°에서 ~1° 오차). `vslam.launch.py` 기본값 `cam_x=0.03 cam_z=0.062`.

## 7. 남은 문제

1. **Wi-Fi로는 LiDAR가 불안정.** Pinky에서 `/scan`은 안정적인 10 Hz. 노트북에서는 평균 ~8.7 Hz지만 가끔 최대 2초 끊김. 그래서 **SLAM과 Nav2는 Pinky 자체에서** 실행하고, 노트북은 RViz로 보기만 합니다.
2. **bringup이 한 번 멈춘 적 있음** (`/scan`, `/odom`이 사라짐). 원인은 아직 모름: 터미널의 오류를 확인해야 함.

## 8. 다음 단계

준비 작업은 끝났습니다. 이어지는 작업은 메인 **guide_robot** 프로젝트에서: 지도 만들기 (`vslam.launch.py`), 사람 인식, 안내원 모드.
