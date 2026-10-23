# OMX VLA — 자연어 명령 Pick & Place (ROS 2 Jazzy + MoveIt2 + Ollama)

탑뷰 RGB 카메라(Depth 없음) + 테이블 네 꼭짓점 ArUco 마커로 블록 위치를 구하고,
Ollama LLM이 "어떤 블록을 어디에" 결정하면 MoveIt2로 ROBOTIS OMX-F가 집어서 옮깁니다.

```
/camera/image_raw ─▶ vla_perception ─/vla/blocks─▶ vla_planner ──/pick_place──▶ vla_executor ─▶ move_group ─▶ OMX-F
  (Gazebo / usb_cam)   ArUco→호모그래피              Ollama(JSON)                    top-down IK
                       HSV 색 블록 검출              + 검증(도달범위/충돌/쌓기)       + MoveIt 계획·실행
```

## 패키지

VLA 패키지(`vla_*`)는 `src/vla_planner_robot/`에 있습니다. `src/`에는 ROBOTIS upstream 패키지와 `pinky_pro`(AMR)도 있습니다.

| 패키지 | 역할 |
|---|---|
| `open_manipulator` (ROBOTIS, jazzy) | OMX-F URDF / ros2_control / MoveIt config |
| `vla_sim` | Gazebo 월드(테이블, ArUco 0~3, 색 블록 4개, 탑뷰 카메라) + `sim.launch.py` |
| `vla_interfaces` | `Block`, `BlockArray` msg / `PickPlace`, `ExecuteCommand` action |
| `vla_perception` | 마커 → 호모그래피(pixel→base xy), 블록 높이 시차 보정, HSV 블록 검출 |
| `vla_executor` | `/pick_place` 액션 서버: 수직 하향 IK + `move_group`(Pilz PTP) + 그리퍼 |
| `vla_planner` | `/execute_command` 액션 서버: Ollama → JSON 계획 → 검증 → `/pick_place` 순차 실행, 한국어 CLI |
| `vla_calibration` | 캘리브레이션 도구 4종: 카메라 내부 파라미터, 블록 색(HSV), 마커↔로봇 좌표, 손목 카메라 ROI |
| `vla_bringup` | 전체 실행 `sim_vla.launch.py`(1팔), `dual_sim_vla.launch.py`(2팔), `calib_dir`로 캘리브레이션 결과 적용, `stop_vla.sh` |
| `vla_dual_description` | OMX-F 2대(`left_`/`right_`) + 7.5 cm 보드 URDF, 시뮬 컨트롤러 설정 |
| `vla_dual_moveit_config` | 2팔 MoveIt 설정: 그룹 `left_arm`, `right_arm`, `both_arms`, 그리퍼 2개 |

## 0. 사전 준비 (최초 1회)

```bash
sudo apt install -y ros-jazzy-moveit ros-jazzy-moveit-py ros-jazzy-realsense2-description \
  ros-jazzy-dynamixel-sdk ros-jazzy-dynamixel-interfaces ros-jazzy-usb-cam python3-opencv
ollama pull gemma4:e2b          # 이미 있으면 생략
```

## 1. 빌드

> ⚠️ **venv(`(ros)`)가 켜진 상태로 빌드하지 마세요.** venv의 python에는 `catkin_pkg`가 없어 빌드가 실패합니다.
> ⚠️ 병렬 빌드가 메모리(15GB)를 넘으면 강제 종료(exit 137)되므로 worker 수를 제한합니다.

```bash
deactivate 2>/dev/null          # venv 끄기
cd ~/dev_ws/robot
# 외부 패키지(pinky_pro·ROBOTIS 3종)는 저장소에 없다 — 처음 한 번 맨 위 README 부록 A의 git 명령으로 고정 커밋을 받는다
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
MAKEFLAGS=-j4 colcon build --symlink-install --parallel-workers 2 \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
```

## 2. 실행 (시뮬레이션)

모든 터미널에서 먼저:

```bash
deactivate 2>/dev/null
source /opt/ros/jazzy/setup.bash
source ~/dev_ws/robot/install/setup.bash
export ROS_DOMAIN_ID=56           # 모든 터미널에서 동일하게
```

### 터미널 1 — 전체 실행

```bash
ros2 run vla_bringup stop_vla.sh            # 이전 실행이 남아 있으면 정리 (없으면 "nothing running")
ros2 launch vla_bringup sim_vla.launch.py
```

> 이전 시뮬레이션이 같은 `ROS_DOMAIN_ID`에서 일부라도 살아 있으면(Gazebo만 죽고 move_group·노드가 남은 경우 등)
> 노드가 두 벌이 되어 RViz가 죽거나 팔이 엉뚱하게 움직입니다. 그래서 launch는 시작 전에 이를 검사하고,
> 남아 있으면 `a previous VLA simulation is still running` 오류와 함께 멈춥니다. 종료할 때는 launch 터미널에서 Ctrl-C 한 번,
> 그래도 남으면 `stop_vla.sh`를 실행하세요.

Gazebo, MoveIt RViz, 검출 결과 화면(`/vla/debug_image`), perception·executor·planner 노드가 함께 뜹니다.

RViz 오른쪽에 카메라 패널이 있습니다.

