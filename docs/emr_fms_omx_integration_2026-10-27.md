# EMR ↔ FMS·OMX 연동 — 2026-10-27 작업 정리

- 대상: EMR·FMS·OMX 팀원, 이어서 작업할 Claude.
- 오늘 무엇을 정했고, 무엇을 만들었고, 무엇을 시험했고, 무엇이 남았는지를 한 장으로 정리한다.
- 기준 문서: API 계약은 [`api_contract_delivery_2026-10-20.md`](api_contract_delivery_2026-10-20.md) **10장**, 분석은 [`fms_emr_interface_2026-10-27.md`](fms_emr_interface_2026-10-27.md).

## 1. 오늘 정한 것 (사용자 결정)

| 항목 | 결정 |
|---|---|
| EMR의 위치 | **EMR은 상위 관제**다. 바깥 연결은 **팀원 FMS와 팀원 OMX 둘뿐**이다. Pinky에 직접 붙지 않고, 로봇도 EMR을 직접 부르지 않는다 |
| 역할 | EMR = 무엇을 어디로 보낼지(신청·주문)와 결과 표시. FMS = 배차·경로·교통·충전. OMX = 집기·내려놓기 |
| 예전 로봇 API (claim 등) | 남겨 두고 쓰지 않는다. FMS를 켜면 claim은 늘 204 |
| FMS ↔ EMR 인증 | 없이 진행한다(예정) |
| FMS `ready`·`loaded` 두 번째의 409 | FMS는 그대로 둔다. EMR이 "이미 넘어감"으로 받아들인다 |
| `order_failed`·`robot_error` | 시뮬레이터에 없으므로 시험에서는 무시한다(처리 코드는 있음) |
| 1초 응답 제한 | 신경 쓰지 않는다. `event_id`로 한 번만 처리하고, 올바른 이벤트에 4xx를 주지 않는다 |
| 장소·지도를 FMS `/rooms`·`/map`에서 | 아직 하지 않고 문서만 둔다 |
| EMR 장소 | FMS 방 번호와 똑같이 맞춘다(101호~108호, 수술실) |
| 구현 범위 | 1단계 "배송 단계 변경에 필요한 최소만" → 2단계 "OMX만 실제로" |
| 마이그레이션 | 0015·0016을 새로 쓴다. 보관 브랜치 `fms-order-2026-10-26`은 합치지 않는다 |
| OMX `/pinky` | **Pinky 정밀 주차가 끝난 뒤 내려놓기** |
| OMX 명령 형식 | **`POST /command {"command": {"blue": N, "green": N}, "request_id"}`**, FMS 묶음 하나에 한 번. 약품 → blue, 비품 → green |

## 2. 만든 것 (EMR, 커밋 `a0ef883`)

### 2.1 흐름

```
간호사 신청 ─(신청 시각)─▶ EMR ─POST /api/v1/orders (물품 1개 = 주문 1건)─▶ FMS
FMS ─batch_assigned─▶ EMR: 신청 → 출발(dispatched)
EMR ─POST /command {"blue": N, "green": N}─▶ OMX 집기 → 양팔로 들고 대기
EMR ─POST /batches/{id}/ready─▶ FMS ─▶ Pinky 약제실로, 정밀 주차 ─robot_at_pharmacy─▶ EMR
EMR ─POST /pinky─▶ OMX 내려놓기 → 시작 자세
EMR ─POST /batches/{id}/loaded─▶ FMS ─▶ Pinky 병실로 ─order_delivered─▶ EMR: 신청의 물품이 모두 배송되면 도착(arrived)
간호사 "받았습니다" → 받음(received)
```

### 2.2 API

| 방향 | API | 비고 |
|---|---|---|
| EMR → FMS | `POST /api/v1/orders {request_id: "emr-d{배송}-s{비품}-{n}", room: "101호", item}` | 5초마다. 같은 `request_id`는 FMS가 처음 주문을 돌려줌 |
| EMR → FMS | `POST /api/v1/batches/{id}/ready`, `…/loaded` | 409 `bad_batch_state` = 이미 넘어감 |
| FMS → EMR | `POST /api/v1/fms/robot-status` | 1초마다. 10-29부터 로봇마다 마지막 위치를 메모리에 두고 병원 지도에 그린다(`GET /api/v1/robot-positions`) |
| FMS → EMR | `POST /api/v1/fms/events` | `batch_assigned` → 출발, `order_delivered`(전부) → 도착, `order_failed` → 실패, `robot_at_pharmacy` → 정밀 주차 시각. 올바른 JSON이면 늘 200 |
| EMR → OMX | `POST /command {"command": {"blue": N, "green": N}, "request_id": "emr-b{id}"}` | OMX가 움직이거나 들고 있으면 보내지 않음(안전) |
| EMR → OMX | `POST /pinky {"pinky_arrive": true, "request_id"}` | 정밀 주차 뒤에만 보냄 |
| EMR → OMX | `GET /status` | 끝났는지 판단(`state`, `pinky`) |
| OMX → EMR | `GET /api/v1/robot/{request_id}/end-point` | 집기 끝·내려놓기 끝에 두 번 온다. 로그만 남긴다 |
| 간호사 | FMS에 보낸 신청을 변경·취소하면 409 `delivery_sent_to_fms` | FMS 취소 연동 전까지 |

