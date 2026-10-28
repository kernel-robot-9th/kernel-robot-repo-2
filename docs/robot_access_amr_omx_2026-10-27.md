# EMR 로봇 연동 인터페이스 — AMR / OMX (2026-10-27)

> **EMR은 상위 관제다 (2026-10-27 사용자).** EMR이 붙는 바깥 시스템은 **팀원 FMS**(AMR·Pinky 담당)와 **팀원 OMX API**(로봇팔) **둘뿐**이다. Pinky 등 로봇에 직접 붙지 않고, 로봇도 EMR을 직접 부르지 않는다. 배차·경로·교통·충전은 FMS, 집기·놓기는 OMX가 한다.

EMR이 로봇 쪽과 주고받는 API를 **로봇 종류별로 나눠** 정리한다.
- **AMR**: 운반 로봇 Pinky. 팀원 FMS를 거친다.
- **OMX**: 탑재 로봇팔. 팀원 OMX API와 직접 주고받는다.

각 로봇마다 **지금 코드**와 **FMS API v1 연동 뒤(목표)**를 같이 적었다.

**구현 상태 (10-27 저녁)** — 계약 `api_contract_delivery_2026-10-20.md` 10장이 기준이다.
- AMR(1.2·1.3): **1단계 구현·시험함** — `POST /orders`(물품 1개당), 받는 곳 `/api/v1/fms/robot-status`(받기만)·`/api/v1/fms/events`(출발·도착·실패). `DELETE /orders`·`GET /state`·로봇 상태 저장은 아직.
- OMX(2.2): **구현함·꺼짐**(`FMS_OMX_ENABLED=0`, 실제 팔 시험 전). 2.2 순서 그대로 — 명령 `{"command": {"blue": N, "green": N}, "request_id": "emr-b{id}"}` 묶음당 한 번, `/pinky`는 정밀 주차 뒤 내려놓기. 다른 점: 두 완료 신호 구분은 OMX `/status`(`state`·`pinky`)로, 들고 있는 동안 다른 묶음의 `/command`를 보내지 않는 안전 규칙. **실제 OMX(47bcb47)는 아직 문장만 받음** — 팀원 변경 필요. 계약 10.4.

관련 문서:
- `fms_emr_interface_2026-10-27.md`: FMS v1 연동 분석
- `emr_unused_apis_fms_v1_2026-10-27.md`: 필요 없어지는 API
- `omx_end_point_spec_2026-10-26.md`: OMX 완료 신호 명세

## 0. 한눈에

```
                      ┌──────── AMR (Pinky) ────────┐        ┌──── OMX (로봇팔) ────┐
EMR :8000 ──POST /api/v1/orders, /batches/{id}/ready·loaded──▶ FMS :8770 ──▶ Pinky
EMR :8000 ◀─POST /api/v1/fms/robot-status (1초) · /api/v1/fms/events── FMS
EMR :8000 ──POST /command(적재), POST /pinky(탑재), GET /status──────────────────────────────────────▶ OMX :8000 (192.168.129.86)
EMR :8000 ◀─GET /api/v1/robot/{request_id}/end-point──────────────────────────── OMX
```

| | AMR (Pinky) | OMX (로봇팔) |
|---|---|---|
| EMR이 직접 상대하는 쪽 | **팀원 FMS** (Pinky에 직접 붙지 않음) | **팀원 OMX API** |
| EMR → 상대 | 주문, `ready`·`loaded` | 적재 명령 `POST /command`, 탑재 명령 `POST /pinky`, 상태 `GET /status` |
| 상대 → EMR | 로봇 상태(1초), 이벤트 | 완료 신호 `GET /robot/{request_id}/end-point` |
| EMR이 맡는 것 | 무엇을 어디로 보낼지(신청), 결과 표시 | 언제 무엇을 실을지 명령, 끝났다는 신호를 FMS에 전달 |
| 상대가 맡는 것 | 배차·경로·교통·충전·오염 처리 | 집기·놓기 동작 |
| 인증 | 지금 없음 (정할 것) | 없음 |