| 패널 | 토픽 | 기본 |
|---|---|---|
| Top camera (detections) | `/vla/debug_image`: 탑뷰 + 마커·블록 인식 결과 | 켜짐 |
| Wrist grasp check | `/vla/wrist_debug`: 마지막 손목 카메라 집기 판정 | 켜짐 (첫 집기 전에는 "No Image") |
| Top camera (raw) | `/camera/image_raw`: 탑뷰 원본 | 꺼짐 (Displays에서 체크) |

RViz 설정 파일: 1팔은 `vla_sim/rviz/vla_single.rviz`(ROBOTIS RViz 대신 사용), 2팔은 `vla_dual_moveit_config/config/moveit.rviz`.
별도 rqt 창은 RViz와 같은 탑뷰 화면이라 기본으로 꺼져 있습니다(`image_view:=true`로 켬).

| 인자 | 기본값 | 설명 |
|---|---|---|
| `headless` | `false` | `true`면 Gazebo GUI 없이 실행 |
| `rviz` | `true` | MoveIt RViz |
| `image_view` | `false` | 별도 rqt 검출 결과 창 (RViz에도 있음) |
| `model` | `gemma4:e2b` | Ollama 모델 이름 |
| `dry_run` | `false` | `true`면 계획만 하고 로봇은 움직이지 않음 |

### 터미널 2 — 자연어 명령

```bash
ros2 run vla_planner cli
> 빨간 블록을 가운데로 옮겨
> 파란 블록을 노란 블록 위에 쌓아줘
> put the green block to the right of the red block
```

CLI 없이 보내는 방법:

```bash
# 액션 (진행 상황 피드백 포함)
ros2 action send_goal --feedback /execute_command vla_interfaces/action/ExecuteCommand "{command: '빨간 블록을 가운데로 옮겨'}"
# 토픽 (결과는 /vla/status)
ros2 topic pub --once /vla/command std_msgs/msg/String "{data: '빨간 블록을 가운데로 옮겨'}"
ros2 topic echo /vla/status
```

### 단계별 확인용 명령

```bash
ros2 topic echo /vla/blocks                     # 검출된 블록 (base 좌표, m)
ros2 run rqt_image_view rqt_image_view /vla/debug_image
# LLM 없이 좌표로 바로 pick & place
ros2 action send_goal /pick_place vla_interfaces/action/PickPlace \
  "{pick_x: 0.18, pick_y: 0.08, pick_yaw: 0.0, pick_z_offset: 0.0, place_x: 0.18, place_y: 0.0, place_yaw: 0.0, place_z_offset: 0.0}"
```

## 2-1. 두 팔(left / right) 시뮬레이션

OMX-F 2대가 7.5 cm 보드 위에 있고, 보드보다 7.5 cm 낮은 바닥에서 작업하는 구성입니다.
명칭은 `left`/`right`를 씁니다. ROBOTIS의 리더 모델 이름 `omx_l`과 헷갈리지 않도록 하기 위해서입니다.

```bash
ros2 run vla_bringup stop_vla.sh
ros2 launch vla_bringup dual_sim_vla.launch.py      # base_separation:=0.33 (두 베이스 중심 사이 거리)
ros2 run vla_planner cli
> 왼팔로 노란 블록을 왼쪽 앞으로 옮겨
> 빨간 블록을 오른쪽으로 옮겨            # 한 팔로 안 되면 자동으로 전달 2단계
> 그릇을 두 팔로 들어서 뒤로 옮겨        # 트레이는 양팔 협동 운반
> 빨간 블록을 가운데로 옮겨              # 가운데에 그릇이 있으면 그릇 안에 놓음
> 노란 블록을 그릇에 넣어
```

| 기능 | 동작 |
|---|---|
| 자동 배정 | 집기와 놓기 지점에 모두 닿는 팔 중 블록에 가까운 팔이 수행 |
| 팔 지정 | "왼팔로 …" / "오른팔로 …". 지정한 팔이 닿지 않으면 움직이기 전에 거부 |
| 전달(핸드오프) | 한 팔로 안 되면, 두 팔이 다 닿고 비어 있는 지점(보드에서 10 cm 이상, 다른 물체와 5 cm 이상)에 내려놓은 뒤 다른 팔이 이어서 옮김 |
| 협동 운반 | 보라색 트레이(양끝 손잡이)를 두 팔이 동시에 잡고, 두 손 사이 거리를 유지하는 동기 궤적(`both_arms`, `/execute_trajectory`)으로 들어 옮김 |
| 충돌 | 하나의 MoveIt 설정이라 팔끼리, 팔과 보드 사이 충돌을 검사 |

**좌표계**: `world` = 바닥(마커) 좌표계, z = 0이 작업면입니다. 팔 베이스는 `world → left_link0`/`right_link0` 고정 TF로 정해집니다.
executor는 목표를 `world`로 받아 TF로 각 팔 기준 좌표로 바꾼 뒤 IK를 풉니다.

**설정 파일**: `perception_dual.yaml`(마커 4개는 바닥 (0.10/0.40, ±0.40)), `executor_dual.yaml`(팔별 접두사·그룹·그리퍼·손목 카메라), `planner_dual.yaml`(팔 이름, `world` 기준 영역 좌표, 전달 지점 조건).

**캘리브레이션 (2팔)**: 마커는 고정하고 팔 베이스 위치를 구합니다. 결과는 `calib/arm_poses.yaml`이며, URDF 인자 `left_x/left_y/left_yaw/...`로 적용됩니다(`dual_sim.launch.py arm_poses:=...`, 실물용).

