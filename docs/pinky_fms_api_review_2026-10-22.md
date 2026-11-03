# 팀원 Pinky API(:8080) 분석과 배송 연동 제안 (2026-10-22)

- 독자: 팀원 전체 — 웹(EMR), 로봇(Pinky·관제). 특히 Pinky API를 만든 팀원에게 9장의 질문을 부탁한다.
- 대상: 팀원이 만든 Pinky 1대용 REST API `http://192.168.129.107:8080` (Swagger `/docs`, 명세 `/openapi.json`, 제목 "Pinky API" 0.1.0).
- **주소 변경(2026-10-22 20시대)**: 팀원 API가 `http://192.168.129.122:8080`(로봇 serial `1cdda27b956a1efc`, 다른 Pinky)으로 옮겨졌다. 아래 2·11·12장 실측은 이전 주소 `192.168.129.107`(serial `8ab6b3c36a27f120`)에서 잰 것. API 형식은 같다.
- **이름 변경(2026-10-22 같은 날)**: 팀원이 `/stops` → `/dests`, `POST /goto {"stop"}` → `{"dest"}`, `/plan?stop=` → `?dest=`로 바꿨다. 아래 본문의 stop은 dest로 읽는다(실행기는 반영함, 설정 키도 `dests`).
- 방법: 이 PC에서 **GET만** 불렀다(`/status`, `/stops`, `/jobs`, `/plan`, `/openapi.json`). `POST /goto`·`/cancel`·`/set_pose`는 부르지 않았다 — **로봇은 움직이지 않았다.**
- 상태: **구현함(2026-10-22)** — 사용자 결정: 지금은 **인증 없이** 진행, **수령 마커는 일단 끔**(간호사·환자 모두 "받았습니다" 버튼).
  실행기 `navigation: pinky_api`(`delivery_executor/pinky_api.py`), 계약 4장 갱신. 가짜 Pinky API로만 확인했다(실물 주행은 보류 그대로).
  남은 것: 9장 질문 1·4·5·6(좌표 변환·복귀 stop·맵/배터리·코드 위치), 인증(질문 3), 마커(질문 2) — `stops` 표는 임시 대응.

## 1. 한 줄 결론

배송 실행기(`robot/src/fms/delivery_executor`)가 Nav2를 직접 부르는 대신 **이 API의 `POST /goto {stop}`과 `GET /jobs/{id}`로 주행**하게 바꾸는 것을 권한다.
EMR 쪽 API·화면은 바꿀 필요가 없다(실행기 설정에 "EMR 장소 → 목적지 이름" 표만 둔다). 대신 **좌표 기준 변환, 수령 마커, 인증** 세 가지는 팀원과 정해야 한다.

## 2. 실측 (2026-10-22 19시경)

| 항목 | 값 |
|---|---|
| 로봇 | `raspi`, serial `8ab6b3c36a27f120`, IP `192.168.129.107`(병원 LAN) + `192.168.4.1`(로봇 AP) |
| 상태 | `localized: true`, `nav2_ready: true`, `state: idle`, 작업 기록 0건 |
| 위치 | (61.7, 144.5) cm, heading −179° — "그림 cm, 라이다 중심" |
| 서버 | Flask 개발 서버(`Werkzeug/3.1.8 Python/3.12.3`) |
| 인증 | **없음** — 같은 LAN의 누구나 `POST /goto`로 로봇을 움직일 수 있다 |
| CORS | 헤더 없음 → 브라우저(EMR 웹)에서 직접 부를 수 없음. 서버·실행기에서 부르는 것은 문제없음 |
| ROS | 이 PC에서 도메인 0으로 `ros2 topic list` → `/parameter_events`·`/rosout`만 보임. **LAN 너머로 로봇 ROS 토픽이 안 보인다**(TF·`/map` 못 읽음) |

목적지(`GET /stops`) 11곳:

| 이름 | 뜻 | 위치 cm | heading | 정밀 주차 |
|---|---|---|---|---|
| `ROOM4_L` / `ROOM4_R` | 4인실 왼쪽 / 오른쪽 | (35, 178) / (175, 178) | 90 | — |
| `ROOM1_CUL` / `ROOM1_CUR` | 1인실 가운데 위-왼 / 위-오른 | (65, 108) / (97, 115) | 90 / 270 | — |
| `ROOM1_CLL` / `ROOM1_CLR` | 1인실 가운데 아래-왼 / 아래-오른 | (72, 45) / (105, 52) | 90 / 180 | — |
| `PHARMACY` | 약제실 OMX | (98.9, 178.8) | 90 | `aruco` |
| `SURGERY` | 수술실 | (180, 50) | 90 | — |
| `POCKET` | 대기 포켓 | (200, 150) | 0 | — |
| `CHARGER` | 충전 | (200, 125) | 270 | — |
| `START_A` | 출발점 A | (182.7, 24.0) | 180 | — |

경로 예(`GET /plan`, 움직이지 않음): 지금 위치 → `ROOM1_CUL`은 90.4 cm, 구간 `nav`(복도) → `wall`(협로 오른쪽 벽 따라가기, 10 cm) → `nav`.
→ `PHARMACY` + `dock=true`는 71 cm, `nav` → `nav` → `dock`(카메라 정밀 주차).

## 3. API 요약

| 메서드 | 경로 | 하는 일 | 응답·오류 |
|---|---|---|---|
| GET | `/status` | 위치·`localized`·`nav2_ready`·`state`(idle/running)·지금 작업 | — |
| GET | `/stops` | 목적지 이름 → `{xy, heading, name, dock}` | — |
| GET | `/plan` | 경로만 계산 (`stop` 또는 `x,y[,heading]`, `dock`, `from`) | 400 목적지 없음·그래프로 못 감, 503 위치 모름 |
| POST | `/goto` ⚠️ | 주행 시작 `{"stop": "...", "dock": false}` 또는 `{"x","y","heading"}` | 202 `{job, plan}`, 400 못 가는 곳, **409 다른 작업 중**, 503 위치 모름 |
| POST | `/cancel` | 지금 작업 멈춤 | `{canceled, state}` |
| GET | `/jobs`, `/jobs/{id}` | 작업 목록(최신 50) · 상세 | 상세: `state`(running/succeeded/failed/canceled), `segment`/`segments_total`, `progress`(남은 cm), 구간별 `results`(`ok·fail·canceled·blocked·contact·timeout·lost` + `why`), `end_pose`, `end_error_cm` |
| POST | `/set_pose` | AMCL 시작 위치(이름·좌표·`find`) — Nav2 띄운 직후 필수 | 200 맞음, 422 스캔과 안 맞음, 409 주행 중, 504 시간 초과 |

## 4. 지금 우리 쪽과 다른 점

| # | 항목 | 팀원 Pinky API | 지금 EMR·배송 실행기 | 영향 |
|---|---|---|---|---|
| 1 | 좌표 | 그림 cm, heading deg, **라이다 중심** | ROS `map` 프레임 m·rad(EMR 장소 `map_x_m`·`map_yaw_rad`), 기준 `base_footprint` | EMR 장소 좌표를 그대로 넘길 수 없다. 변환식(평행 이동·회전·라이다 오프셋)을 팀원에게 받아야 한다 |
| 2 | 목적지 | 이름 11개(주행 그래프의 stop 노드) | EMR 장소 5곳: 간호사스테이션·301호·302호·비품실(맵 `병원 map_rev2`), 303호(다른 맵) | 이름이 서로 다르다. 같은 곳인지부터 맞춰야 한다(6장 표) |
| 3 | 주행 | 주행 그래프: 복도 Nav2 + **협로 벽 따라가기** + 회전 + **ArUco 정밀 주차** | Nav2 `navigate_to_pose` 한 번 | 팀원 쪽이 실제 아레나에 맞게 더 다듬어져 있다. 우리가 같은 것을 다시 만들 이유가 없다 |
| 4 | 통신 | HTTP(LAN) | ROS 2 DDS(같은 네트워크·도메인 필요) | 지금 LAN에서는 ROS가 안 보여 **실행기의 Nav2 방식은 이 상태로는 못 돈다**. HTTP는 된다 |
| 5 | 작업 | 한 번에 하나, `job` id로 추적, 끝 상태 4가지 | 배송 하나 = 목적지 주행 + 대기 + 복귀 | 실행기가 job id를 기억하고 `/jobs/{id}`로 끝을 기다리면 된다 |
| 6 | 맵 확인 | 맵 API 없음 | 실행기가 로봇 `/map`과 EMR 맵을 비교(10-20) | 비교 방법을 바꿔야 한다(로봇 맵 파일 이름·해시를 `/status`에 넣어 달라고 할지) |
| 7 | 수령 마커 | 없음(카메라는 `PHARMACY` 정밀 주차에만) | ROS 토픽 `receipt_marker`(Int32)를 기다림 | ROS가 LAN 너머로 안 보이므로 마커도 HTTP로 받아야 한다 |
| 8 | 인증 | 없음 | EMR은 로봇별 키(`X-Robot-Api-Key`) | 운영 전에 로봇 API에도 키가 필요하다 |

