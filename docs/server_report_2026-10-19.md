# dev_ws 서버 현황 보고서

- 작성일: 2026-10-19
- 대상: `/home/fastcamp1/dev_ws` (폴더 `emr/`, `robot/`, `ollama_ws/`) 와 이를 올린 PC 한 대
- 방법: 파일·설정·로그 읽기와 읽기 전용 명령만 사용(부록). 컨테이너·ROS·파일은 바꾸지 않았다
- 독자: 이 서버를 이어받아 작업할 팀원(웹·로봇)과 Claude Code 세션

## 1. 요약

1. 이 PC 한 대가 **EMR 웹(상시 기동) + 로봇 관제 모니터(필요 시) + OMX-F 로봇팔 시뮬(필요 시) + Ollama(상시)** 를 같이 맡는다.
2. EMR은 Docker 3개 컨테이너로 정상 기동 중이고(API 24경로, DB 마이그레이션 0006까지 적용), 로드맵 1단계(맵 업로드·장소 찍기)가 끝났다.
3. 로봇 워크스페이스는 31개 패키지가 빌드되어 있으나 지금은 아무 노드도 돌지 않는다. 실물 캘리브레이션은 아직 없다.
4. **EMR과 로봇 사이 코드 연동은 0건**이다. EMR은 로봇용 API 1개와 로봇별 키 발급만 제공하고, 로봇 쪽에는 EMR을 부르는 코드가 없다. 2단계 전에 API 계약 문서가 필요하다.
5. 바로 처리할 위험 두 가지: `.bashrc`가 전역 export한 Gemini **API 키가 colcon 로그·build 파일 78개에 기록**되어 있고, Postgres(5432)·Jupyter(8888)가 **외부에 열려** 있다.
6. `ollama_ws/`는 비어 있다. 다른 모델을 Ollama 호환 인터페이스로 제공할 예정 폴더다(사용자 확인).
7. 할 일은 6장에서 **웹(EMR) · 로봇(Pinky AMR·관제) · OMX(로봇팔)** 세 갈래로 나눴고, 세 갈래가 먼저 맞출 API 계약 항목을 6.4에 모았다.

## 2. 서버 사양·실행 상태

### 2.1 호스트

| 항목 | 값 |
|---|---|
| 호스트명 / OS | `fastcamp1-OMEN` / Ubuntu 24.04.5 LTS, 커널 7.0.0-38 |
| CPU / RAM / swap | 24코어 / 15GB(사용 9GB) / 4GB(사용 2.9GB) — **메모리 압박** |
| GPU | NVIDIA RTX 5080 Laptop 16GB (드라이버 580) |
| 디스크 | 468GB 중 257GB 사용, 187GB 여유 |
| LAN IP (바뀔 수 있음) | 192.168.129.135 |
| ROS 2 | Jazzy (`/opt/ros/jazzy`) |
| Docker | 29.9.0, Compose v5.6.0 |
| Ollama | 0.40.1, systemd 서비스, `127.0.0.1:11434`, 모델 `gemma4:e2b`(4.6GB) |
| Python | `/usr/bin/python3` 3.12.3. 단, 셸 기본은 anaconda3 python(`~/.bashrc` conda init) |

### 2.2 지금 돌아가는 것

| 서비스 | 상태 | 포트 | 확인 |
|---|---|---|---|
| `emr-db-1` (postgres:16-alpine) | Up 3일, healthy | 5432 (`0.0.0.0`) | — |
| `emr-api-1` (emr-api, uvicorn --reload) | Up 2시간 | 8000 | `GET /docs` 200, openapi "EMR Supply API 0.1.0", 24 paths |
| `emr-web-1` (emr-web, Vite dev) | Up 4시간 | 5173 | `GET /` 200 |
| `ollama.service` | active | 11434 (로컬만) | `/api/tags` → `gemma4:e2b` |
| robot_monitor | **미기동** | 8090 | 연결 안 됨 |
| ROS 2 노드 | **없음** (ros2 daemon만) | — | `ros2 node list` 비어 있음 |
| 그 밖에 | SSH 22, Jupyter 8888(`0.0.0.0`), CUPS 631(로컬) | | |