### 2.3 코드·DB·설정

| 종류 | 내용 |
|---|---|
| 새 파일 | `api/v1/fms_inbound.py`, `clients/fms.py`, `services/fms_order.py`(주문 보내기), `services/fms_events.py`(이벤트 → 단계), `services/fms_omx.py`(OMX로 싣기), `services/omx_items.py`(약품 → blue, 비품 → green), `models/fms_order.py`, `models/fms_batch.py`, `repositories/fms_order.py` |
| 바뀐 파일 | `main.py`(주기 작업 2개), `dispatch.py`(FMS를 켜면 claim 막음), `delivery.py`(보낸 신청 변경·취소 막음), `clients/omx.py`(`/pinky`), `config.py`, `docker-compose.yml`, `.env.example`, `errorMessages.ts` |
| 마이그레이션 | **0015** `fms_orders` + "로봇 한 대 = 진행 중 배송 하나" 인덱스 없앰(FMS 묶음에 여러 신청이 실림). **0016** `fms_batches`. 둘 다 운영 DB에 적용함 |
| 설정 | `FMS_BASE_URL`(빈 값 = 끔), `FMS_ROBOT_MAP`(FMS 1·2·3 → EMR 로봇 1·3·4, `[검토 필요]`), `FMS_OMX_ENABLED`(기본 0, 1이면 로봇팔이 움직임), `OMX_COMMAND_FORMAT`(기본 `counts`) |
| 임시 스위치 | `OMX_COMMAND_FORMAT=sentence`이면 개수 대신 문장 `"pick and place blue gauze"` 하나를 보낸다(수량 무시). 관리자 API도 문장을 받는다. **오늘 시험 뒤 끔** — 끄면 문장은 400 `omx_sentence_disabled` |
| 데이터 | EMR 장소 7곳의 `robot_dest`를 방 번호로, 이름을 FMS 이름으로 바꿈. 103호·106호 새로 만듦. 장소 "약제실 OMX" → "약제실" |
| 테스트 | **232개 통과**(FMS 1단계 9개, OMX 2단계 5개, 관리자 OMX 문장 1개 포함). 프론트 타입 검사·린트 통과 |

## 3. 시험한 것

| 시험 | 조건 | 결과 |
|---|---|---|
| OpenAPI 대조 | 받은 JSON과 저장소 `fms/openapi_v1.py` 비교 | 완전히 같음 |
| 이벤트 모양 | 시뮬레이터 주문 7건 | 10종 모두 API.md 표와 같음. 이벤트가 평균 1.1초 늦게 옴 |
| 흉내 스크립트 | EMR 실제 신청 2건 / 물품 10개 | 모두 도착, 오류 0. 묶음 4개, 로봇이 스스로 오염 처리·주차 |
| 물품 25개 | 사용자 시뮬레이터 | **9초 만에 시뮬레이터가 다시 시작되어 중단**. 주문 25건이 알림 없이 사라짐 → "FMS 다시 시작 대응"이 꼭 필요함을 확인 |
| **EMR 1단계** | 실제 EMR + 시뮬레이터(가상 OMX) | NO 55·56·57 신청 → 출발 → 도착. NO 57(4개)은 로봇 두 대로 나뉘어도 4개가 모두 배송된 뒤 도착 |
| **실물 OMX 단독** | 관리자 API 문장 명령 | 1차: 집기 성공, 양팔 들기 실패(오른팔 `/dev/omx_follower` 없음). 2차: 집기 → 들기 → 내려놓기 → 시작 자세, 완료 신호 두 번 모두 EMR 도착 |
| **EMR + 시뮬레이터 Pinky + 실물 OMX** | 약품 2개, 문장 형식 | **NO 59**: 신청 → 도착 1분 35초. Pinky가 OMX보다 먼저 도착 → `/pinky` `accepted: false` → OMX가 기억했다가 내려놓음. **NO 60**: 1분 50초. OMX가 먼저 들고 대기 → `/pinky` 바로 받음. 두 경우 모두 오류 0 |