```bash
E=install/vla_executor/share/vla_executor/config/executor_dual.yaml
P=install/vla_perception/share/vla_perception/config/perception_dual.yaml
ros2 run vla_calibration table --arm left  --color red  --executor-config $E --perception-config $P
ros2 run vla_calibration table --arm right --color blue --executor-config $E --perception-config $P
ros2 run vla_calibration wrist --arm right --color blue --executor-config $E
```

**시뮬 결과 (2026-10-16)**

| 항목 | 결과 |
|---|---|
| 블록·트레이 인식 | 블록 최대 3 mm, 트레이 크기 0.242×0.058 m(실제 0.24×0.06) |
| 단일 팔 바닥 pick & place | 대부분 4–7 mm. 왼팔 반복 6회 중 2회는 집게 안에서 미끄러져 2–3 cm 어긋남 |
| 협동 운반 5회 | 4회 성공(6.7–9.7 mm, 기울기 최대 1.9–6.2°), 1회 트레이가 보드 쪽으로 끌림(원인 미확인) |
| 자연어 | 왼팔 지정 ✅, 오른팔이 닿지 않는 명령 거부 ✅, 전달 2단계 ✅(최종 11 mm), 그릇 양팔 운반 ✅(8.6 mm) |
| 팔 베이스 캘리브레이션 | 왼팔 추정 (−0.008, 0.162, +0.9°), 실제 (0, 0.165, 0°): 로봇의 놓기 편향이 반영됨 |

**한계**
- 두 팔이 함께 닿는 공유 영역이 좁습니다(y = 0 근처 x 0.10–0.17 m). 그래서 트레이가 그 자리에 있으면 전달할 수 없습니다.
- 동시 독립 동작은 지원하지 않고, 한 번에 한 팔씩 움직입니다(협동 운반 제외).
- 실물 2팔: 두 OMX-F 모두 Dynamixel ID가 11–16이라 U2D2가 2개 필요합니다(`left_port`, `right_port`). ROBOTIS ros2_control 매크로의 서비스 이름(`dynamixel_hardware_interface/...`)이 겹치므로 실물 launch에서 따로 처리해야 합니다.
- 실측 필요: 두 베이스 중심 사이 거리(`base_separation`, 지금 0.33 추정), 1번 관절 축에서 보드 앞 가장자리까지 거리(`board_front`, 0.06 추정), 실제 그릇 크기·손잡이.

## 3. 좌표계와 명령 규칙

- 기준 좌표계: 로봇 베이스 `link0`, **+x = 로봇에서 먼 쪽(앞)**, **+y = 로봇의 왼쪽**, 테이블 z = 0
- ArUco 마커: **`DICT_5X5_100`**, ID 0–3, 한 변 5 cm (`aruco_dictionary` 파라미터로 변경 가능)
- 시뮬 마커 중심: ID0 (0.05, 0.20), ID1 (0.33, 0.20), ID2 (0.33, −0.20), ID3 (0.05, −0.20)
- 블록: 2.5cm 정육면체, 빨강/초록/파랑/노랑
- 놓을 위치 종류
  - **영역**: `center, left, right, front, back, front_left, front_right, back_left, back_right`
  - **상대 위치**: 다른 블록의 앞/뒤/왼쪽/오른쪽 5cm
  - **위에 쌓기**
- 작업 반경: 0.09 m ≤ r ≤ 0.25 m. 벗어나거나 다른 블록과 3.5cm 안으로 겹치면 실행 전에 거부합니다.
- LLM은 검출된 블록 id 중에서만 고릅니다. 좌표는 코드가 계산하므로 LLM이 좌표를 지어낼 수 없습니다.

## 4. 주요 설정 파일

| 파일 | 내용 |
|---|---|
| `src/vla_planner_robot/vla_perception/config/perception_sim.yaml` | ArUco 딕셔너리(`aruco_dictionary`), 마커 ID·위치, 블록 높이, HSV 범위(`hsv.<color>`) |
| `src/vla_planner_robot/vla_executor/config/executor.yaml` | 집기 높이 `grasp_z`, 접근 높이, 그리퍼 열림/닫힘, 속도, 작업 반경 |
| `src/vla_planner_robot/vla_planner/config/planner.yaml` | Ollama 주소·모델, 상대 위치 간격, 충돌 거리 |

## 5. 테스트

```bash
cd ~/dev_ws/robot/src/vla_planner_robot
(cd vla_planner && python3 -m pytest -q test)                                              # 계획 해석·검증, 2팔 (24)
PYTHONPATH=vla_perception:$PYTHONPATH python3 -m pytest -q vla_perception/test               # ArUco 딕셔너리·검출 (4)
PYTHONPATH=vla_executor:vla_perception:$PYTHONPATH python3 -m pytest -q vla_executor/test   # 손목 집기 판정 (5)
PYTHONPATH=vla_calibration:vla_executor:vla_perception:$PYTHONPATH \
  python3 -m pytest -q vla_calibration/test                                                # 캘리브레이션 수학 (8)
```

## 6. 현재 상태 (시뮬)

