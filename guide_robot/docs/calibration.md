# Pinky 카메라 캘리브레이션 (단계별)

2026-10-21/22에 한 작업을 순서대로 정리한 기록이자 다른 개발자를 위한 안내입니다. 다음 단계: [vslam.md](vslam.md) (비주얼 SLAM).

## 왜 캘리브레이션이 필요한가

Pinky에는 카메라가 하나 (모노)뿐입니다. "카메라가 하나면 캘리브레이션이 필요 없다"는 말은 **스테레오** 캘리브레이션 (두 카메라 사이의 거리와 각도 측정)에 해당합니다. 카메라 하나에도 내부 파라미터가 있습니다:

* **fx, fy**: 픽셀 단위 초점 거리;
* **cx, cy**: 광학 중심;
* **distortion**: 렌즈 왜곡.

필요한 곳:

| 위치 | 이유 |
|---|---|
| 비주얼 SLAM (RTAB-Map) | `camera_info` 없이는 아예 동작하지 않음 |
| 검은 테이프 검출 (`line_detector.py`) | 픽셀을 바닥 위 미터 좌표로 바꿀 때 fx/fy, cx/cy 사용 |

`cam_pub.py`는 `camera_info`를 발행하지 않으므로 직접 캘리브레이션했습니다.

## 1단계. 보드 고르기와 인쇄

**일반 체스보드 대신 ChArUco 보드를 사용했습니다.** ChArUco 보드는 흰 칸 안에 ArUco 마커가 있습니다. 장점: 보드가 일부만 보이거나 기울어져 있어도 코너를 찾습니다.

**사전 선택.** 다른 용도의 마커는 `DICT_4X4_50` 사전을 씁니다. 보드는 다른 사전인 `DICT_5X5_100`을 씁니다. 그래서 마커 추종 노드가 보드를 마커로 착각하지 않습니다.

파일: [charuco_board_9x7_25mm_5x5_A4.pdf](charuco_board_9x7_25mm_5x5_A4.pdf)

| 파라미터 | 값 |
|---|---|
| 칸 | 9 x 7 (내부 코너 48개) |
| 칸 한 변 | 25 mm |
| 마커 한 변 | 18 mm |
| 사전 | DICT_5X5_100 |
| 용지 | A4 |

**인쇄:**
* 프린터 설정에서 **100% / 실제 크기**를 고르세요. "페이지에 맞춤"을 고르면 크기가 줄어듭니다.
* 인쇄 후 자로 한 칸을 재세요. 우리 것은 **2.5 x 2.5 cm**로 정확했습니다.
* 다르게 나오면, 예를 들어 24.5 mm이면 스크립트에 `--square 0.0245`를 넘기세요.
* 보드는 판지나 단단한 파일에 **평평하게** 붙이세요. 휘어진 종이는 결과를 망칩니다.

## 2단계. Pinky로 파일 복사

```bash
rsync -av guide_robot/ pinky@PINKY_IP:~/guide_robot/
```
`PINKY_IP`는 Pinky에서 `hostname -I`로 확인합니다. Pinky의 사용자는 `pinky`입니다.

## 3단계. 연결 확인 (노트북 ↔ Pinky)

양쪽에서:
```bash
echo $ROS_DOMAIN_ID $ROS_STATIC_PEERS
hostname -I
```
* `ROS_DOMAIN_ID`는 양쪽이 같아야 합니다.
* `ROS_STATIC_PEERS`는 노트북에서는 Pinky IP, Pinky에서는 노트북 IP.
* 공유기가 날마다 IP를 바꿀 수 있습니다. 그러면 `~/.bashrc`를 고치고 `ros2 daemon stop` 후 새 터미널을 여세요.

## 4단계. 노트북에서 카메라 보기 (선택)

원본 카메라 스트림 (640x480, 30 Hz)은 약 27 MB/s로 Wi-Fi에는 너무 무겁습니다. 그래서 캘리브레이션 중에는 `calibrate_camera.py`가 작은 JPEG를 직접 발행합니다 (`/calib/preview/compressed`).

노트북에서:
```bash
ros2 run rqt_image_view rqt_image_view
```
목록에서 토픽을 고르고, 비어 있으면 🔄를 누르세요. 미리보기에서 찾은 코너는 초록 점으로, 왼쪽 위에 `N/25`가 표시됩니다.

목록에 `/compressed`가 없으면: `sudo apt install ros-jazzy-rqt-image-view ros-jazzy-compressed-image-transport`