## 1. AMR (Pinky, 팀원 FMS 경유)

### 1.1 지금 코드 — 로봇 전용 API `/api/v1/robot/...` (`app/api/v1/robot_access.py`)

로봇 쪽 프로그램이 EMR에서 배송을 가져가는 예전 방식이다. FMS v1에서는 쓰이지 않는다. 사용자 결정은 "남겨 두고 쓰지 않음"이다.

| API | 하는 일 | v1 뒤 |
|---|---|---|
| `POST /robot/deliveries/claim` | 배송 하나를 맡음. 그 전에 Pinky `/status`로 배터리·오염도 판정 | **막음** (`DELIVERY_DISPATCH=fms`면 204) |
| `GET /robot/deliveries` | 맡지 않은 예약 목록 | 안 씀 |
| `GET /robot/me` | 맡은 배송·수령 대기 시간 | 안 씀 |
| `POST /robot/arrived` | 약제실 도착(로그만, 10-27) | 안 씀 — FMS 이벤트 `robot_at_pharmacy` |
| `POST /robot/deliveries/{id}/progress` | 병실 도착·실패 보고 | **막음**. 안의 처리 `report_progress`는 이벤트 처리에서 다시 씀 |
| `POST /robot/deliveries/{id}/receipt` | 로봇이 마커로 수령 확인 | 안 씀 (간호사 "받았습니다") |

- 인증: 로봇별 키 `X-Robot-Api-Key`. 개발 스택은 `ROBOT_KEY_DISABLED=1`이라 꺼져 있다.
- 관련: `services/dispatch.py`, `services/robot_status.py`(Pinky 상태 판정), `clients/robot_server.py`(Pinky `GET /status`)

### 1.2 v1 뒤 — EMR → FMS (`clients/fms.py`, 새로 만듦)

| 요청 | 언제 | 본문·응답 |
|---|---|---|
| `POST /api/v1/orders` | 신청 시각이 되면 **물품 1개당 1건** | `{"request_id": "emr-d{배송}-s{비품}-{n}", "room": "101호", "item": "A 약품"}` → 202 새 주문 / 200 같은 `request_id`(다시 보내도 안전) |
| `POST /api/v1/batches/{id}/ready` | **OMX 적재 완료 신호**를 받으면(2.2, 10-27 사용자 시나리오) | 200 `{"status": "called", "eta_s": 32}` · 다시 보내면 409 `bad_batch_state` |
| `POST /api/v1/batches/{id}/loaded` | **OMX 탑재 완료 신호**를 받으면(2.2) | 200 `{"status": "delivering"}` · `at_pharmacy`가 아니면 409 |
| `DELETE /api/v1/orders/{id}` | 간호사가 취소할 때 | 200 · `queued`가 아니면 409 `order_locked` |
| `GET /api/v1/state` | EMR을 켤 때, 이벤트 `seq`가 빌 때 | 로봇 전부 + 끝나지 않은 주문·묶음 + `last_seq` |

- `room`은 방 번호(101호~108호, 수술실)다. EMR 장소 `robot_dest`를 방 번호로 바꾸고 103호·106호를 추가해야 한다.

### 1.3 v1 뒤 — FMS → EMR (`api/v1/fms_inbound.py`, 새로 만듦)

| EMR이 받는 곳 | 언제 | EMR이 할 일 |
|---|---|---|
| `POST /api/v1/fms/robot-status` | 1초마다, 로봇 전부 | 로봇마다 마지막 값을 덮어씀. **1초 안에 2xx** |
| `POST /api/v1/fms/events` | 일이 생길 때 1건씩 | `event_id`로 중복을 거르고 저장한 뒤 아래 표대로. **1초 안에 2xx**, 바깥 호출은 그 뒤에 |

로봇 상태 중 EMR이 쓰는 칸:

| 칸 | 쓰는 곳 |
|---|---|
| `robot` (1·2·3) | EMR 로봇과 잇기 — `robots.fms_robot_number` (EMR 1→1, 3→2, 4→3. EMR 2번은 OMX) |
| `pose {x, y, heading}` (cm, °) | 병원 지도 "Pinky 아레나"에 위치 표시 (cm/100 = m) |
| `battery`, `contamination` | 로봇 탭·지도 |
| `online`, `state`, `place`, `load`, `batch_id` | 로봇 탭·지도 |

AMR 이벤트와 EMR 배송 상태:

| 이벤트 | EMR 배송 상태 | 같이 하는 일 |
|---|---|---|
| `order_created` | reserved (보냄 표시) | `order_id` 저장 |
| `batch_assigned` | **dispatched** (로봇 = FMS 번호에 맞는 EMR 로봇) **OMX 적재 명령 (2.2)**, 간호사 알림 "곧 로봇이 출발합니다." |
| `robot_called`, `robot_departed`, `robot_arrived`, `batch_departed` | dispatched | 기록만 |
| `robot_at_pharmacy` | dispatched | **OMX 탑재 명령 (2.2)** |
| `order_delivered` | 신청의 물품이 모두 delivered면 **arrived** | "병동에 도착했습니다. 받아 주세요." → 간호사 버튼으로 received |
| `batch_completed` | — | 기록만 |
| `order_failed`, `robot_error` (시뮬레이터에 아직 없음) | **failed** | 재고 복구, 실패 알림 |
| `order_canceled` | cancelled | EMR 취소 확인 |

### 1.4 AMR에서 정할 것
- FMS로 보낸 뒤 간호사 취소: DELETE를 시도하고 409면 거절하는 안을 권함
- 신청 하나가 여러 묶음·로봇으로 나뉠 때 배송의 로봇 칸에 무엇을 적을지: 처음 배차된 로봇을 권함
- 5분 수령 마감을 없앨지. 로봇은 병실에서 한 바퀴 돈 뒤 1~5초 만에 떠난다
- FMS → EMR 인증. FMS가 다시 시작된 뒤 진행 중인 주문을 어떻게 맞출지

## 2. OMX (로봇팔, 팀원 OMX API `http://10.42.0.147:8000`)

### 2.1 지금 코드

| 방향 | API | 하는 일 | 코드 |
|---|---|---|---|
| 관리자 → EMR | `POST /api/v1/omx/command {"command": {"blue": n, "green": n}}` (10-27 형식 변경, 합계 1~3) | EMR이 `request_id`(`emr-YYYYMMDDTHHMMSS-xxxxxx`)를 만들어 OMX에 전달. **로봇팔이 움직인다** | `api/v1/omx.py` → `services/omx_control.py` → `clients/omx.py` |
| 관리자 → EMR | `GET /api/v1/omx/status` | OMX `GET /status`를 그대로 돌려줌 | 같음 |
| EMR → OMX | `POST /command {"command": {"blue": n, "green": n}, "request_id"}` | **색깔별 개수(10-27 사용자 결정)**. 예전 형식은 문장(`"pick and place green gauze"`)이었다. 팀원 `vision` 브랜치는 아직 문장 속 `blue`/`green`을 읽는다 → 팀원이 이 형식을 받게 바꿔야 한다 | `clients/omx.py` `send_command` |
| EMR → OMX | `GET /status` | state·phase·end_point 등 | `clients/omx.py` `get_status` |
| **OMX → EMR** | `GET /api/v1/robot/{request_id}/end-point` | 완료 신호. 인증 없음, 성공만, `request_id` 형식 `^[A-Za-z0-9._-]{1,64}$`. **지금은 로그만** | `api/v1/robot_access.py` → `services/omx_signal.py` |

- 관리자 API의 오류: OMX가 응답하지 않으면 503 `omx_unavailable`, OMX가 4xx를 주면 409 `omx_rejected`. 관리자만 쓸 수 있다(403 `admin_required`).
- OMX에는 그 밖에 `POST /pinky`(핑키 도착 → 양팔 집기·놓기), `/return`, `/next-stage`, `GET /end-point`, `/detection`이 있다. 지금 EMR은 쓰지 않는다. v1 뒤에는 `POST /pinky {"pinky_arrive": true, "request_id"}`를 탑재에 쓴다(2.2).