- 블록 위치 추정 오차 최대 **2.1 mm** (Gazebo 실제 위치 대비)
- 좌표 지정 이동 3/3 (4–6 mm), 쌓기 8/9 (회전 블록 포함), 손목 카메라 집기 확인: 정상 85–99% / 실패 0%
- `gemma4:e2b` 명령 해석 10개 중 **10개** 정답, 평균 3.1초 (첫 호출은 모델 로딩 ≈15초)
- 최종 자연어 명령 5개 중 5개 정상 처리 (실행 4, 올바른 거부 1)
- 매 단계 후 카메라로 결과를 확인하고, 목표에서 3 cm 이상 벗어나거나 쌓기가 무너지면 실패로 보고
- 보고서: [docs/report_visual.pdf](docs/report_visual.pdf) (요약), [docs/report_technical.pdf](docs/report_technical.pdf) (기술 문서)

시뮬 전용 설정: `src/vla_planner_robot/vla_sim/config/omx_f_sim_controllers.yaml`의 `position_proportional_gain: 1.0`.
기본값 0.1이면 팔이 중력에 처져 집기에 실패합니다.

### 손목 카메라 집기 확인

블록을 들어 올린 직후(`verify grasp` 단계) 손목 카메라 영상의 손가락 사이 영역(ROI)에서 집으려던 색이 차지하는 비율을 잽니다.
`wrist_min_fill`(60%) 미만이면 집게를 열고 관찰 자세로 돌아간 뒤 실패로 보고합니다.

| 상황 | ROI 색 비율 | 판정 |
|---|---|---|
| 정상 집기 (일반/회전/어긋난 위치) | 85–99% | 통과 |
| 빈 자리를 집음 | 0% | 실패 |
| 블록 위에서 헛잡음 (블록은 테이블에 남음) | 0% | 실패 |
| 다른 색 블록을 집음 | 0% | 실패 |

- 시뮬: `sim.launch.py`가 `link5`에 손목 카메라(320×240, `/wrist_camera/image_raw`)를 붙입니다. 손가락 사이에 보이던 URDF의 빨간 EE 표시 박스는 오탐을 막기 위해 제거합니다.
- 확인 화면: `ros2 run rqt_image_view rqt_image_view /vla/wrist_debug`
- 관련 파라미터 (`executor.yaml`): `wrist_check`, `wrist_required`, `wrist_image_topic`, `wrist_roi`, `wrist_min_fill`, `wrist_timeout`
- 실물: 카메라 장착 위치가 다르면 `wrist_roi`와 `wrist_min_fill`을 다시 맞춰야 합니다. 손목 카메라가 없으면 `wrist_check: false`로 끕니다.

## 7. 캘리브레이션 (`vla_calibration`)

> **실물 탑뷰 카메라(2026-10-22)**: ChArUco 내부 캘리브레이션 + 테이블 9점 호모그래피(픽셀 → 오른팔 x, y)는 `ros2 run vla_calibration top_camera capture|intrinsics|points|homography`로 한다. 인쇄물·순서는 `docs/calibration/README.md`. 아래 표의 도구는 시뮬(ROS 토픽) 기준이다.

실물(또는 카메라·마커·조명이 바뀐 환경)에서 아래 순서로 실행합니다. 결과는 `~/dev_ws/robot/calib/`에 저장되고,
`calib_dir`로 지정하면 launch가 기본 설정 위에 덮어씁니다.

| 순서 | 명령 | 준비 | 결과 파일 → 적용 대상 |
|---|---|---|---|
| 1 | `ros2 run vla_calibration intrinsics --board 9x6 --square 0.03` | 체커보드를 카메라 아래에서 기울이고 움직임 (자동 20장 수집) | `camera_info.yaml` → usb_cam `camera_info_url` |
| 2 | `ros2 run vla_calibration colors --colors red green blue yellow` | 마커 안쪽에 색별 블록 1개씩, 팔은 관찰 자세 | `colors.yaml` → perception + executor `hsv.*` |
| 3 | `ros2 run vla_calibration table --color red` | 빨간 블록 1개만 남김. 팔이 시작점 위에서 열리면 블록을 손가락 아래에 두고 Enter | `table.yaml` → perception `marker_positions` |
| 4 | `ros2 run vla_calibration wrist --color red` | 빨간 블록 1개 | `wrist.yaml` → executor `wrist_roi`, `wrist_min_fill` (+ `wrist_calibration.png`) |

```bash
ros2 launch vla_bringup sim_vla.launch.py calib_dir:=~/dev_ws/robot/calib   # 결과 적용
```

**각 도구가 하는 일**

- **intrinsics**: 체커보드 자세가 기존 샘플과 충분히 다를 때만 자동 캡처 → `cv2.calibrateCamera` → ROS camera_info YAML.
  perception은 `camera_info`의 K·D로 마커·블록 픽셀을 왜곡 보정합니다.
- **colors**: 마커 사각형 안의 채도 높은 영역을 색 이름에 매칭(색상환 거리)해 15프레임 동안 픽셀을 모은 뒤,
  hue는 1–99 백분위 ± 6, S·V 하한은 2 백분위에서 여유를 둡니다(빨강은 0/179 경계에서 2구간으로 나눔).
- **table**: 마커끼리의 상대 배치(자로 잰 `marker_positions`)는 그대로 두고, 그 사각형이 로봇 기준으로 어디 있는지를 구합니다.
  로봇이 블록을 12곳에 직접 놓고, 카메라가 본 위치와 명령 위치 사이의 **2D 강체 변환(회전+이동)**을 맞춥니다(이상치 제거, leave-one-out 오차 보고).
  집기 실패 시 카메라로 다시 찾아 재시도합니다. `--fit-scale`은 마커 간 거리 측정이 부정확할 때 배율도 함께 맞춥니다.