## 5. 제안 — 배송 실행기를 Pinky API로 주행

EMR ↔ 실행기 계약(3장)은 **그대로** 두고, 실행기 ↔ 로봇 부분(4장)만 바꾼다.

```
EMR :8000 ──claim·progress·receipt (지금 그대로)──▶ delivery_executor(관제 PC)
                                                   │ POST /goto {stop}   GET /jobs/{id}   POST /cancel
                                                   ▼
                                     Pinky API :8080 (로봇) ──▶ 주행 그래프 · Nav2 · 벽 따라가기 · 정밀 주차
```

실행기 동작 (계약 4장 고칠 안):

| 단계 | 지금 (Nav2 직접) | 바꾼 뒤 (Pinky API) |
|---|---|---|
| 시작 확인 | `/robot/me` + 로봇 `/map` = EMR 맵 | `/robot/me` + `GET /status`: `localized`·`nav2_ready`·`state=idle`이 아니면 배송을 맡지 않음 |
| 목적지 | 장소 좌표(m) → `navigate_to_pose` | 장소 id → 설정 표의 stop 이름 → `POST /goto {"stop"}`. 표에 없는 장소는 `failed destination_blocked`(움직이지 않음) — 지금 금지 장소 규칙과 같은 자리 |
| 진행 | Nav2 결과 기다림 | 1초마다 `GET /jobs/{id}`. `succeeded` → `progress arrived` |
| 실패 | Nav2 실패·시간 초과 → `navigation_failed` | `failed`(구간 결과 `blocked·contact·timeout·lost·fail`) → `navigation_failed`, 로그에 `why`. `POST /goto` 400 → `destination_blocked`, 503 → 배송을 맡지 않고 기다림 |
| 409 다른 작업 중 | — | 다른 사람이 로봇을 쓰는 중. 배송을 맡기 전에 `/status`로 확인하므로 claim 뒤 409면 잠깐 기다렸다 다시, 계속이면 `robot_error` |
| 복귀 | 복귀 장소 좌표로 Nav2 | 설정의 복귀 stop(예: `POCKET` 또는 `CHARGER`)으로 `POST /goto` |
| Ctrl+C | Nav2 목표 취소 | `POST /cancel`(실행기가 시작한 job일 때만) |
| 재시작 | `/robot/me`의 맡은 배송부터 | 같음 + `GET /jobs`에서 실행기가 시작한 `running` job이 있으면 그것을 이어서 기다림 |
| 수령 마커 | ROS `receipt_marker` | 로봇 API에 마커 읽기 경로가 생기면 그것(9장 질문 2). 그 전엔 시험용으로 실행기에 마커 번호를 손으로 넣는 방법 |

실행기 설정(예, `config/executor.yaml`):

```yaml
robots:
  pinky_1:
    emr_robot_id: 1
    api_key_file: ~/.config/delivery_executor/pinky_1.key
    pinky_api: http://192.168.129.107:8080     # ros_domain_id 대신
    home_stop: POCKET
    stops:                                       # EMR 장소 id → Pinky 목적지 이름 (6장 표를 정한 뒤 채움)
      3: ROOM1_CUL        # 301호 (예시)
      4: ROOM1_CUR        # 302호 (예시)
```

코드 변경 범위(추정): `logic.py`는 이미 `Navigator`·`MarkerSource`를 주입받는 구조라 **새 `PinkyApiNavigator`(HTTP, 표준 라이브러리)** 를 하나 만들고 `navigate()`가 좌표 대신 목적지(장소)를 받게 바꾸면 된다. ROS 의존(`ros_io.py`)은 선택으로 남긴다. 단위 테스트는 가짜 Pinky API로.

좋은 점:
- 협로·정밀 주차를 팀원 코드 그대로 쓴다.
- LAN에서 HTTP만 되면 되므로 ROS 도메인·DDS 문제가 없다.
- 여러 대는 로봇마다 주소만 다르면 된다 — `docs/pinky_multi_robot_2026-10-20.md`의 "로봇마다 ROS 도메인" 안보다 단순하다.