### 2.2 v1 뒤 — 약제실 시나리오 (AMR과 만나는 곳, 10-27 사용자 확정)

**적재(이미지) → 완료 → AMR 호출(ready) → 정밀 주차 → 탑재 → 완료 → loaded → 병실 이동.**

- **적재는 이미지(비전)로 한다**(10-27 사용자). 팀원 `vision` 브랜치(`eval_bi_api_yolo.py`, 커밋 `47bcb47`)에서 확인한 OMX 동작은 아래와 같다.
  - 지금은 `POST /command {"command": "pick and place blue gauze", "request_id": …}`(문장)를 받는다. EMR은 10-27부터 색깔별 개수 `{"blue": n, "green": n}`로 보내므로 팀원 쪽 변경이 필요하다.
  - 위 카메라 YOLO로 색(`blue` → `blue_gauze`, `green` → `green_gauze`)을 찾아 왼팔로 집어 놓고 시작 자세로 돌아간다.
  - **완료 신호 1**: 서버를 `--emr-api`로 띄우면 `GET {EMR}/robot/{request_id}/end-point`를 보낸다.
  - (`--pinky`) 이어서 양팔로 집어 들고 **시간 제한 없이** 기다린다.
  - `POST /pinky {"pinky_arrive": true, "request_id": …}`를 받으면 Pinky 위에 놓고 시작 자세로 돌아간다.
  - **완료 신호 2**: 같은 `request_id`로 end-point를 다시 보낸다.
- 작업 영역에 물품이 보이지 않으면 팔은 움직이지 않고 명령이 실패한다. **실패(`end_point: false`, `pinky_done: false`)는 EMR로 보내지 않는다.** OMX `GET /status`에만 남는다.

| # | 누가 | 무엇을 | API | EMR이 할 일·저장 |
|---|---|---|---|---|
| 0 | FMS → EMR | 배차 | 이벤트 `batch_assigned` (`batch_id`, `robot`, `orders`) | 배송 dispatched, 간호사 알림. Pinky는 제자리에서 기다림(로봇 `reserved`) |
| 1 | EMR → OMX | **적재**(이미지) 명령 | `POST /command {"command": {"blue": 2, "green": 1}, "request_id": "fms-b-5"}` | 묶음의 물품을 대응표(2.4)로 색깔별 개수로 바꿔 보냄. `request_id` ↔ `batch_id`를 저장, 단계 `preparing` |
| 2 | OMX → EMR | 적재 완료 (신호 1) | `GET /api/v1/robot/fms-b-5/end-point` | OMX `GET /status`의 `pinky`가 `grabbing`·`holding`이면 적재 완료로 본다 |
| 3 | EMR → FMS | **AMR 호출** | `POST /api/v1/batches/b-5/ready` → 200 `{"status": "called", "eta_s": 32}` | 단계 `called` |
| 4 | FMS·Pinky | 약제실로 가서 정밀 주차 | (FMS 안) | — |
| 5 | FMS → EMR | 정밀 주차 끝 | 이벤트 `robot_at_pharmacy` (`batch_id`, `robot`) | — |
| 6 | EMR → OMX | **탑재** 명령 | `POST /pinky {"pinky_arrive": true, "request_id": "fms-b-5"}` | 단계 `loading`. OMX는 들고 기다리던 물품을 놓는다(lift 전에 와도 기억했다가 놓음) |
| 7 | OMX → EMR | 탑재 완료 (신호 2) | `GET /api/v1/robot/fms-b-5/end-point` (같은 `request_id`) | OMX `GET /status`의 `pinky`가 `completed`면 탑재 완료로 본다 |
| 8 | EMR → FMS | **loaded** | `POST /api/v1/batches/b-5/loaded` → 200 `{"status": "delivering"}` | 단계 `delivering` |
| 9 | FMS·Pinky | 병실 이동, 병실마다 한 바퀴 | 이벤트 `batch_departed`, `order_delivered` … `batch_completed` | 1.3 표대로 arrived → 간호사 "받았습니다" |

