# dev_ws 서버 안내 — 병원 비품·배송 로봇 서버 (EMR 웹 + 로봇팔 + 로컬 LLM)

> 2026-10-20 저장소 README를 팀 저장소 소개(`kernel-robot-repo-2`)로 바꾸면서 기존 README 내용을 여기로 옮겼다.

PC 한 대가 서버 역할을 한다. 간호사는 EMR 웹에서 비품과 배송을 관리하고, Pinky Pro 로봇이 배송하며,
OMX-F 로봇팔이 자연어 명령으로 물건을 집어 옮긴다(시뮬레이션 단계). LLM은 이 PC의 Ollama가 맡는다.

```
                     ┌──────────────── 이 PC (fastcamp1-OMEN) ─────────────────┐
브라우저 ───http───▶ │ emr/      web :5173 ─▶ api :8000 ─▶ db :5432  (docker)    │
(간호사)             │                                                          │
팀원 FMS ──http──▶  │           (api :8000 로봇 API, 로봇별 키)                │
(Pinky 주행)         │ robot/    vla_* OMX-F 시뮬·실물 ─▶ Ollama :11434 (gemma4)   │
                     │ ollama_ws/ (예정) 다른 모델을 Ollama 호환 API로 제공        │
                     └──────────────────────────────────────────────────────────┘
```

## 폴더

| 폴더 | 무엇 | 자세히 |
|---|---|---|
| `emr/` | 간호사용 비품·배송 웹. 로그인, 비품 재고, 배송 예약, 맵·장소·로봇 관리, 재고 부족 실시간 알림, 간호사 ArUco 마커 인쇄, 로봇 API 키·수령 확인 | [emr/README.md](../emr/README.md) · [emr/CLAUDE.md](../emr/CLAUDE.md) |
| `robot/` | ROS 2 워크스페이스. OMX-F 자연어 pick & place(`src/vla_planner_robot`), Pinky Pro AMR(`src/pinky_pro`, 시뮬용), ROBOTIS upstream. 관제·주행 코드는 2026-10-23 삭제(팀원 FMS 담당) | [robot/README.md](../robot/README.md) · [robot/CLAUDE.md](../robot/CLAUDE.md) |
| `ollama_ws/` | 예정. Ollama에 없는 다른 모델을 Ollama 호환 인터페이스로 제공할 작업 폴더 (아직 비어 있음) | — |
| `docs/` | 서버 전체 현황 보고서 | [docs/server_report_2026-10-19.md](server_report_2026-10-19.md) |

## 사전 준비 (이 PC에는 이미 설치되어 있음)

- Ubuntu 24.04, Docker 29 + Compose v5, ROS 2 Jazzy(`/opt/ros/jazzy`), MoveIt 2 · Gazebo Harmonic (robot/README 0장)
- Ollama(systemd로 자동 기동) + 모델 `gemma4:e2b` — 없으면 `ollama pull gemma4:e2b`
- `~/dev_ws/robot`은 빌드되어 있다(`install/`). 다시 빌드할 때는 robot/README 1장 — **venv·conda를 끄고** `--parallel-workers 2`

## 실행

### 1) EMR 웹 (상시 기동)

```bash
cd ~/dev_ws/emr
cp .env.example .env              # 처음 한 번. JWT_SECRET은 긴 무작위 문자열로, 첫 기동 후 SEED=0
docker compose up -d --build      # 이후에는 docker compose up -d
```

- 웹 http://localhost:5173 — 다른 PC에서는 `http://<이 PC IP>:5173` (IP는 `hostname -I`)
- API 문서 http://localhost:8000/docs
- 계정: `N001`(관리자) · `N002`(간호사) / 비밀번호 `nurse1234`
- 중지 `docker compose down`, DB까지 초기화 `docker compose down -v`

### 2) OMX-F 로봇팔 시뮬레이션 (필요할 때만)

```bash
ros2 run vla_bringup stop_vla.sh               # 항상 먼저 (이전 실행 정리)
ros2 launch vla_bringup sim_vla.launch.py      # 2팔은 dual_sim_vla.launch.py
ros2 run vla_planner cli                       # > 빨간 블록을 가운데로 옮겨
```

Gazebo · MoveIt · Ollama가 함께 돌아 메모리(15GB)를 많이 쓴다. 끝나면 `stop_vla.sh`로 내린다.

## 포트 한눈에

| 포트 | 서비스 | 어디서 |
|---|---|---|
| 5173 | EMR 웹 (Vite) | docker `emr-web-1` |
| 8000 | EMR API (FastAPI, `/docs`) | docker `emr-api-1` |
| 5432 | PostgreSQL 16 | docker `emr-db-1` |
| 11434 | Ollama (이 PC 안에서만) | systemd `ollama.service` |
| 8080 | 팀원 Pinky API | **로봇** 쪽 |

## 지금 상태와 다음 (2026-10-19)

할 일은 **웹(EMR) · 로봇(Pinky AMR·관제) · OMX(로봇팔)** 세 갈래로 나눠 진행한다. 목록은 [docs/server_report_2026-10-19.md](server_report_2026-10-19.md) 6장.

- **웹(EMR)**: 맵 업로드·장소 찍기(1단계)까지 완료. 다음은 배송 배정·진행(2단계) — 로봇 쪽과 API 계약(필드·주기·오류 코드)부터 맞춘다. 그 전에 운영 준비(DB 포트 제한, 프론트 운영 이미지 `/api` 프록시, https).
- **로봇(Pinky · 관제)**: 2026-10-23부터 팀원 FMS가 주행하고 EMR 로봇 API로 상태·도착을 보고한다. 우리 관제 모니터·배송 실행기는 삭제했다.
- **OMX(로봇팔)**: 시뮬에서 1팔·2팔 검증 완료. 실물 캘리브레이션(`calib/`)과 2팔 실물(U2D2 2개) 전. EMR 적재 연동은 "나중" 단계. `ollama_ws`의 Ollama 호환 서버가 생기면 플래너 LLM을 교체한다.

## 문제가 생기면

| 증상 | 보기 |
|---|---|
| 다른 PC에서 "서버에 연결할 수 없습니다" | `.env`의 `VITE_API_URL=/api/v1` 확인 → emr/README "다른 PC에서 접속" |
| `No module named 'catkin_pkg'` / `rclpy._rclpy_pybind11` | venv·conda가 켜져 있음 → `deactivate`, `conda deactivate` → robot/README 8장 |
| 빌드 중 exit 137 | 메모리 부족 → `MAKEFLAGS=-j4 colcon build --parallel-workers 2` |
| 시뮬이 안 뜨거나 팔이 혼자 움직임 | 이전 실행 잔재 → `ros2 run vla_bringup stop_vla.sh` |
| 로봇 위치(`pose`)가 null | 로봇에서 SLAM/Nav2가 돌아 `map→base_footprint` TF가 있는지 |
