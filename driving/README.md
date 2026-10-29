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
| `line_follow.py` | IR 3채널 라인트레이싱 (PD 조향, 튀는 값 중앙값 필터, 바닥 값은 채널마다 최근 2초 최댓값으로 따라감). 흰색·바닥 값은 **로봇별 보정 파일** `~/.config/pinky/ir_cal.json` 을 읽음 (로봇마다 센서 감도가 달라 고정값 안 씀) |
| `lane_drive.py` | 교행 복도 단계 실행: 테이프 따라가기 / 제자리 회전 / 테이프 없는 차선 바꾸기, 구간별 시간 기록. 테이프를 놓치면 마지막 본 쪽으로 돌며 0.8초 다시 찾음. 제자리 회전 최대 1.5 rad/s, 앞뒤 AMCL 대기 0.3 s (10-29, 90° 7.5 → 3.6 s) |
| `edge_run.py` | 엣지 시간 측정: 영역 안 모든 방향 엣지를 덮는 경로를 짜서 엣지마다 실제 주행 방식으로 달리며 회전·이동 시간을 따로 기록 (`edge_logs/`). line = 테이프, wall = 벽 따라가기(벽 쪽은 그래프의 wall 선분으로), nav·벽 없는 문 앞 = AMCL 축선 직진 5 cm/s (Nav2 는 `--nav2`). `--new-only` / `--min-n 2` 로 덜 잰 엣지만, `--done-log <기록>` 으로 끊긴 한 바퀴 이어 돌기, `--skip a-b`, `--pre rotate:90 straight:3` 로 자리 맞추기. 배터리는 기본으로 안 봄 (`--batt-stop`) |
| `edge_costs.py` | 측정 기록 → 방향별 엣지 이동 시간(중앙값) + 회전 시간 식. `--write` 로 `graph/edge_times.yaml` (FMS 경로 계획용). `--rot` = 회전 식은 지정한 기록만으로 (회전 속도를 바꾼 뒤) |
| `rot_test.py` | 제자리 회전 시간 재기 (`--wmax`, `--settle` 로 설정 비교) |
| `ir_sweep.py` | IR 보정: 제자리 ±30° 회전하며 센서별 흰색·바닥 값 측정. **`--amp 45 --save`** = 이 로봇의 보정 파일 만들기 (테이프 위에 차선 방향으로 놓고 실행, 로봇 바꿀 때마다 한 번) |
| `ir_watch.sh` (+ `ir_watch.py`) | PC 에서 실행하면 로봇 IR 3채널 값을 실시간으로 보여 줌 (막대, 최소/최대, 채널 차이). IR 노드가 없으면 띄움 |
| `precise_dock.py`, `aruco_ref.py`, `dock_test.sh` | 카메라 ArUco 정밀 주차 (1 cm · 3°), 기준 자세 가르치기, 반복 시험 |
| `set_pose.py`, `global_find.py`, `now_pose.py`, `scan_fit.py` | AMCL 시작 위치 넣기와 스캔 확인, 스캔만으로 위치 찾기 |
| `make_drawn_map.py`, `real_walls.yaml` 외 지도 스크립트 | 실측 벽으로 지도(map_drawn) 만들기, SLAM 맵 정합·보정·검증 |
| `coords.py`, `points.yaml`, `diagram_walls.yaml` | 좌표 변환, 바닥 표시점 A~G, 그림 기준 벽 |
| `run_route.py`, `follow_path_client.py`, `battery.sh` | 초기 FollowPath 시험, 배터리 보기 |

## graph/ — 주행 그래프

| 파일 | 하는 일 |
|---|---|
| `graph_spec.yaml` | 사람·편집기가 고치는 원본 (차선, 갈림목, 노드, 엣지). `lane_skip:` = 못 가는 차선 노드 (지금 T2_20 — 콘센트 자리) |
| `build_graph.py` | `graph_spec.yaml` → `graph.yaml` + `graph.png`. 차선 노드·차선 엣지(line)·갈림목 transfer(경계점↔차선, 차선↔차선)를 자동으로 만들고 엣지마다 벽 여유(빈 로봇 Ø11 / 그릇 Ø14)를 계산 |
| `graph.yaml`, `graph.png` | 만들어진 그래프 (API 와 FMS 가 읽음 — FMS 는 복사하지 말고 이 파일을 가리킬 것). 그림의 목적지에 방 번호(101~108호·수술실·약제실) |
| `edge_times.yaml` | **실측 엣지 시간** (10-27~29, pinky_6364·ee3a): 방향별 엣지 142개 전부(엣지마다 3~7번)의 이동 시간 중앙값·최소·최대·측정 횟수 + 회전 시간 식 (1.5 rad/s 회전 기준 ≈ 1.9 s + 1.8 s/90°: 90° 3.7 s, 180° 5.2 s). `tools/edge_costs.py --write` 로 만듦 |
| `graph_editor.py`, `editor.html` | 브라우저 편집기 (`python3 graph/graph_editor.py` → http://localhost:8765) |

## maps/ · launch/ · config/

- `maps/map_drawn.*` — 실측 벽으로 그린 지도 (AMCL·Nav2·스캔 확인용, 맵 m × 100 = 그림 cm). `map_rev3*` 는 SLAM 원본·보정본 (지도 도구용 참고)
- `launch/nav2_followpath.launch.py`, `config/nav2_params_followpath.yaml` — `pinky-nav2.service` 가 띄우는 Nav2 (map_server + amcl + controller + velocity_smoother, 플래너 없음)

## 로봇에 배포

코드끼리 상대 경로(`../graph`, `../maps`, `../tools`)로 찾고 서비스는 `~/pinky_map_rev3/` 를 가리키므로,
이 `driving/` 폴더를 로봇의 `~/pinky_map_rev3/` 로 그대로 복사한 뒤 `api/install_service.sh` 를 실행한다.

IR 노드(`pinky_sensor_adc main_node`, `/ir_sensor/range`)는 아직 자동 실행에 없어서 라인트레이싱 도구를 쓸 때 직접 띄운다.
