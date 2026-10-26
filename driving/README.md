# Pinky 주행 (driving)

Pinky Pro 가 병원 아레나(210 × 200 cm)를 주행 그래프대로 달리게 하는 코드. 로봇 위에서 도는 REST API 와 주행·지도 도구.

좌표는 그림 cm (왼쪽 아래 원점, x 오른쪽, y 위), 위치 = 라이다 중심, 방향 0° = +x · 90° = +y.

## api/ — 로봇 REST API (로봇에서 실행, 포트 8080)

| 파일 | 하는 일 |
|---|---|
| `pinky_api.py` | Flask 서버. `/status` `/dests` `/plan` `/goto` `/cancel` `/jobs` `/set_pose` `/notify`. 경로를 구간으로 나눠 Nav2 FollowPath · 협로 벽 따라가기 · 회전 · 정밀 주차로 실행하고, 약제실 도착을 관제 PC 에 알림 |
| `graph_route.py` | 주행 그래프에서 지금 자리 → 목적지 경로를 구간 목록으로 (ROS 없이 PC 에서도 돎) |
| `openapi.py`, `API.md` | API 명세(`/docs` Swagger)와 사용법 |
| `*.service`, `install_service.sh`, `run_ros.sh`, `run_api.sh`, `ros_env.sh` | 부팅 때 bringup · Nav2 · API 자동 실행 (사용자 systemd 서비스) |

## tools/ — 주행 · 위치 · 지도 도구

| 파일 | 하는 일 |
|---|---|
| `corridor_drive.py` | 협로 라이다 벽 따라가기 (벽 없는 구간은 AMCL), 접촉 검사, `--stop-on-tape` 로 협로에서 나올 때 IR 로 차선 테이프 위에 멈춤 |
| `line_follow.py` | IR 3채널 라인트레이싱 (센서별 보정, PD 조향, 튀는 값 중앙값 필터) |
| `lane_drive.py` | 교행 복도 단계 실행: 테이프 따라가기 / 제자리 회전 / 테이프 없는 차선 바꾸기, 구간별 시간 기록 |
| `ir_sweep.py` | IR 보정: 제자리 ±30° 회전하며 센서별 흰색·바닥 값 측정 |
| `precise_dock.py`, `aruco_ref.py`, `dock_test.sh` | 카메라 ArUco 정밀 주차 (1 cm · 3°), 기준 자세 가르치기, 반복 시험 |
| `set_pose.py`, `global_find.py`, `now_pose.py`, `scan_fit.py` | AMCL 시작 위치 넣기와 스캔 확인, 스캔만으로 위치 찾기 |
| `make_drawn_map.py`, `real_walls.yaml` 외 지도 스크립트 | 실측 벽으로 지도(map_drawn) 만들기, SLAM 맵 정합·보정·검증 |
| `coords.py`, `points.yaml`, `diagram_walls.yaml` | 좌표 변환, 바닥 표시점 A~G, 그림 기준 벽 |
| `run_route.py`, `follow_path_client.py`, `battery.sh` | 초기 FollowPath 시험, 배터리 보기 |

## 같이 있어야 하는 것 (이 폴더에 없음)

원래 번들(`~/pinky_map_rev3/`)에서는 `api/`, `tools/` 옆에 아래 폴더가 있어야 돈다.

- `graph/` (`graph.yaml`, `graph_spec.yaml`) — `graph_route.py` 가 읽는 주행 그래프
- `maps/` (`map_drawn.*`) — Nav2 · `scan_fit.py` · `set_pose.py` 가 쓰는 지도
- `launch/nav2_followpath.launch.py`, `config/nav2_params_followpath.yaml` — `pinky-nav2.service` 가 띄우는 Nav2

IR 노드(`pinky_sensor_adc main_node`, `/ir_sensor/range`)는 아직 자동 실행에 없어서 라인트레이싱 도구를 쓸 때 직접 띄운다.