나중 단계에 쓸 수 있는 것:
- EMR 로드맵 3단계(로봇 위치·상태): `robot_monitor`가 ROS 대신 `GET /status`를 읽게 하면 된다. 맵 위 표시는 1번 변환식이 있어야 한다.
- 적재(OMX): `PHARMACY`(약제실 OMX, ArUco 정밀 주차)가 OMX 로봇팔 앞 정차 위치로 보인다.

## 6. EMR 장소 ↔ Pinky 목적지 (팀이 채울 표)

> **2026-10-22 해결**: 사용자 결정으로 Pinky 목적지 11곳을 그대로 EMR 맵 "Pinky 아레나"·장소로 가져왔다(`emr/backend/scripts/import_pinky_dests.py`, 장소에 `robot_dest`). 아래 표는 그 전 기록.

| EMR 장소 (id) | EMR 좌표 m (맵 `병원 map_rev2`) | Pinky 목적지 | 비고 |
|---|---|---|---|
| 간호사스테이션 (2) | (−0.60, −1.55) | ? | 지금 로봇 1호 복귀 장소. Pinky엔 없음 → `POCKET`·`CHARGER`·`START_A` 중? |
| 301호 (3) | (0.26, −0.92) | ? | 1인실 4곳·4인실 2곳 중 |
| 302호 (4) | (0.61, −0.12) | ? | |
| 비품실 (1) | (0.42, −1.51) | `PHARMACY`? | 지금 실행기 금지 장소(비품실 모방학습 중) |
| 303호 (7) | 다른 맵(3병동) | — | Pinky 아레나 밖으로 보임 |
| (없음) | — | `SURGERY`, `ROOM4_L/R`, `ROOM1_*` 나머지 | EMR에 장소로 새로 등록할지 |

EMR 맵 `map_rev2`(5.42 × 7.18 m)와 팀원 아레나(약 2.1 × 1.9 m 그림)가 같은 공간인지도 확인이 필요하다. EMR 장소를 팀원 그래프 이름으로 다시 정리하는 것이 가장 간단할 수 있다.

## 7. 위험

- **인증 없음**: LAN의 누구나 `POST /goto`로 로봇을 움직인다. 시연 전에 최소한 고정 토큰 헤더(예: `X-Pinky-Token`)라도.
- **Flask 개발 서버**: 운영 전엔 프로덕션 서버(waitress·gunicorn)로.
- **작업 하나만**: 팀원 시험 UI와 실행기가 동시에 `goto`하면 409. 실행기는 자기가 시작한 job id만 취소·추적해야 한다.
- **실물 시험 보류**: 배송 실물 종단 시험은 비품실 모방학습이 끝난 뒤(10-20 결정). 이번 제안을 구현해도 먼저 가짜 Pinky API로만 확인한다.

## 8. 하지 않은 것

- 로봇을 움직이는 호출(`goto`·`cancel`·`set_pose`)
- 그림 cm ↔ map m 변환 확인 — LAN에서 로봇 TF가 안 보여 같은 순간의 두 좌표를 비교하지 못했다

## 9. 팀원에게 물을 것

1. 그림 cm ↔ ROS `map` m 변환식(원점·회전·라이다 오프셋)과 지금 로봇이 쓰는 맵 파일(EMR의 `map_rev2`와 같은지).
2. 수령 마커: 로봇 카메라가 ArUco `DICT_4X4_250`(50–249)를 읽어 알려 주는 경로를 이 API에 넣을 수 있는지(예: `GET /marker` → `{id, age_s}`).
3. 인증 토큰 헤더를 넣을 수 있는지, 실행기 외에 `goto`를 부르는 곳(시험 UI 등)이 있는지.
4. 복귀·대기 위치로 어느 stop을 쓰면 되는지(`POCKET`·`CHARGER`·`START_A`).
5. `/status`에 맵 이름(또는 해시)과 배터리(%)를 넣을 수 있는지 — 실행기 맵 확인과 EMR 3단계에 쓴다.
6. 이 API 코드를 저장소 어디에 둘지(지금 GitHub 브랜치에 없음).

## 10. 결정되면 고칠 곳