EMR DB 현재 데이터(2026-10-19): 간호사 2, 비품 9, 맵 3, 장소 4, 로봇 4, 배송 2(품목 2). 마이그레이션 `0006_map_image`.
Docker 이미지: emr-api 366MB, emr-web 626MB, postgres 420MB. 볼륨 `emr_pgdata`.

### 2.3 셸 환경 (주의)

`~/.bashrc`가 다음을 **전역으로** 실행한다: `source /opt/ros/jazzy/setup.bash`, `source ~/doosan_ws/install/setup.bash`, conda init(base 자동 활성화).
그래서 모든 터미널에 doosan 워크스페이스 경로와 anaconda python이 먼저 잡힌다. `robot/CLAUDE.md`의 "`deactivate`·`conda deactivate` 후 `/usr/bin/python3`" 규칙은 이 때문이다.
`~/.bashrc`는 Gemini API 키도 전역 export해서, colcon 빌드 로그(`robot/log/*/events.log`)와 `robot/build/*/colcon_command_prefix_*.env`에 키가 그대로 찍힌다(5장 위험 1).

홈에는 이 워크스페이스와 무관한 `doosan_ws`, `il_ws`, `yolo_ws`, `isaac`, `main_project`, `robot_barista_-team_01` 등이 더 있고, `~/pinky_pro/`는 `robot/src/pinky_pro`와 **같은 커밋(014a09f)의 중복 colcon 워크스페이스**다.

## 3. 폴더별 구성

### 3.1 `emr/` — 병원 비품·배송 웹

| 항목 | 내용 |
|---|---|
| 백엔드 | FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16, pydantic-settings, structlog, PyJWT, bcrypt. 계층 `api → services → repositories → models` |
| 프론트 | React 19 + Vite 8 + TypeScript + TanStack Query 5 + react-router 8 + Tailwind 4, oxlint |
| 실행 | `docker-compose.yml` 하나로 db + api + web. api는 `backend/`를 마운트해 `--reload`, web은 Vite dev 서버(`target: dev`) |
| 마이그레이션 | `0001_baseline`(옛 0001~0014 통합) · 0002 nurse_role · 0003 nurse_aruco_marker · 0004 supply_low_stock_threshold · 0005 delivery_receipt · 0006 map_image — DB도 0006 |
| 테스트 | `tests/test_api/` 11파일(DB 필요, `TEST_DATABASE_URL` 없으면 skip) + `tests/test_services/` 4파일 — 케이스 81개(2026-10-19 수령 완료 알림 추가 후, 모두 통과) |
| 문서 | `CLAUDE.md`(규칙·결정·로드맵·열린 항목), `README.md`, `backend/REVIEW.md`(검토 필요 3건) |
| 진행 | 로드맵 1단계 완료. 2단계 배송 배정·진행(`reserved → dispatched → arrived → received / failed`)은 **로봇 쪽과 API 계약 후** 시작 |

**API (모두 `/api/v1` 아래, 24경로)**

| 인증 | 엔드포인트 |
|---|---|
| 없음 | `POST /auth/login` · `GET /maps`, `/maps/{id}`, `/maps/{id}/image` · `GET /locations`, `/locations/{id}` · `GET /robots`, `/robots/{id}` · `GET /health`(스키마 밖, DB 미확인) |
| 간호사 JWT(8시간) | `GET /auth/me` · `POST /auth/password` · `supplies` GET/POST/PATCH/DELETE(soft) · `GET /nurses`, `/nurses/{id}` · `deliveries` POST / GET(본인만) / GET {id} / PATCH / POST {id}/cancel (reserved만) · `GET /notifications/low-stock` · `GET /notifications/stream`(SSE, 25초 ping, 600초마다 서버가 닫음) |
| 관리자 | `nurses` POST/PATCH/DELETE, `POST /nurses/{id}/password-reset` · `maps` POST/PATCH/DELETE, `POST /maps/upload`, `PUT /maps/{id}/files` · `locations` POST/PATCH/DELETE · `robots` POST/PATCH/DELETE, `POST`/`DELETE /robots/{id}/api-key` |
| 로봇 키(`X-Robot-Api-Key`) | `POST /robot/deliveries/{id}/receipt` `{aruco_marker_id}` |
| **없음(아직)** | 관리자가 전체 배송을 보는 API, 로봇이 배송 id를 받는 API(claim·목록), 로봇 상태 보고 API |

