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

그때 만든 도구(`vla_calibration table --arm`, `wrist`)는 2026-10-23에 지웠고(git `340a397`), 결과 파일 `calib_sim/arm_poses.yaml`·`wrist_dual.yaml`은 그대로 씁니다.

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
(cd vla_planner && python3 -m pytest -q test)                                              # 계획 해석·검증, 2팔 (26)
PYTHONPATH=vla_perception:$PYTHONPATH python3 -m pytest -q vla_perception/test               # ArUco 딕셔너리·검출 (4)
PYTHONPATH=vla_executor:vla_perception:$PYTHONPATH python3 -m pytest -q vla_executor/test   # 손목 집기 판정·정렬 (7)
PYTHONPATH=vla_calibration:vla_executor:vla_perception:$PYTHONPATH \
  python3 -m pytest -q vla_calibration/test                                                # top_camera·wrist_refine (8)
(cd vla_teleop && PYTHONPATH=.:$PYTHONPATH python3 -m pytest -q test)                       # 텔레옵·카메라 고정 (6)
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

실물 오른팔용 도구 두 개만 있습니다. 결과는 `~/dev_ws/robot/calib/`에 저장되고 `real_vla.launch.py`가 읽습니다.

| 도구 | 하는 일 | 결과 |
|---|---|---|
| `top_camera capture\|intrinsics\|points\|board\|homography` | 탑뷰 카메라 내부 파라미터(체커보드 9x6 또는 ChArUco 7x5), 테이블 호모그래피(픽셀 → 팔 x, y)와 판 높이 | `top_intrinsics.yaml`, `top_homography.yaml` |
| `wrist_refine measure\|fit` | 초록 2.5 cm 정육면체 위에서 손목 카메라로 실제 위치·높이를 재고(블록 크기 → 높이), 탑뷰 좌표(affine)와 판 높이(plane)를 다시 맞춤 | `wrist_points.csv` → `top_homography.yaml` (이전 파일은 날짜 붙여 보관) |

인쇄물·순서는 `docs/calibration/README.md`, 2026-10-22 실물 시험과 남은 문제는 `docs/real_tests/2026-10-22_command/failures.md`에 있습니다.

**시뮬:** 예전 ROS 토픽 기반 도구(`intrinsics`, `colors`, `table`, `wrist`)는 2026-10-23에 지웠습니다(git `340a397`). 그 결과 `calib_sim/`(camera_info·colors·table·wrist)는 그대로 쓸 수 있습니다.

```bash
ros2 launch vla_bringup sim_vla.launch.py calib_dir:=~/dev_ws/robot/calib_sim   # 시뮬 결과 적용
```

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

## 8-1. (삭제됨) 로봇 모니터·Pinky 이동 시험·배송 실행기·간호사 따라가기

`src/fms`(`robot_monitor`, `test_waypoint`, `delivery_executor`)와 `src/pinky_onboard`(`pinky_marker`), `maps/`는 2026-10-23에 지웠습니다. Pinky 주행과 로봇 상태 보고는 팀원 FMS가 맡고, EMR은 배송 미션만 만듭니다. 코드가 다시 필요하면 git 기록(커밋 `340a397`)에서 꺼내면 됩니다.

## 8-2. 실물 팔 텔레오퍼레이션 (`vla_teleop`)

리더 팔로 팔로워 팔을 움직이며 그리퍼 끝 좌표를 보고 기준점을 기록하는 도구입니다. 설정(팔별 OpenRB 시리얼, 카메라, 안전 높이)은 `src/vla_planner_robot/vla_teleop/config/arms.yaml`에 있습니다.

```bash
ros2 run vla_teleop teleop scan                      # 모든 OpenRB: 역할·모터 ID·자세·에러·전압 (읽기만)
ros2 run vla_teleop teleop start --arm right         # 에러 확인 → 팔로워 → 리더 자세로 10초 정렬 → 리더 → 좌표 뷰어
ros2 run vla_teleop teleop here blue_round           # 지금 좌표·기울기·탑뷰/손목 화면 기록 (세션 폴더 points.csv)
ros2 run vla_teleop teleop stop                      # 리더로 팔을 접은 뒤. 접히지 않았으면 거부(--force로 강제)
ros2 run vla_teleop teleop camera --tune                # 탑뷰·손목 카메라 노출/화이트밸런스를 측정해 고정값으로 저장(calib/camera_settings.yaml). 평소 조명에서 한 번
ros2 run vla_teleop teleop camera                       # 저장한 고정값 다시 적용(카메라를 다시 꽂으면 UVC가 값을 잊음). start와 real_vla는 자동 적용
ros2 run vla_teleop teleop clear-errors --arm right  # 모터 LED가 빨갛게 깜빡일 때(과부하 등). 팔이 멈춘 상태에서
ros2 run vla_teleop teleop status
```

- 팔로워는 `init_position:=false`로 켜서 저절로 움직이지 않고, 리더를 켜기 전에 리더 자세로 천천히 맞춥니다(켜자마자 튀는 동작 방지). ROBOTIS `omx_ai.launch.py`는 팔을 위로 곧게 펴므로 쓰지 않습니다.
- 안전 범위: 그리퍼 끝 z ≥ −0.04 m, 끝까지 뻗지 않기(x ≤ 0.24 m 권장). 뷰어는 z가 안전선 아래면 빨간 글씨로 표시합니다.
- 오른쪽 팔 = 팔로워 9C4E6E48 + 리더 0DE4DEF8 + 손목 카메라(USB 포트 10.1.4). `ttyACM` 번호는 다시 꽂으면 바뀌므로 시리얼로 찾습니다.
- 도메인은 77로 분리해서 실행합니다. 로그와 기록은 `~/.cache/vla_teleop/<시각>/`에 남습니다.

## 9. 실물 오른팔로 실행

```bash
ros2 run vla_bringup stop_vla.sh                 # 남은 실행·텔레옵 정리 (팔은 접힌 자세로)
ros2 launch vla_bringup real_vla.launch.py       # 카메라 2대 + 팔로워 + 비전(calib/) + 실행기(직접 구동) + 플래너, 도메인은 터미널 설정대로
ros2 run vla_planner cli                         # 다른 터미널: "파랑 블록을 초록 블록에 쌓아"
```

- 설정: `perception_real.yaml`, `executor_real.yaml`(`motion_backend: direct`, 판 높이 `surface_plane`, 집기 높이, 그리퍼), `planner_real.yaml`.
- 2026-10-23 현재 집기는 실물에서 성공하지 못했습니다. 탑뷰 좌표가 x로 1.5~3 cm 틀리고 팔이 멀리 뻗을수록 처집니다. `wrist_refine`으로 재보정한 뒤 다시 시험합니다(`docs/real_tests/2026-10-22_command/failures.md`).