```
FMS ──batch_assigned──▶ EMR ──POST /command {blue: 2, green: 1} (적재, 이미지)──▶ OMX
OMX ──end-point (fms-b-5) #1──▶ EMR ──POST /batches/b-5/ready──▶ FMS ──▶ Pinky: 약제실로, 정밀 주차
                                  (OMX는 양팔로 들고 기다림)
FMS ──robot_at_pharmacy──▶ EMR ──POST /pinky {pinky_arrive: true}──▶ OMX (Pinky 위에 놓음)
OMX ──end-point (fms-b-5) #2──▶ EMR ──POST /batches/b-5/loaded──▶ FMS ──▶ Pinky: 병실로
```

**두 완료 신호를 구분하는 법**
- OMX는 `/pinky`에 `/command`와 같은 `request_id`를 쓴다. 그래서 같은 주소로 **같은 `request_id`가 두 번** 온다.
- 신호가 오면 EMR이 OMX `GET /status`의 `pinky` 값을 본다.
  - `grabbing`·`holding`이면 적재 완료 → `ready`
  - `completed`면 탑재 완료 → `loaded`
- 저장한 묶음 단계로도 한 번 더 막는다: `preparing`일 때만 `ready`, `loading`일 때만 `loaded`. 같은 신호가 다시 와도 FMS에 두 번 보내지 않는다(FMS는 두 번째를 409로 거절 — 점검 문서 1번).
- 저장한 표에 없는 `request_id`(관리자가 손으로 보낸 명령 등)는 지금처럼 로그만 남긴다.

**그 밖의 규칙**
- **바깥 호출은 받은 요청 밖에서**: 완료 신호·FMS 이벤트를 받는 요청 안에서는 저장만 한다. OMX `GET /status`·`/pinky`와 FMS `ready`·`loaded` 호출은 뒤에서 한다.
- **실패는 EMR이 물어봐야 안다**: OMX는 실패를 EMR로 보내지 않는다. 그래서 단계 `preparing`·`loading`이 정한 시간(예: 2분)을 넘기면 EMR이 OMX `GET /status`를 보고 실패를 처리한다(배송 failed `robot_error`, 관리자 알림).
- **바뀐 결정**: 앞서 "ready는 배차 즉시 자동"이었다. 10-27 시나리오에서 **"ready는 OMX 적재 완료 뒤"**로 바꿨다. Pinky는 물품이 준비될 때까지 제자리에서 기다린다. FMS API.md의 원래 순서("batch_assigned → OMX 준비 → ready")와 같다.

| 묶음 단계 (EMR 저장) | 다음으로 넘어가는 계기 |
|---|---|
| `assigned` | EMR이 적재 명령을 보냄 → `preparing` |
| `preparing` | 완료 신호 1 + OMX `pinky` = `holding` → `ready` 보냄 → `called` |
| `called` | FMS `robot_at_pharmacy` → `/pinky` 보냄 → `loading` |
| `loading` | 완료 신호 2 + OMX `pinky` = `completed` → `loaded` 보냄 → `delivering` |
| `delivering` | FMS `batch_completed` → `completed` |
| `preparing`·`loading`에서 시간 초과 | OMX `/status` 확인 → `failed` |

### 2.3 OMX에서 정할 것
- **OMX가 새 형식을 받는지**: `{"command": {"blue": n, "green": n}}`를 받게 팀원 `vision` 서버를 바꿔야 한다. 개수가 2 이상일 때 한 명령으로 여러 개를 집는지도 함께 정한다.
- **묶음의 물품이 여러 개일 때**: 명령 하나가 한 색 물품 **하나**를 집는 것으로 보인다. FMS 묶음은 최대 3개다.
  - (가) 물품마다 `/command`를 차례로 보내고 마지막에 `/pinky`
  - (나) OMX가 한 명령으로 여러 개를 집게 바꿈
  - (다) 묶음 크기를 1로 제한해 달라고 FMS에 요청