**데이터** (7개 테이블, 상태값은 varchar + CHECK): `nurses`(employee_no, role admin|nurse, aruco_marker_id 0~49 unique) · `supplies`(code, stock_qty=예약 가능 수량, low_stock_threshold_qty, expiry_date, soft delete) · `maps`(resolution_m_per_pixel, origin_x/y/yaw, image_png bytea) · `locations`(map_x/y/yaw_m 셋이 함께, map_id) · `robots`(robot_type manipulator|amr, status idle|delivering|charging|maintenance(가정값), api_key_hash sha256) · `deliveries`(nurse_id, destination_location_id, scheduled_at, status reserved|cancelled|received, received_at/by_nurse/by_robot) · `delivery_items`.

**프론트**: 페이지 Login · Deliveries · MapView · Supplies · Nurses · Sites(장소·로봇·맵 업로드) · Password. 토큰은 localStorage `emr_token`, 401이면 로그아웃. 알림은 EventSource 대신 fetch 스트림으로 SSE를 읽고(토큰을 URL에 넣지 않으려고) 1·3·10·30초 간격 재연결.

### 3.2 `robot/` — ROS 2 워크스페이스

| 묶음 | 패키지 | 역할 | 빌드 |
|---|---|---|---|
| `src/fms/robot_monitor` (우리) | 1 | 관제 서버용 로봇 모니터. 로봇별 namespace의 `battery/percent·voltage`, `odom`, `tf·tf_static`(`map→base_footprint`), `navigate_to_pose/_action/status`를 구독해 `GET /api/robots`, `/api/robots/<name>`, SSE `/api/robots/stream`(8090)과 ROS `/fms/robot_states`로 1초마다 내보냄. 표준 라이브러리 HTTP만. 설정 `config/robots.yaml`(로봇 `pinky_1`, namespace `''`, `emr_robot_id: 1`). 테스트 4개(state.py만) | ✅ (오늘 17:37) |
| `src/vla_planner_robot` (우리) | 9 | OMX-F 자연어 pick & place: `vla_perception`(ArUco `DICT_5X5_100` 호모그래피·HSV 블록) → `vla_planner`(Ollama `POST /api/chat`, JSON 스키마로 블록 id·장소만 고름, `resolve_plan`이 좌표 계산) → `vla_executor`(top-down IK + MoveIt Pilz PTP, 손목 카메라 집기 확인) + `vla_sim`, `vla_bringup`, `vla_calibration`(4종), `vla_dual_description`, `vla_dual_moveit_config`, `vla_interfaces`. 1팔·2팔(left/right) 시뮬 검증 완료. 테스트 함수 37개(문서는 43/41로 표기가 다름) | ✅ (오늘 16:17) |
| `src/pinky_pro` (upstream, 수정 금지) | 11 | Pinky Pro AMR: bringup, description, navigation(Nav2·slam_toolbox·Flask 웹 8080), gz_sim, mujoco, interfaces, emotion, led + 하드웨어 전용 imu_bno055, lamp_control, sensor_adc | 8 ✅ / 3 미빌드(RPi 전용). emotion·led는 빌드됐지만 PC에선 import 불가 |
| ROBOTIS upstream (수정 금지) | 13 | `open_manipulator`(8), `dynamixel_hardware_interface`, `robotis_interfaces`, `om_*` 컨트롤러 3 | ✅ |

- 빌드 로그: 2026-10-19 16:17(vla 9개), 17:05(pinky 8개), 17:37(robot_monitor) 모두 rc 0. `log/`는 49회 빌드분 18MB.
- 캘리브레이션: 실물용 `calib/` 없음. `calib_sim/`에 시뮬 결과(intrinsics·colors·table·wrist·arm_poses).
- 문서: `README.md`(한국어 사용자용), `CLAUDE.md`, `docs/report_technical.*`(2026-10-15, 시뮬 단계), `docs/report_visual.*`(2팔 부분 없음), `docs/test_report_dual.pdf` + `docs/test_report/`(2팔 시험 10회), `docs/tests/run_dual_suite.py`·`make_report.py`.

### 3.3 `ollama_ws/` — 예정