미리보기가 없어도 캘리브레이션은 동작합니다. Pinky 터미널의 메시지로 따라갈 수 있습니다.

## 5단계. 캘리브레이션 실행

Pinky에서 터미널 두 개:
```bash
python3 ~/guide_robot/robot/cam_pub.py                                                  # 1: 카메라
cd ~/guide_robot && python3 robot/calibrate_camera.py --save-frames ~/calib_imgs     # 2: 캘리브레이션
```

스크립트 설명:
* 화면이 필요 없고 프레임을 스스로 고릅니다.
* 카메라가 거꾸로 달려 있으므로 먼저 영상을 180° 회전합니다. `vslam_camera.py`와 같으므로 캘리브레이션이 실제 사용하는 영상과 맞습니다.
* 두 조건을 만족할 때만 프레임을 저장합니다: 코너가 **12개 이상** 보이고, 보드가 이전 프레임 이후 움직였을 것.
* `--save-frames`는 저장한 프레임을 보관합니다. 나중에 `--images ~/calib_imgs`로 카메라 없이 다시 계산할 수 있습니다.

터미널 메시지:

| 메시지 | 의미 |
|---|---|
| `board not visible (0 corners)` | 보드가 화면에 없음. 아직 보여 주지 않았다면 정상 |
| `board not visible (7 corners)` | 보드가 일부만 보임, 코너 12개 미만 |
| `N corners: move the board somewhere else` | 이 자리의 프레임은 이미 저장함; 다른 곳으로 옮기세요 |
| `TAKEN 5/25 (32 corners, size 191px)` | 프레임 저장함 |

## 6단계. 보드 보여 주는 방법

* 가까이 (20 cm)와 멀리 (50–60 cm) 들어 보세요.
* 화면의 **왼쪽, 오른쪽, 위, 아래**와 **모서리**로 옮기세요.
* 각 방향으로 20–30° 기울이세요.
* 각 자리에서 1초 동안 멈추세요. 아니면 영상이 흐려집니다.
* 조명은 고르게, 보드에 반사가 없게 하세요.

약 10분 동안 25프레임을 모았습니다.

## 7단계. 결과

25프레임 후 스크립트가 결과를 출력하고 파일을 저장합니다:

```
Result: reprojection error 0.459 px (excellent)
  fx=582.5 fy=584.1 cx=313.7 cy=226.3  (horizontal field of view 57.6°)
  distortion: [0.2035, -1.0349, -0.0066, -0.0047, 1.597]
Saved: /home/pinky/pinky_camera.yaml
```

판단 기준:

| 지표 | 우리 값 | 기준 |
|---|---|---|
| 재투영 오차 | 0.459 px | < 0.5 매우 좋음, < 1.0 좋음, 그 이상이면 다시 |
| fx와 fy | 582.5 / 584.1 | 서로 비슷함 (정사각 픽셀) ✅ |
| cx, cy | 313.7, 226.3 | 영상 중심 (320, 240)에 가까움 ✅ |
| 시야각 | 57.6° | |
| 왜곡 k3 | 1.597 | 조금 큼. 보드가 화면 가장자리에 드물게 있었음. 지금은 충분하며, 문제가 생기면 가장자리를 더 많이 담아 다시 캘리브레이션 |

## 8단계. 결과 사용

비주얼 SLAM에서는 `robot/vslam_camera.py`가 `~/pinky_camera.yaml`을 자동으로 읽어 `/vslam/camera_info`로 발행합니다. 자세한 내용: [vslam.md](vslam.md). 안내원 모드 (`guide_mode.py`)도 같은 파일로 검은 테이프 위치를 계산합니다.

**중요:** 캘리브레이션은 640x480에서 했습니다. 카메라 해상도가 바뀌거나 카메라를 다시 달면 다시 캘리브레이션하세요. 크기가 맞지 않으면 `vslam_camera.py`가 경고합니다.

## 문제와 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| 노트북의 rqt 목록이 비어 있음 | IP나 `ROS_STATIC_PEERS`가 바뀜 | 3단계 |
| 항상 `0 corners` | 보드를 안 보여 줌, 너무 멂, 반사 | 20–60 cm, 조명 바꾸기 |
| `move the board somewhere else`만 나옴 | 보드가 한 자리에 있음 | 화면의 다른 곳으로 옮기기 |
| `cv2.aruco` 오류 | opencv-contrib 없음 | `pip install opencv-contrib-python` |
| 오차 > 1 px | 보드가 휨, 흐린 프레임 | 판지에 평평하게 붙이기, 더 천천히 움직이기 |