- 문장 형식이라 신청은 2개였지만 OMX는 1개만 집었다.
- 시험 중 고친 것: OMX 연동을 꺼도 정밀 주차 이벤트가 새 표를 조회하던 것, 개발 `.env` 값에 따라 기존 시험이 깨지던 것(시험에서는 FMS·OMX를 기본으로 끔).

## 4. 지금 켜져 있는 것 (시험용)

| 무엇 | 값 | 끄는 법 |
|---|---|---|
| `emr/.env` `FMS_BASE_URL` | `http://172.18.0.1:8770` | 줄 삭제 → `docker compose up -d api` |
| `emr/.env` `FMS_OMX_ENABLED` | `1` — 이제 개수 형식이라 **실제 OMX가 422로 거절**하고 묶음이 실패로 멈춘다(팔은 안 움직임) | 같음 |
| 중계 프로그램 | 172.18.0.1:8770 → 127.0.0.1:8770 (시뮬레이터가 127.0.0.1에서만 들어서) | 프로세스 종료. FMS를 `--host 0.0.0.0`으로 띄우면 필요 없음 |
| 시뮬레이터 | `control_url = http://127.0.0.1:8000`, 가상 OMX 꺼짐 | 시뮬레이터 화면 또는 `POST /api/control` |

### 4.1 OMX 주소 변경 (2026-10-28)

- 팀원 OMX가 **`10.42.0.147:8000`**으로 옮겼다(예전 `192.168.129.86`). 이 PC는 그 망에서 **`10.42.0.1`**(`enp130s0`, NetworkManager **shared** 연결)이다.
- **EMR 컨테이너 → OMX는 바로 닿지 않는다**: shared 연결의 방화벽이 도커 컨테이너에서 `10.42.0.x`로 가는 새 연결을 거절한다(`Connection refused`). 이 PC 자체는 닿는다.
  - 지금: 이 PC의 시험용 중계 `172.18.0.1:18000 → 10.42.0.147:8000` + 개발 `.env` `OMX_BASE_URL=http://172.18.0.1:18000`. 확인: EMR `GET /api/v1/omx/status` → OMX `idle`, 개수 형식 명령은 OMX가 422(아직 문장만) → EMR 409 `omx_rejected`, 팔은 안 움직임.
  - 중계 없이 하려면(sudo 필요): shared 연결 방화벽에 도커 망(172.18.0.0/16) → `enp130s0` 허용을 넣거나, OMX를 다른 망에 두거나, api 컨테이너를 host 네트워크로. 정해지면 `.env` 두 줄을 지운다.
- **OMX → EMR 완료 신호**: OMX는 `--emr-api http://10.42.0.1:8000/api/v1`(그 망에서 본 EMR 주소). 10-28 명령 한 번으로 확인 — 집기 → 들기, 완료 신호가 EMR에 도착.
- **Pinky `10.42.0.79`**(Pinky API `:8080`): `localized`·`nav2_ready`·`idle` 확인. 사용자 요청으로 도착 신호 설정 `PUT /notify`의 주소를 `http://192.168.129.135:8000/api/v1/robot/arrived` → **`http://10.42.0.1:8000/api/v1/robot/arrived`**로 바꿈(대상 PHARMACY 그대로). 이 길(Pinky → EMR `/robot/arrived`)은 예전 방식이라 EMR은 로그만 남기고, 맡은 배송이 없으면 409를 준다(Pinky는 4xx를 다시 보내지 않음).

## 4.2 2026-10-28 이어서 한 것

**사용자 결정**

| 항목 | 결정 |
|---|---|
| OMX 주소 | `10.42.0.147:8000`(EMR 기본값 변경). 이 PC는 그 망에서 `10.42.0.1` |
| 실물 Pinky 주행 코드 | **작성하지 않는다** — FMS가 미완성(가상만)이라. 실물 주행은 사용자가 그때그때 요청한 한 번짜리 명령만 |
| 명령의 0개 색 | **뺀다** — `{"blue": 0, "green": 1}` → `{"green": 1}` |
| OMX가 양식을 받지 않으면(422) | OMX 싣기를 **생략**하고 `ready` → 정밀 주차 → `loaded` |
| 내려놓기 시점 | **정밀 주차 완료 후** — FMS가 가상인 동안은 실물 Pinky의 `POST /robot/arrived`를 신호로(`FMS_PHARMACY_SIGNAL=pinky`). FMS가 AMR을 직접 API로 몰게 되면 FMS `robot_at_pharmacy`(`fms`)로 |