비어 있다(2026-10-11 생성). 사용자 확인: **Ollama에 없는 다른 모델을 Ollama 호환 인터페이스로 제공**하기 위한 작업 폴더.
`vla_planner`는 `urllib`로 `POST {ollama_host}/api/chat`에 `stream: false`, `format`(요청마다 만든 JSON 스키마), `options.temperature: 0`을 보내고 `message.content`를 읽는다(`llm_plan.ask_ollama`, `llm_timeout 90초`). 여기서 만들 서버가 이 형식을 지키면 `planner.yaml`의 `ollama_host`·`model`만 바꿔 연결된다.

## 4. 시스템 간 연결 현황

```
브라우저(간호사) ──http──▶ web :5173 ──/api/v1 프록시──▶ api :8000 ──▶ db :5432
                                                          ▲   └─ pg_notify → SSE 재고 부족 알림(모든 간호사)
Pinky Pro(로봇) ◀──ROS 2 DDS, 도메인 56──▶ robot_monitor :8090 ──▶ (관제 화면: 아직 없음)
                                           └─ emr_robot_id 숫자만 가짐, EMR을 부르지 않음
로봇 프로그램(아직 없음) ──X-Robot-Api-Key──▶ api :8000  POST /robot/deliveries/{id}/receipt
vla_planner(OMX-F) ──POST /api/chat──▶ Ollama :11434 (같은 PC)   ◀── ollama_ws가 대체할 자리
```

| 연결 | 지금 | 비고 |
|---|---|---|
| EMR → 로봇 | 없음 | 배송 전송·목록 API 없음. 2단계에서 "로봇이 EMR을 조회(claim)"로 결정됨(`emr/CLAUDE.md`) |
| 로봇 → EMR | 없음 (API만 준비) | `src/` 전체에 `api/v1`·`X-Robot-Api-Key`·`receipt`·`claim` 호출 0건. 로봇 쪽 외부 HTTP는 Ollama POST 하나 |
| robot_monitor → EMR | 없음 | `emr_robot_id`는 매칭용 값. 모니터가 올릴지, 로봇이 직접 올릴지 미정 |
| Pinky → robot_monitor | DDS 토픽·TF·액션 상태 | 로봇과 같은 `ROS_DOMAIN_ID`(56)·네트워크 필요. 시뮬은 배터리를 발행하지 않음 |
| vla_planner → Ollama | HTTP 로컬 | Ollama가 `127.0.0.1`만 수신 — 다른 PC·로봇이 쓰려면 `OLLAMA_HOST=0.0.0.0` |

**맞지 않는 것(계약 때 확정)**

- 마커 딕셔너리: EMR 간호사 마커 `DICT_4X4_50`(0~49, 인쇄 50mm 가정) vs VLA 테이블 마커 `DICT_5X5_100`(0~3, 5cm). 로봇 카메라는 둘 다 검출해야 한다. `vla_perception`은 `DICT_4X4_50`을 오류 메시지 예시·부정 테스트에만 쓴다.
- 프레임: EMR 장소 좌표 = ROS `map` 프레임 미터·라디안(가정). robot_monitor `base_footprint`, pinky `bt_navigator` `robot_base_frame: base_link`, Flask 웹서버 `map→base_link`.
- 로봇 상태값: EMR `idle|delivering|charging|maintenance`(가정), 모니터 `offline|idle|navigating`.
- 로봇 여러 대: EMR 로드맵 6단계(namespace별). 모니터는 `map_frame`·`base_frame`이 전역이라 namespace 로봇(`frame_prefix=<ns>/`)은 pose가 null, pinky `nav2_params.yaml`·`mapper_params.yaml`은 `/scan` 절대 경로.

## 5. 문제·위험·권고 (우선순위)