- **wrist**: 잡은 상태 / 빈 집게 / 블록 위에서 헛잡음 상태의 손목 영상을 찍어, 잡은 블록이 항상 덮는 영역을 ROI로,
  잡음/놓침 비율의 중간값을 기준값으로 정합니다. 여유가 25% 미만이면 경고(종료 코드 2)합니다.

**시뮬 검증 결과** (`calib_sim/`)

| 도구 | 결과 |
|---|---|
| intrinsics | fx 1325.28 (실제 1324.90, **+0.03 %**), RMS 0.22 px, 20장 |
| colors | 4색 모두 검출, 수집 픽셀 재현율 98–100 %, 색 범위 겹침 없음 |
| table | 마커 배치를 일부러 2° 회전 + 14 mm 이동시켜 시작 → 회전 **−2.04°** 복원, 맞춤 잔차 3.1 mm, leave-one-out 3.8 mm |
| wrist | 잡음 95–100 % / 빈 집게·헛잡음 5.7 % → 기준 50 %, 여유 89 % |

> table 캘리브레이션은 카메라를 **로봇이 실제로 블록을 놓는 위치**에 맞춥니다. 시뮬에서는 로봇이 늘 약 9 mm 짧게 놓아서,
> 적용 후 카메라↔로봇 일관성은 0–1 mm로 좋아지지만 Gazebo 절대 좌표와는 약 9 mm 차이가 납니다.
> 블록 기준 작업(쌓기·옆에 놓기)에는 일관성이 중요하므로 이 방식을 택했습니다.

시뮬에서 직접 해보기: 체커보드는 `ros2 run vla_sim checkerboard_sweep.py --poses 40`이 대신 움직여 줍니다(intrinsics 실행 중에 별도 터미널에서).

## 8. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `No module named 'catkin_pkg'` | venv가 켜져 있음 → `deactivate` 후 `build/ install/ log/` 삭제하고 다시 빌드 |
| `No module named 'rclpy._rclpy_pybind11'` (rqt_image_view, cli 등) | conda base나 venv의 python이 먼저 잡힘 → `conda deactivate` / `deactivate` 후 새 터미널에서 실행. launch가 시작할 때 경고를 출력함 |
| `place point … collides with <id>` | 놓을 자리에 다른 물체가 있음(안전 검사). 다른 위치를 말하거나 물체를 먼저 옮김. 영역 점이 그릇 위면 그릇 안에 놓음 |
| 빌드 중 exit 137 | 메모리 부족 → `--parallel-workers 2`, `MAKEFLAGS=-j4` |
| 시뮬이 안 뜸 / RViz가 바로 죽음 / `Publisher already registered for node name` / 팔이 혼자 움직임 | 이전 실행의 일부 프로세스가 남아 같은 도메인에서 충돌 → `ros2 run vla_bringup stop_vla.sh` 후 다시 실행 |
| `a previous VLA simulation is still running` | 위와 같음. 일부러 두 개를 띄울 때만 `VLA_ALLOW_RUNNING=1` |
| 마커가 전부 같은 ID로 보이거나 카메라 영상이 깜빡임 | 이전 Gazebo 서버가 남아 같은 토픽에 발행 → `stop_vla.sh` |
| `table not calibrated` | 마커 4개가 모두 보이지 않음. 팔이 가리면 executor가 관찰 자세로 돌아간 뒤 다시 시도 |
| 다른 터미널에서 노드가 안 보임 | `ROS_DOMAIN_ID`가 터미널마다 다름 |
| table 캘리브레이션에서 모든 점이 dropped | 초기 `marker_positions`가 3 cm 넘게 틀림 → `--max-drift 1`로 첫 회 실행 후 결과로 다시 실행 |
| wrist 캘리브레이션 종료 코드 2 | 잡음/놓침 구분 여유 부족 → 조명·카메라 각도 확인, 색 캘리브레이션 먼저 |

## 8-1. 로봇 모니터 (`src/fms/robot_monitor`)

관제 서버에서 로봇마다 배터리·위치·주행 상태를 계속 모아 내보냅니다. 로봇은 토픽만 내고, 모니터가 구독합니다.

```bash
colcon build --symlink-install --packages-select robot_monitor && source install/setup.bash
ros2 run robot_monitor monitor                         # 설정: src/fms/robot_monitor/config/robots.yaml
curl http://localhost:8090/api/robots                  # 전체 로봇 상태 (JSON)
curl -N http://localhost:8090/api/robots/stream        # 1초마다 실시간 (SSE)
ros2 topic echo /fms/robot_states                      # 같은 내용을 ROS 토픽으로
```

- 구독(로봇 namespace 아래): `battery/percent`, `battery/voltage`, `odom`, `tf`·`tf_static`(위치 = `map → base_footprint`), `navigate_to_pose/_action/status`
- 상태: `offline`(3초간 아무 메시지 없음) / `idle` / `navigating`. 배터리 20 % 미만이면 `battery.low = true`
- 위치는 지도(`map`)가 있어야 나옵니다(SLAM 또는 AMCL 실행 중). 로봇과 같은 `ROS_DOMAIN_ID`에서 실행합니다.