**EMR 변경**: `OMX_BASE_URL` 기본값·compose 설정, `omx_items.omx_command`(0개 색 빼기), `fms_omx.py`(422 생략, `loaded` 전에 FMS `GET /batches/{id}`가 `at_pharmacy`인지 확인), `fms_events.pinky_docked_at_pharmacy`·`/robot/arrived`(실물 Pinky 신호), `clients/fms.get_batch`. 테스트 236개 통과.

**실물 시험 (이 PC에서 직접 부른 한 번짜리 명령 + EMR 흐름)**

| 시험 | 결과 |
|---|---|
| EMR → OMX(중계 `172.18.0.1:18000`), OMX → EMR(`10.42.0.1`) | ✅ 명령 한 번: 파란 거즈 집기 → 들기 → 완료 신호 EMR 도착 |
| 실물 Pinky `10.42.0.79` → 약제실 | 1차: 정밀 주차 "앞이 막혀 멈춤"(앞으로 4~5 cm 남음) · 2차·3차: ✅ 오차 8 mm 안 |
| Pinky 도착 신호 주소 `PUT /notify` → `http://10.42.0.1:8000/api/v1/robot/arrived` | ✅ 정밀 주차 뒤 EMR 도착(예전 경로라 409) |
| OMX 내려놓기 → Pinky 위 | ✅ 완료 신호 두 번 |
| 약제실 → 101호 | ✅ 오차 1.6 cm |
| 101호 → A | ❌ 병실에서 나올 때 Nav2 104, 다시 하니 **왼쪽 협로 `contact`(벽 0.9 cm)**, 벽에 붙어 재시도 불가 → 손으로 옮긴 뒤 `set_pose find`로 위치 다시 잡음(벽 96%) |
| **EMR 흐름 NO 63(녹색 1)** | 팀원 OMX가 **개수 형식을 받게 바뀜**(`green:1`). 실물 팔 집기 → 가상 Pinky 정밀 주차에 맞춰 내려놓음(실물 Pinky는 늦게 도착 — 자리 비어 있음) → 도착. 이 일로 "내려놓기 = 실물 정밀 주차 뒤" 결정 |
| EMR 흐름 NO 64·65 | FMS가 한 묶음 `{"blue": 1, "green": 1}`으로 묶음 → OMX "green_gauze not found"(녹색 거즈를 NO 63에서 이미 씀) → 묶음 실패로 멈춤(설계대로). 둘 다 출발에 멈춰 있음 |

**팀원에게**: 왼쪽 협로 벽 따라가기(기록 `/home/pinky/pinky_map_rev3/api/logs/corridor_1028_121032.npz`), 병실 나오는 구간 Nav2 104, FMS가 실물을 몰기(`--real`) 전까지 EMR은 `FMS_PHARMACY_SIGNAL=pinky`.

**지금 켜져 있는 것**: `.env` `FMS_BASE_URL`, `FMS_OMX_ENABLED=0`(실물 팔 꺼 둠), `OMX_BASE_URL=http://172.18.0.1:18000`(중계), `FMS_PHARMACY_SIGNAL=pinky` · 중계 프로그램 2개(OMX `:18000`, 이전 FMS `:8770`은 FMS가 `0.0.0.0`으로 떠서 필요 없음).

## 5. 남은 것

**팀원에게**

| 대상 | 요청 |
|---|---|
| OMX | `/command`가 `{"blue": N, "green": N}`를 받게 바꾸기. 한 명령으로 N개를 집는지도 정하기. 지금(`vision` 47bcb47)은 문장만 받아 개수 형식이면 422 |
| OMX | 들고 있는 동안(`holding`) 새 `/command`를 거절하기. 지금은 받아서 왼팔이 움직인다 |
| OMX | 실행 옵션 `--pinky --emr-api http://10.42.0.1:8000/api/v1`, 오른팔 연결 확인 |
| FMS | 다시 시작했음을 알리기(시작 시각·세대 번호). 실제 FMS 주소, `--host 0.0.0.0` |
| FMS | 실패·시간 초과 흐름(`order_failed`·`robot_error`), 모든 이벤트에 `request_id`(급하지 않음) |

**EMR에서**
- FMS 다시 시작 대응(진행 중인 신청이 출발에 멈춤)
- FMS 취소 연동(`DELETE /orders`)
- OMX 시간 초과
- 로봇 위치를 지도에 표시: 1초마다 오는 `robot-status`를 Pinky 아레나 지도에 그대로 그릴 수 있음을 확인함. 방식은 사용자가 고르기 전
- 예전 로봇 API·Pinky 직접 연결 코드 지우기(v1이 실물로 돈 뒤)
- 커밋