| # | 심각도 | 문제 | 권고 | 담당 |
|---|---|---|---|---|
| 1 | **높음** | `~/.bashrc` 140줄이 **Gemini API 키**를 전역 export하고, colcon이 셸 환경을 통째로 남겨 `robot/log/*/events.log` 47개와 `robot/build/*/colcon_command_prefix_*.env` 31개에 키가 평문으로 들어 있다(`~/pinky_pro/` 로그 1·build 8개도). 기록된 키는 1종 | 키 즉시 폐기·재발급 → `.bashrc`에서 export 제거(필요한 프로그램만 별도 파일에서 읽기) → `robot/log/` 삭제, `robot/build/`는 키 제거 후 다시 빌드 → `log/`·`build/` 공유·커밋 금지 | 로봇 |
| 2 | **높음** | Postgres 5432가 `0.0.0.0`에 개발 계정(emr/emr)으로 열려 있음. Jupyter 8888도 전체 바인딩 | compose `ports`를 `127.0.0.1:5432:5432`로(또는 제거), Jupyter는 로컬 바인딩·토큰 확인 | 웹 / 공통 |
| 3 | 높음 | EMR을 지금 상태로 운영에 못 올림: 프론트 prod 이미지에 `/api` 프록시 없음(`nginx.conf`), `VITE_API_URL` 기본값 `localhost:8000`, uvicorn `--reload` 단일 프로세스, `ENV=prod`여도 `/openapi.json` 공개, 도메인 예외 외 catch-all 없음(plain 500), Dockerfile root·HEALTHCHECK 없음, `.dockerignore` 없어 `.env`까지 빌드 컨텍스트, 전 구간 http | 6.1 "운영 준비" 목록대로 | 웹 |
| 4 | 중간 | 메모리 15GB 중 9GB + swap 2.9GB 사용. Gazebo+MoveIt+Ollama+Docker 동시 실행 시 OOM(빌드 exit 137 이력) | 시뮬 중엔 불필요한 것 내리기, 빌드 `--parallel-workers 2`, 장기적으로 RAM 증설 또는 EMR/로봇 PC 분리 | 공통 |
| 5 | 중간 | 로봇 여러 대 미지원(모니터 전역 프레임, nav2 `/scan` 절대 경로, `base_link`/`base_footprint` 불일치) | 6.2 "관제 모니터" 목록 | 로봇 |
| 6 | 중간 | robot_monitor 8090이 인증 없음·CORS `*`·`0.0.0.0` | 로컬 바인딩 + EMR/프록시 뒤에 두거나 토큰 추가 | 로봇 |
| 7 | 중간 | 셸 환경 오염(`~/.bashrc` 전역 doosan_ws·conda), `~/pinky_pro/` 중복 워크스페이스 | doosan source는 기존 `rosdoosan` alias로만, `conda config --set auto_activate_base false`, 중복 ws 정리 | 로봇 |
| 8 | 낮음 | EMR 테스트 한계: 마이그레이션 미검증(`create_all`), `emr_test` DB 수동 생성, `TestClient`가 lifespan을 실행해 dev DB도 필요(주석과 다름), `JWT_SECRET` 없으면 import 실패 | 6.1 "정리" | 웹 |
| 9 | 낮음 | 정리 후보: `emr/backend/docker-compose.yml`(통합 전 db 전용), 프론트 `[검토 필요]` 3건이 `REVIEW.md`에 안 잡힘(`scripts/review.py`가 백엔드만 스캔), `npm run gen` 결과 `schema.d.ts` 부재, `emr/.claude/settings.json`에 다른 PC 경로 규칙, robot 테스트 수 표기 43/41 불일치, `report_visual.pdf` 2팔 부분 없음 | 6.1 / 6.2 | 웹·로봇 |

## 6. 다음 단계 — 웹 · 로봇(Pinky) · OMX 세 갈래로 나눠서 진행

세 갈래는 **6.4의 계약 문서가 나오기 전까지** 서로 독립적으로 할 수 있는 일(운영 준비·보안·정리·모니터 개선·실물 캘리브레이션)을 먼저 한다.
계약이 정해지면 6.1-B, 6.2-C, 6.3-C를 같은 문서를 보고 각자 구현한다. 담당 폴더: 웹 `emr/`, 로봇 `robot/src/fms` + `robot/src/pinky_pro`(읽기만), OMX `robot/src/vla_planner_robot` + `ollama_ws/`.

### 6.1 웹(EMR) 할 일 — `emr/`