- `docs/api_contract_delivery_2026-10-20.md` 4장(실행기 동작), 7장(열린 질문)
- `robot/src/fms/delivery_executor`: `PinkyApiNavigator`, 설정 `pinky_api`·`stops`·`home_stop`, 테스트
- `robot/README.md` 8-1-2, `robot/CLAUDE.md`, 루트 `CLAUDE.md` 포트 표(로봇 `:8080` 설명 갱신)
- `docs/pinky_multi_robot_2026-10-20.md` — 로봇마다 주소 방식으로 갱신할지

## 11. 실물 주행 1회 — START_A → PHARMACY (2026-10-22 19:30, 사용자 요청)

EMR·실행기 없이 `POST /goto {"dest": "PHARMACY", "dock": false}` 한 번(작업 `010406fb`). 시작 전 `/status`: (181.8, 22.9) cm, `localized`·`nav2_ready`, `idle`.

| 구간 | 방식 | 경로 cm | 결과 |
|---|---|---|---|
| 1 | `nav` | (181.8, 22.9) → (180, 15) | ok, 5.8 s |
| 2 | `nav` | (180, 15) → (130, 15) 복도 | ok, 8.4 s — (131.8, 13.8), heading 89.5° |
| 3 | `wall` | (130, 15) → (130, 145) 협로 벽 따라가기 | **failed** — 시작하자마자 |
| 4·5 | `nav` | → (98.9, 145) → PHARMACY (98.9, 178.8) | 실행 안 됨 |

- 오류(`job.error`): `ExtrapolationException: Lookup would require extrapolation into the past. Requested time 1792665048.094631 but the earliest data is at time 1792665048.513180, when looking up transform from frame [base_footprint] to frame [map]`
- 로봇은 협로 입구 (131.1, 13.9) cm, heading 83.7°에서 멈춤, `idle`·`localized` 유지 — 위험한 상태는 아님.
- 추정: 벽 따라가기 구간이 **지난 시각(약 0.4 s 전)의 TF**를 찾다가 버퍼에 없어 실패했다. TF 조회를 최신값(`rclpy.time.Time()`)으로 하거나 짧은 timeout을 주면 될 것으로 보인다 — 팀원 확인 필요(코드는 로봇에 있어 이 PC에서 볼 수 없음).
- 실행기 쪽 영향: 이 실패는 Pinky 작업 `failed` → 실행기 `navigation_failed` 보고 → 복귀 주행으로 이어진다. 협로를 지나는 목적지(PHARMACY 등)는 이 문제가 고쳐질 때까지 실패할 수 있다.

## 12. 팀원 업데이트 뒤 다시 확인 + 실물 주행 PHARMACY 앞 → START_A (2026-10-22 20:02, 사용자 요청)

API 다시 읽기(GET만):
- 엔드포인트·요청 형식 그대로(`/dests`, `POST /goto {"dest", "dock"}`). 작업 응답에 **`dock_error`**(정밀 주차 성공 시 마커 기준 어긋남 `{fwd_mm, left_mm, heading_deg}`)가 생겼고, 정밀 주차 작업은 `end_error_cm`가 null. 실행기는 도착 로그에 `dock_error`를 찍도록 맞췄다(동작 영향 없음).
- 작업 기록이 비어 있음 — 서버를 다시 띄운 것으로 보인다. 시작 위치 (96.2, 187.1) cm, heading 88.6°(PHARMACY 앞), `localized`·`nav2_ready`·`idle`.

`POST /goto {"dest": "START_A", "dock": false}` (작업 `4f3ffe69`) — **성공 54.9 s, 끝 (182.5, 22.9) cm, heading 179.9°, 오차 1.1 cm**.

| 구간 | 방식 | 결과 |
|---|---|---|
| 1 | `nav` (96.2, 187.1) → (98.9, 145) | ok 13.1 s |
| 2 | `nav` → (130, 145) 복도 | ok 6.6 s |
| 3 | `wall` (130, 145) → (130, 15) 협로 | **ok 21.2 s** — 11장의 TF ExtrapolationException이 다시 나지 않았다 |
| 4 | `nav` → (180, 15) 복도 | ok 9.3 s |
| 5 | `nav` → START_A (182.7, 24.0) | ok 4.7 s |

협로를 반대 방향(위 → 아래)으로 한 번 통과한 것이라, 11장 방향(아래 → 위, START_A → PHARMACY)도 한 번 더 보면 확실하다.