- **OMX가 바쁠 때**: 다른 묶음의 물품을 들고 기다리는 동안 새 `/command`를 받는지. 받지 않으면 EMR이 묶음을 하나씩 차례로 처리해야 한다.
- **실패를 EMR로 보내기**: 지금은 성공만 온다. 실패 신호(예: `GET /robot/{request_id}/end-point?result=failed`)를 만들지, EMR이 `/status`를 묻는 방식으로 갈지
- **OMX 서버 실행 옵션**: `--emr-api http://10.42.0.1:8000/api/v1 --pinky --auto`로 띄워야 위 시나리오가 된다(`--pinky`가 없으면 탑재 단계가 없다)
- 완료 신호의 인증: 지금은 없다. 같은 망 누구나 `ready`·`loaded`를 일으킬 수 있다

### 2.4 OMX 물품 대응표 (10-27 사용자 결정: "약품 파란, 비품 녹색")

OMX가 이미지로 알아보는 것은 파란 거즈(`blue_gauze`)와 녹색 거즈(`green_gauze`) 두 가지뿐이다. 그래서 비품 하나하나가 아니라 **비품 종류(`supplies.category`)**로 색을 정한다. DB 칸은 더하지 않았다.

| EMR 비품 종류 | OMX 색 | 지금 비품 (10-27 DB) |
|---|---|---|
| 약품 `medication` | **blue** (파란 거즈) | A 약품, B 약품, C 약품, 주사제 |
| 비품 `supply` | **green** (녹색 거즈) | 이불, 매트리스 패드, 환자복, 실내화, 플라스틱 컵 |

- 코드: `emr/backend/app/services/omx_items.py`
  - `OMX_COLOR_BY_CATEGORY` 대응표
  - `omx_color(종류)`
  - `omx_counts([(종류, 수량), …])` → `{"blue": n, "green": n}`
  - 테스트 `tests/test_services/test_omx_items.py`: 비품 종류를 늘리면 대응표가 비어 테스트가 실패한다
- 명령 형식: `{"command": {"blue": n, "green": n}, "request_id": "…"}`
  - 두 색 모두 키를 보낸다(없으면 0). 합계는 1~3이다(Pinky 적재 한도, `schemas/omx.py` `OMX_MAX_ITEMS_PER_COMMAND` — `[검토 필요]` OMX가 한 번에 몇 개를 집는지 확인 전)
  - 관리자 API `POST /api/v1/omx/command`도 같은 모양 `{"command": {"blue": 1, "green": 0}}`을 받는다. 예전 문장 형식은 422다
- 예: 묶음 = A 약품 2개(101호) + 환자복 1개(104호) → `{"blue": 2, "green": 1}`

## 3. 코드 배치 제안 (구현할 때)

지금은 AMR용 로봇 API와 OMX 완료 신호가 `robot_access.py` 한 파일에 섞여 있다. 종류별로 나눈다. **바깥 경로는 바꾸지 않는다**(팀원 OMX가 이미 `/api/v1/robot/{request_id}/end-point`를 부른다).

| 파일 | 담는 것 |
|---|---|
| `api/v1/robot_access.py` | 예전 AMR 로봇 API 6개만 (막음, 나중에 지움) |
| `api/v1/fms_inbound.py` (새로 만듦) | AMR: FMS가 보내는 `/fms/robot-status`, `/fms/events` |
| `api/v1/omx_access.py` (새로 만듦) | OMX: 완료 신호 `GET /robot/{request_id}/end-point`(경로 그대로, `robot_access.py`에서 옮김) |
| `api/v1/omx.py` | OMX: 관리자 명령·상태 (그대로) |
| `clients/fms.py` (새로 만듦), `clients/omx.py` | 바깥 호출 |
| `services/fms_order.py`·`fms_events.py` (새로 만듦), `services/omx_signal.py`·`omx_control.py` | 업무 규칙 |

- 라우터 등록(`api/router.py`) 태그도 `amr-legacy`, `fms`, `omx`로 나눈다. 그러면 `/docs` 화면에서도 갈라져 보인다.