**A. 지금 할 수 있는 것 (계약과 무관)**
1. 보안: db `ports`를 `127.0.0.1:5432:5432`로 제한. `ENV=prod`일 때 `openapi_url=None`(`main.py`). catch-all 예외 핸들러로 500도 `{"code","detail"}` JSON으로(IntegrityError 포함).
2. 이미지: `.dockerignore`(`.env`, `node_modules`, `tests`, `.pytest_cache`, `dist`), Dockerfile non-root + HEALTHCHECK(`/health`가 DB까지 확인하도록).
3. 프론트 운영 이미지: `nginx.conf`에 `location /api/ → api:8000` 프록시(SSE용 `proxy_buffering off`, 긴 `proxy_read_timeout`), 빌드 인자 기본값 `VITE_API_URL=/api/v1`, compose에 `prod` 프로필(web-prod :8080) 추가, `Dockerfile` 주석 갱신.
4. 백엔드 기동: 운영용 entrypoint(`--reload` 없이 `--workers N --proxy-headers`), DB 대기 타임아웃, `SEED` 기본 0, `JWT_SECRET` 길이 검사, 첫 관리자 지정 방법(열린 항목).
5. TLS: 리버스 프록시(nginx/caddy)로 https만 열기 — 로그인 비밀번호·로봇 키가 평문으로 간다.
6. 정리: `backend/docker-compose.yml` 삭제, `scripts/review.py`가 `frontend/src`도 스캔하게(또는 REVIEW.md에 프론트 3건 수동 기재), `npm run gen`으로 `schema.d.ts` 만들어 `types.ts` 대조, `.claude/settings.json` 잔존 규칙 삭제.
7. 테스트: `conftest.py:72` 주석 수정, `emr_test` DB 자동 생성(fixture 또는 entrypoint), 마이그레이션 기반 테스트 1개(`alembic upgrade head` → downgrade).

**B. 2단계(배송 배정·진행) — 계약 문서 확정 후**
1. 상태 머신 확장: `reserved → dispatched → arrived(마커 대기) → received`, `failed(사유)`. 변경·취소 허용 상태 재정의, 간호사 화면에 단계 표시, 배송 목록 폴링(30초) 유지 또는 SSE로 전환.
2. 로봇 API: `POST /robot/deliveries/claim`(예약 시각 지난 것부터 한 건, `FOR UPDATE SKIP LOCKED`), `POST /robot/deliveries/{id}/progress`, 로봇별 복귀 장소. 오류 코드와 한국어 안내(`errorMessages.ts`) 함께.
3. 3단계 `POST /robot/status` `{map_id, x_m, y_m, yaw_rad, battery_percent}`, `last_seen_at`, 끊김 표시, 맵에 위치·배터리(MapView `[검토 필요]` 해소).
4. 4단계 `robot_events` 테이블 + 관리자 로그 화면, 5단계 SSE 구독자별 필터링. 관리자 전체 배송 조회 API.
5. REVIEW.md 3건 반영: 로봇 상태 종류(AMR·매니퓰레이터 따로), 좌표계 확정, 로봇 삭제 → 비활성화.
6. (나중, OMX 적재 단계) `manipulator` 로봇의 적재 API — 적재할 배송·품목을 OMX가 받고 결과를 올리는 엔드포인트. 6.3-C와 함께.

### 6.2 로봇(Pinky AMR · 관제 모니터 · 워크스페이스 공통) 할 일 — `robot/src/fms`, `robot/src/pinky_pro`

**A. 지금 바로 (워크스페이스 공통)**
1. **Gemini API 키 폐기·재발급**, `~/.bashrc` 140줄의 export 제거, `robot/log/` 삭제(18MB), `robot/build/` 정리 후 재빌드(키가 `colcon_command_prefix_*.env` 31개에 있음). `~/pinky_pro/`도 같은 처리.
2. `~/.bashrc` 정리: `~/doosan_ws` 전역 source 제거(기존 `rosdoosan` alias 사용), `conda config --set auto_activate_base false`. 새 터미널에서 `which python3`가 `/usr/bin/python3`인지 확인.
3. `~/pinky_pro/` 중복 워크스페이스 정리(둘 중 하나만 남김).