## 8-1-1. EMR 장소로 Pinky 이동 (`src/fms/test_waypoint`)

EMR 맵 화면에서 찍은 장소를 이름으로 골라 Pinky를 차례로 보냅니다. EMR에서 장소 좌표를 읽고(로그인 불필요), 로봇의 Nav2 웹서버(`:8080`)에 목표를 보냅니다.
ROS가 필요 없는 python3 스크립트라 이 PC나 로봇 어디서든 돌릴 수 있습니다.

로봇에 맵 파일이 없으면 EMR에서 꺼내 보냅니다. EMR이 저장한 이미지(픽셀 그대로)와 해상도·원점으로 map_server용 yaml+png를 만들므로 좌표가 EMR과 정확히 같습니다.
mode·thresh는 EMR에 없어서 Pinky 맵과 같은 값(trinary, 0.65/0.25)을 씁니다.

```bash
python3 ~/dev_ws/robot/src/fms/test_waypoint/emr_map_export.py 병원 ~/dev_ws/robot/maps   # → map_rev2.yaml + map_rev2.png
scp ~/dev_ws/robot/maps/map_rev2.yaml ~/dev_ws/robot/maps/map_rev2.png pinky@<로봇 IP>:~/maps/
```

```bash
# 로봇에서 (EMR에 올린 것과 같은 맵 파일로)
ros2 launch pinky_navigation web_nav2.launch.xml map:=<경로>/map_rev2.yaml
#   → 웹 화면(http://<로봇 IP>:8080)에서 초기 위치(2D Pose Estimate)를 먼저 잡는다

# 이 PC에서
cd ~/dev_ws/robot/src/fms/test_waypoint
python3 test_waypoint.py --list                                    # EMR 장소 목록
python3 test_waypoint.py 비품실 301호 --robot http://<로봇 IP>:8080 --dry-run   # 검사·계획만
python3 test_waypoint.py 비품실 301호 302호 간호사스테이션 --robot http://<로봇 IP>:8080
```

| 단계 | 동작 |
|---|---|
| 출발 전 | 이름이 EMR에 있는지, 한 맵에 있는지, **로봇 Nav2 맵이 EMR 맵과 같은지**(해상도·원점·크기), 로봇 위치가 잡혔는지 확인. 하나라도 아니면 움직이지 않음(종료 코드 2) |
| 출발 | 이동 계획을 보여 주고 `y`를 입력해야 출발 (`--yes`로 생략) |
| 장소마다 | 목표 전송 → 주행이 끝나면 현재 위치가 목표 0.35 m 안이면 도착 → 3초 머무름 |
| 실패 | 도착 못 하면 거기서 멈춤(`--continue-on-miss`로 계속). 120초 넘게 안 끝나거나 Ctrl+C면 **정지 명령** |

- 웹서버 `/api/goal`은 성공·실패를 알려 주지 않아 위치로 판정합니다. Nav2가 목표를 거부하면 제한 시간까지 기다린 뒤 정지합니다.
- 옵션: `--emr`(기본 `http://localhost:8000/api/v1`), `--robot`(기본 `http://192.168.4.1:8080`), `--arrive-tolerance-m`, `--timeout-s`, `--wait-s`, `--skip-map-check`(위험).

## 8-1-2. EMR 배송 실행기 (`src/fms/delivery_executor`, 2026-10-20 · 주행·수령 변경 2026-10-22)

EMR 웹 예약을 로봇에 전달하는 관제 PC 프로그램입니다(EMR 로드맵 2단계). 예약 시각이 지난 배송을 EMR에서 가져와(claim) 로봇을 보내고,
도착을 알린 뒤 수령을 기다렸다가 복귀시킵니다. 계약: `dev_ws/docs/api_contract_delivery_2026-10-20.md` 4장.

**2026-10-22부터 (사용자 결정)**
- 주행은 **팀원 Pinky API**(로봇 `:8080`, `POST /goto {dest}` → `GET /jobs/{id}`)로 합니다(`navigation: pinky_api`). ROS가 필요 없고, **인증 없이** 진행합니다(운영 전에 넣기). 분석: `dev_ws/docs/pinky_fms_api_review_2026-10-22.md`.
- 주행은 **비동기**입니다: 보내 놓고 반복마다 확인하며, **제한 시간이 없습니다**(`navigation_timeout_s: null`). **비품실 금지를 풀었습니다**(비품실 → `PHARMACY`, 복귀 간호사스테이션 → `START_A`).
- **수령 마커는 꺼 둡니다**(`receipt_markers: false`). 간호사·환자가 EMR 화면에서 "받았습니다"를 누르면, 실행기가 대기 중 2초마다 `/robot/me`를 보고 알아차립니다.
- 예전 방식(Nav2 직접 `navigation: ros`, 마커 `receipt_markers: true` + EMR `NURSE_RECEIPT_METHOD=marker`)은 설정으로 되살립니다.

```bash
# 1) EMR 장소·맵·로봇 화면 → 로봇 탭: 로봇 1호의 복귀 장소(예: 간호사스테이션) 지정, 키 발급 → 파일로 저장
mkdir -p ~/.config/delivery_executor && chmod 700 ~/.config/delivery_executor
nano ~/.config/delivery_executor/pinky_1.key && chmod 600 ~/.config/delivery_executor/pinky_1.key   # 키 한 줄
# 2) 설정 확인: src/fms/delivery_executor/config/executor.yaml
#    emr_robot_id, pinky_api 주소. 목적지는 EMR 장소의 '로봇 목적지'(robot_dest)를 쓴다 — 아래로 Pinky 목적지를 EMR 맵·장소로 가져오기
#    (팀원이 목적지를 바꾸면 다시 실행. 관리자 비밀번호는 EMR_PASSWORD 또는 입력)
python3 ~/dev_ws/emr/backend/scripts/import_pinky_dests.py --pinky http://192.168.129.122:8080 --home START_A --robot-id 1
curl http://192.168.129.122:8080/status      # 로봇 위치 추정(localized)·nav2_ready·idle 확인 (읽기만)
curl http://192.168.129.122:8080/dests       # 목적지 이름 (2026-10-22 /stops에서 바뀜)
# 3) 연결 점검 — 로봇을 움직이지 않음 (EMR 키·복귀 장소, Pinky 상태, 목적지 이름, 목적지별 경로 계산)
colcon build --symlink-install --packages-select delivery_executor && source install/setup.bash
ros2 run delivery_executor executor --check    # 끝에 "→ 배송을 맡을 수 있습니다"면 준비 완료
# 4) 실행 — ⚠️ 배송이 있으면 로봇이 실제로 움직입니다
ros2 run delivery_executor executor            # --config 다른.yaml, --robot pinky_1
# 5) 도착하면 간호사 화면의 도착 창(또는 배송 목록)에서 "받았습니다" → 실행기가 알아차리고 복귀
```

| 상황 | 동작 |
|---|---|
| 시작 | `/robot/me`로 키가 설정의 로봇 것인지, 복귀 장소 확인. 맡고 있던 배송이 있으면 그 단계부터 이어서. (`ros`면 로봇 /map = EMR 맵도 확인) |
| claim 전 | (`pinky_api`) `GET /status` — 위치 모름·Nav2 안 됨·다른 작업 중이면 맡지 않고 기다림 |
| 배송 | 3초마다 claim → 목적지 이름으로 `/goto` → **기다리지 않고** 반복마다 `/jobs/{id}` 확인(비동기, 제한 시간 없음) → 끝나면 도착 보고 → "받았습니다" 대기(2초마다 `/robot/me`) → 복귀도 같은 방식 |
| 실패 | Pinky 작업 실패(제한 시간을 정했으면 시간 초과도) → `navigation_failed`, 5분 미수령 → `not_received`, 금지 장소(2026-10-22 비품실 해제 — 지금 없음)·`dests`에 없는 장소·Pinky가 못 가는 곳 → `destination_blocked`(움직이지 않음), Pinky가 30초 넘게 다른 작업 중 → `robot_error`. 모두 EMR이 재고를 되돌리고 알림 |
| 복귀 실패 | 멈춤(다음 배송을 맡지 않음) — 로봇 위치 확인 후 다시 시작 |
| Ctrl+C | 실행기가 시작한 Pinky 작업을 `POST /cancel`로 멈춤(`ros`면 Nav2 목표 취소). 배송은 EMR에 남아 다음 시작 때 이어서(실패로 보고하지 않음) |

로봇 없이 시험: 가짜 Pinky API(단위 테스트 `test/test_pinky_api.py`와 같은 흉내 서버)에 `pinky_api` 주소를 돌려 실행기 전체를 확인(2026-10-22 수행 — 실제 EMR, 간호사 화면 "받았습니다"까지). 예전 방식은 EMR `backend/scripts/simulate_robot.py` 또는 도메인 77 가짜 Nav2(2026-10-20).

## 8-1-3. 간호사 따라가기 (선택 기능, `src/pinky_onboard/pinky_marker`, 2026-10-20)

간호사 신분증 마커(EMR에서 배정·인쇄한 0~49번)를 Pinky 카메라로 보고 그 간호사를 30 cm 거리로 따라갑니다. 배송과 별개 기능입니다.
팀원 시제품(`~/Downloads/macker`, 2026-10-12)을 정리한 것이고, **Pinky에서 돕니다**(Pi 카메라). 패키지 폴더를 Pinky 워크스페이스에 복사해 빌드합니다.

```bash
# PC → Pinky로 복사 후 Pinky에서 빌드
scp -r ~/dev_ws/robot/src/pinky_onboard/pinky_marker pinky@<로봇 IP>:~/pinky_ws/src/
colcon build --packages-select pinky_marker && source install/setup.bash     # Pinky에서
# config/nurses.yaml: 마커 번호 → 이름 (EMR 간호사 화면 배정과 같게)
ros2 launch pinky_marker follow.launch.py                                      # 카메라 + 따라가기 (LCD 영상 play_cam.py는 꺼 둘 것)
ros2 service call /nurse_follower/enable std_srvs/srv/SetBool "{data: false}"   # 끄기 / true면 켜기
ros2 topic echo /follow/state                                                  # WAITING · FOLLOWING · SHORT_LOSS · TARGET_LOST · NAV_BUSY · DISABLED
```