**B. 관제 모니터 (`src/fms/robot_monitor`) — 계약과 무관하게 가능**
1. 로봇 여러 대: `robots.yaml`에 로봇별 `base_frame`/`map_frame`(기본 `<ns>/base_footprint`) 허용, `frame_prefix` 반영. 우리 쪽 params 파일로 pinky nav2 `/scan`·프레임 override(upstream 수정 금지).
2. `base_link` vs `base_footprint` 통일(bt_navigator·Flask 웹·모니터).
3. 오프라인 판정: 실물 `battery_publisher` 5초 주기 > `offline_after_s` 3초 — odom 기준인지 명시하거나 TF도 online 갱신에 포함. offline 시 pose·velocity 처리 규칙.
4. 접근 제어: 8090을 `127.0.0.1` 바인딩 + 프록시 뒤 또는 간단한 토큰, CORS 제한.
5. 시뮬에서 배터리 mock 발행 노드로 e2e 확인, 노드·HTTP·SSE 테스트 추가(지금 state.py 4개뿐), launch 파일 추가.
6. Pinky 실물 1대로 모니터 확인: 같은 도메인(56)·네트워크에서 `offline → idle → navigating` 전이, 배터리·위치가 `GET /api/robots`에 나오는지.

**C. EMR 연동 — 계약 문서 확정 후**
1. Pinky에서 도는 EMR 클라이언트 노드: `X-Robot-Api-Key` 보관(설정 파일 권한), `claim` 폴링 → Nav2 `navigate_to_pose`(장소 좌표 = EMR `map_x_m, map_y_m, map_yaw_rad`) → 도착 보고 → 간호사 마커 인식 → `receipt` 호출 → 복귀 장소 → 상태 보고 `POST /robot/status`(주기·배터리).
2. 간호사 마커 인식(Pinky 카메라): `DICT_4X4_50`, 인쇄 크기 50mm 가정을 카메라 거리·자세로 검증해 EMR 쪽에 회신(`MarkerPrintDialog` `[검토 필요]`).
3. 모니터와 EMR의 관계 결정: 모니터가 EMR에 상태를 올리는 서버↔서버 연동인지, 로봇이 직접 올리는지. 네트워크: 로봇이 EMR에 닿는 주소(`http://192.168.129.135:8000` → 운영은 https).
4. EMR 맵 업로드용 맵(slam_toolbox yaml+pgm)을 Pinky에서 뽑아 EMR에 올리고, 장소 좌표가 Nav2 목표와 맞는지 1회 검증.

### 6.3 OMX(로봇팔 · VLA · LLM) 할 일 — `robot/src/vla_planner_robot`, `ollama_ws/`

**A. 실물 전환 (robot/README 9장·7장) — 계약과 무관**
1. 테이블 마커 `DICT_5X5_100` ID 0~3 출력, 마커 중심 간 거리 실측 → `marker_positions` 초기값.
2. 카메라 장치(`/dev/video*`)·해상도 확정 → `vla_calibration intrinsics` → `camera_info.yaml`.
3. 블록(또는 실제 비품) 크기·색 → `block_height`, `vla_calibration colors`.
4. 손목 카메라 장착 → `vla_calibration wrist`(없으면 `wrist_check: false`).
5. `vla_calibration table`로 로봇 기준 마커 위치 → `calib/`에 저장, `calib_dir`로 적용. 실물용 `executor.yaml`(`use_sim_time: false`).
6. OMX-F 포트(U2D2) → `open_manipulator_bringup omx_f.launch.py`로 실물 1팔 pick & place 재현(시뮬 지표: 위치 오차 ≤ 7mm, 쌓기 8/9).

**B. 2팔 실물**
1. U2D2 2개(두 팔 모두 Dynamixel ID 11~16) → `left_port`/`right_port`, ROBOTIS `omx_f_system` 서비스 이름 충돌을 실물 launch에서 분리.
2. 실측: `base_separation`(0.33 가정), `board_front`(0.06 가정), 트레이·그릇 크기와 손잡이.
3. 시뮬에서 남은 문제: 협동 운반 5회 중 1회 실패 원인, 기울기 5° 초과(3/5), 핸드오프 공유 영역이 좁음(y≈0, x 0.10~0.17m).