| 팀원 시제품과 다른 점 | 이유 |
|---|---|
| 따라가는 동안에만 `/cmd_vel`을 냄(멈출 때 정지 3번) | 시제품은 늘 20 Hz로 정지 명령을 내서 Nav2 주행을 막았다 |
| Nav2 주행 중이면 NAV_BUSY — 따라가지 않음 | 배송 실행기와 같이 켜져도 바퀴 명령이 부딪히지 않게 |
| 영상 구독 QoS reliable·최신 1장 (`image_qos`) | best-effort로는 이 PC에서 0.9 MB 영상이 60장 중 0장 도착(2026-10-20 측정) |
| 사전 DICT_4X4_250, 따라가기 대상은 0~49만 | 일회용 수령 마커(50~249)를 같은 카메라로 읽을 수 있게(따라가기는 무시) |
| `~/enable` 서비스, Ctrl+C·SIGTERM 직접 처리 | 켜고 끄기, launch·스크립트에서 띄워도 바로 멈추게 |

- 거리 추정은 초점 거리 500 px 가정(보정 전) — 실제 거리와 다를 수 있다. 카메라가 180° 돌아 달려 `invert_x: true`(팀원 확인).
- 시험(2026-10-20): 도메인 77 가짜 카메라 영상으로 따라가기·NAV_BUSY·끄기·놓침 확인. **Pi 카메라 노드(`camera`)는 Pinky에서만 확인 가능 — 미시험**.

## 8-2. 실물 팔 텔레오퍼레이션 (`vla_teleop`)

리더 팔로 팔로워 팔을 움직이며 그리퍼 끝 좌표를 보고 기준점을 기록하는 도구입니다. 설정(팔별 OpenRB 시리얼, 카메라, 안전 높이)은 `src/vla_planner_robot/vla_teleop/config/arms.yaml`에 있습니다.

```bash
ros2 run vla_teleop teleop scan                      # 모든 OpenRB: 역할·모터 ID·자세·에러·전압 (읽기만)
ros2 run vla_teleop teleop start --arm right         # 에러 확인 → 팔로워 → 리더 자세로 10초 정렬 → 리더 → 좌표 뷰어
ros2 run vla_teleop teleop here blue_round           # 지금 좌표·기울기·탑뷰/손목 화면 기록 (세션 폴더 points.csv)
ros2 run vla_teleop teleop stop                      # 리더로 팔을 접은 뒤. 접히지 않았으면 거부(--force로 강제)
ros2 run vla_teleop teleop tap --x 0.190 --y -0.081 --z -0.04 --record   # 리더 없이 팔로워만: 위로 접근 → 내려 찍기 → 올라와 접힌 자세로 복귀 → 종료. 안전 높이 아래는 거부, --dry-run은 계획만, --record는 세션 폴더에 top.mp4·wrist.mp4
ros2 run vla_teleop teleop pick --x 0.244 --y 0.004 --z -0.038 --place-x 0.200 --place-y 0.097 --place-z -0.028 --record   # 그리퍼 열기 → 내려가 집기 → 들어 옮기기 → 놓기 → 복귀. 그리퍼 열림/닫힘 값은 config/arms.yaml
ros2 run vla_teleop teleop camera --tune                # 탑뷰·손목 카메라 노출/화이트밸런스를 측정해 고정값으로 저장(calib/camera_settings.yaml). 평소 조명에서 한 번
ros2 run vla_teleop teleop camera                       # 저장한 고정값 다시 적용(카메라를 다시 꽂으면 UVC가 값을 잊음). start/tap/pick은 자동 적용
ros2 run vla_teleop teleop clear-errors --arm right  # 모터 LED가 빨갛게 깜빡일 때(과부하 등). 팔이 멈춘 상태에서
ros2 run vla_teleop teleop status
```

- 팔로워는 `init_position:=false`로 켜서 저절로 움직이지 않고, 리더를 켜기 전에 리더 자세로 천천히 맞춥니다(켜자마자 튀는 동작 방지). ROBOTIS `omx_ai.launch.py`는 팔을 위로 곧게 펴므로 쓰지 않습니다.
- 안전 범위: 그리퍼 끝 z ≥ −0.04 m, 끝까지 뻗지 않기(x ≤ 0.24 m 권장). 뷰어는 z가 안전선 아래면 빨간 글씨로 표시합니다.
- 오른쪽 팔 = 팔로워 9C4E6E48 + 리더 0DE4DEF8 + 손목 카메라(USB 포트 10.1.4). `ttyACM` 번호는 다시 꽂으면 바뀌므로 시리얼로 찾습니다.
- 도메인은 77로 분리해서 실행합니다. 로그와 기록은 `~/.cache/vla_teleop/<시각>/`에 남습니다.

## 9. 실물로 옮길 때 (TODO)

- 마커: `DICT_5X5_100` ID 0–3으로 출력 (다른 딕셔너리면 `aruco_dictionary`와 `colors --aruco-dictionary`도 변경), 크기, **마커 중심끼리의 실측 거리**(자로 측정) → `marker_positions` 초기값. 로봇 기준 위치는 `vla_calibration table`이 구함
- 카메라: 장치(`/dev/video*`), 해상도 → `vla_calibration intrinsics`
- 블록 크기와 색 → `block_height`, `vla_calibration colors`
- 손목 카메라 장착 → `vla_calibration wrist` (없으면 `wrist_check: false`)
- OMX-F 포트(U2D2) → `ros2 launch open_manipulator_bringup omx_f.launch.py`
- 실물에서는 `executor.yaml`의 `use_sim_time: false`로 바꾼 설정 파일을 사용