**C. EMR 적재 연동 — 계약 문서 확정 후 (EMR 로드맵 "나중": 적재 = 사람 확인 → OMX)**
1. 적재 시퀀스 정의: Pinky 적재 장소 도착 → 적재 시작 → OMX가 품목 집어 Pinky에 적재 → 적재 성공/실패 → 배송 시작. emr/CLAUDE.md의 보류된 "작업 시퀀스"를 이 범위로 다시 정한다.
2. OMX가 EMR에서 받을 것: 어느 배송·어떤 비품·몇 개. 비품을 카메라로 구별하는 방법(지금은 색 블록 HSV뿐) — 비품에 마커를 붙일지, 칸(슬롯) 위치로 구별할지.
3. `manipulator` 로봇 상태값(REVIEW.md #1: `delivering·charging`이 맞지 않음) → 예: `idle·loading·error·maintenance`.
4. `vla_planner`의 명령 입력을 자연어 CLI 외에 EMR 적재 요청(구조화 JSON)으로도 받는 액션/토픽.
5. OMX도 로봇별 API 키를 받아 `X-Robot-Api-Key`로 적재 결과를 올림(키 보관 방식은 6.2-C-1과 동일).

**D. LLM 교체 — `ollama_ws/`**
1. Ollama 호환 서버 구현: `POST /api/chat`(`stream: false`, `format` JSON 스키마, `options.temperature`, 응답 `message.content`), `GET /api/tags`. 이 PC의 11434와 포트가 겹치지 않게.
2. `planner.yaml`/`planner_dual.yaml`의 `ollama_host`·`model`만 바꿔 연결, 명령 해석 10문항 재검증(현재 `gemma4:e2b` 10/10, 평균 3.1초, 첫 호출 15초).
3. 다른 PC·로봇에서 쓰려면 바인딩 `0.0.0.0`과 접근 제한을 같이 정한다(기존 Ollama는 로컬 전용).

**E. 문서·테스트**
1. `docs/report_visual.pdf`에 2팔 부분 추가, README·technical 문서 동기화(robot/CLAUDE.md "Docs to keep in sync").
2. 테스트 수 표기 통일(CLAUDE.md 43 / README 41 / 함수 37).

### 6.4 세 갈래가 먼저 맞출 것 (API 계약 문서 1장, `docs/`에)

1. 배송 상태 머신과 전이 조건(누가 어떤 상태로 바꾸는지). 적재 단계가 들어갈 자리(지금은 적재 없이 바로 출발).
2. 로봇 API 필드·단위·주기·오류 코드: `claim`, `progress`, `receipt`, `status`, (나중) 적재. 단위는 이름에(`_m`, `_rad`, `_percent`), 시각은 ISO 8601.
3. 인증: 로봇 키 전달·보관 방법(Pinky·OMX 각각), 재발급 절차, https 적용 시점.
4. 좌표계: `map` 프레임·origin·yaw 방향(반시계), EMR 맵 교체 시 좌표 재지정 절차.
5. 마커 규격: 간호사 `DICT_4X4_50`(Pinky가 읽음), 테이블 `DICT_5X5_100`(OMX가 읽음), id 범위, 인쇄 크기, 인식 거리.
6. 로봇 상태 종류(AMR·매니퓰레이터 따로), 로봇 삭제/비활성화, 끊김 기준 시간.
7. 로봇 여러 대: namespace 이름 규칙 ↔ EMR `robots.name`/`emr_robot_id` 매칭.

## 부록 — 확인에 쓴 명령 (읽기 전용)

```bash
ls -la ~/dev_ws; find ~/dev_ws -maxdepth 3 ...            # 구조
cat emr/CLAUDE.md emr/README.md robot/CLAUDE.md robot/README.md emr/backend/REVIEW.md
cat emr/docker-compose.yml emr/.env.example; sed 's/=.*/=<redacted>/' emr/.env
nproc; free -h; df -h; nvidia-smi; ls /opt/ros; ollama list
docker ps -a; docker volume ls; docker images; ss -tlnp; ps aux; systemctl list-units
curl :8000/docs :8000/openapi.json :5173 :11434/api/tags :8090/api/robots
docker logs --tail 15 emr-api-1; docker exec emr-db-1 psql ... select count(*)
git -C robot/src/pinky_pro log -1; git -C robot/src/open_manipulator log -1
ls robot/install robot/build; grep -iE 'error|fail' robot/log/latest_build/events.log
grep -rl GEMINI_API_KEY robot/log | wc -l; grep -rl AIza robot/build | wc -l   # 47, 31 (값은 기록하지 않음)
grep -nE 'source|conda|ROS_' ~/.bashrc; systemctl show ollama -p Environment
grep -rn 'emr\|X-Robot-Api-Key\|api/v1\|receipt\|claim\|DICT_4X4_50' robot/src   # 연동 여부
```
