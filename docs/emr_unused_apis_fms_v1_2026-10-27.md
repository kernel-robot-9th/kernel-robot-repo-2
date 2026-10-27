# FMS API v1 연동 뒤 EMR에서 필요 없어지는 API (2026-10-27)

> **EMR은 상위 관제다 (2026-10-27 사용자).** EMR이 붙는 바깥 시스템은 **팀원 FMS**(AMR·Pinky 담당)와 **팀원 OMX API**(로봇팔) **둘뿐**이다. Pinky 등 로봇에 직접 붙지 않고, 로봇도 EMR을 직접 부르지 않는다. 배차·경로·교통·충전은 FMS, 집기·놓기는 OMX가 한다. 아래 목록은 이 원칙에서 벗어나는 길 — **로봇이 EMR을 직접 부르는 길**과 **EMR이 Pinky에 직접 붙는 길**이다.

팀원 FMS API v1(`kernel-robot-repo-2/fms/API.md`)로 바꾸면 EMR과 로봇 사이에서 오가는 것이 둘로 줄어든다.
- EMR → FMS: 주문, `ready`·`loaded`
- FMS → EMR: 로봇 상태, 이벤트

로봇이나 로봇 쪽 프로그램이 EMR을 직접 부르는 API는 더 이상 쓰이지 않는다. 이 문서는 그런 API와 딸린 코드·설정·화면을 정리한다.
연동 분석은 `fms_emr_interface_2026-10-27.md`에 있다.

- **사용자 결정 (10-27)**: 예전 로봇 API는 **남겨 두고 쓰지 않는다.** 그래서 1단계는 막기만 하고, 지우는 것은 FMS 연동이 실제로 돈 뒤에 따로 정한다(5장).
- 이 문서는 정리 목록이다. **10-27 저녁 적용한 것**: FMS를 켜면(`FMS_BASE_URL`, 이 문서의 `DELIVERY_DISPATCH=fms` 대신) `claim`이 늘 204 — 1단계 '막기' 중 claim만. `progress`·로봇 `receipt` 409와 화면 숨김은 아직. 나머지 코드는 그대로다.

## 1. 필요 없어지는 API

### 1.1 로봇 전용 API `/api/v1/robot/...` (`app/api/v1/robot_access.py`)

| API | 지금 하는 일 | v1에서 대신하는 것 | 1단계 (막기) |
|---|---|---|---|
| `POST /robot/deliveries/claim` | 로봇이 배송 하나를 맡음(배정). 그 전에 Pinky `/status`를 물어 판정 | FMS 배차 → 이벤트 `batch_assigned` | **설정 `DELIVERY_DISPATCH=fms`면 늘 204.** 막지 않으면 같은 배송을 두 흐름이 같이 바꿈 |
| `GET /robot/deliveries` | 맡지 않은 예약 목록 | EMR이 `POST /orders`로 보냄 | 그대로 둬도 상태를 바꾸지 않음. 문서에서만 뺌 |
| `GET /robot/me` | 이 로봇이 맡은 배송·수령 대기 시간 | FMS `GET /api/v1/state`, 이벤트 | 그대로 둬도 무해 |
| `POST /robot/arrived` | 약제실 도착 알림, 로그만(10-27 오전에 바꿈) | 이벤트 `robot_at_pharmacy` | 그대로 둬도 무해(상태를 바꾸지 않음) |
| `POST /robot/deliveries/{id}/progress` | 병실 도착·실패 보고 | 이벤트 `order_delivered`·`order_failed` | **API는 막고 안의 처리(`DispatchService.report_progress`)는 이벤트 처리에서 그대로 씀** |
| `POST /robot/deliveries/{id}/receipt` | 로봇이 일회용 마커를 읽어 수령 확인 | 간호사 "받았습니다"(`POST /deliveries/{id}/receipt`) | 이미 쓰지 않음(`NURSE_RECEIPT_METHOD=button`) |

**남기는 것**: `GET /robot/{request_id}/end-point`(OMX 완료 신호). v1에서는 이 신호를 받아 FMS에 `loaded`를 보낸다.

### 1.2 로봇 관리 API `/api/v1/robots/...` (`app/api/v1/robots.py`) 중 일부

| API·칸 | 지금 하는 일 | 필요 없어지는 이유 |
|---|---|---|
| `POST /robots/{id}/api-key`, `DELETE /robots/{id}/api-key` | 로봇별 키 발급·폐기 (`X-Robot-Api-Key`) | 로봇이 EMR을 부르지 않는다. FMS가 보내는 곳의 인증은 따로 정한다(FMS 공유 키 등) |
| `PATCH /robots/{id}`의 `robot_server_url` | claim 때 EMR이 Pinky `/status`를 직접 부를 주소 | EMR이 로봇에 직접 붙지 않는다. 상태는 FMS가 보낸다 |
| 응답의 `has_api_key`, `api_key_issued_at`, `robot_server_url` | 위 두 기능 표시 | 같은 이유 |

**남기는 것**: `GET /robots`, `GET /robots/{id}`, 등록·이름 수정·삭제. 여기에 `fms_robot_number`와 위치 칸이 새로 붙는다.

### 1.3 배송 API 중 일부 (`app/api/v1/deliveries.py`, `app/services/delivery.py`)

| 무엇 | 지금 | 필요 없어지는 이유 |
|---|---|---|
| 로봇 전용 장소로 물품 없이 신청 (`robot_only` 장소, `receipt_method: none`) | 충전소 등으로 **로봇 이동**을 EMR 신청으로 만든다 | 충전·대기·오염 처리는 FMS가 스스로 한다. 로봇 전용 장소는 신청 목적지에서 빼기만 하면 된다 |

## 2. 그대로 남기는 API (참고)

| API | 이유 |
|---|---|
| `GET /robot/{request_id}/end-point` | OMX 완료 신호 → FMS `loaded` |
| `POST /omx/command`, `GET /omx/status` (관리자) | OMX를 손으로 시험할 때 |
| `POST /deliveries/{id}/receipt` (간호사 "받았습니다") | v1에서 arrived → received |
| 병상 `POST /bedside/requests`, `POST /bedside/deliveries/{id}/receipt` | 신청·수령은 EMR 몫. 병상 신청도 같은 방식으로 FMS에 보낸다 |
| 간호사 배송·비품·장소·맵·로봇 조회 API | EMR 고유 기능 |

## 3. 같이 필요 없어지는 코드·설정·스크립트·화면

| 종류 | 대상 | 비고 |
|---|---|---|
| 서비스 | `services/robot_status.py` (`RobotStatusService.check_before_claim`, Pinky 상태로 배정 판정) | 판정은 FMS가 한다 |
| 클라이언트 | `clients/robot_server.py` (Pinky `GET /status`) | EMR이 Pinky에 직접 붙는 길. EMR은 FMS·OMX만 부른다 |
| 서비스 | `services/dispatch.py`의 `claim`, `list_waiting`, `overview`, `report_at_pharmacy`, `confirm_receipt` | 배정 부분은 `dispatch_to_robot`으로 떼어 v1 이벤트 처리에서 다시 씀. `report_progress`는 남김 |
| 리포지토리 | `repositories/delivery.py`의 `lock_next_claimable`, `list_waiting` | claim 전용 |
| 인증 | `core/deps.py`의 `get_current_robot`, `CurrentRobot`, `ROBOT_RESPONSES` | 로봇 키 인증 |
| DB 칸 | `robots.api_key_hash`, `api_key_issued_at`, `robot_server_url`, `home_location_id`(10-27부터 안 씀) | 지우려면 마이그레이션이 필요하다. 1단계에서는 남김 |
| 설정 (`core/config.py`) | `ROBOT_KEY_DISABLED`, `ROBOT_KEY_DISABLED_AS`, `CLAIM_MIN_BATTERY_PERCENT`, `CLAIM_MAX_CONTAMINATION_PERCENT`, `ROBOT_SERVER_TIMEOUT_SECONDS` | `.env`의 `ROBOT_KEY_DISABLED=1`도 |
| 설정 | `NURSE_RECEIPT_METHOD=marker` 경로 | 로봇이 마커를 읽지 않으면 마커 수령은 쓸 일이 없다. 일회용 마커는 DB 규칙(arrived엔 마커) 때문에 계속 만든다 |
| 스크립트 (`scripts/`) | `simulate_robot.py`(로봇 흉내: me·claim·arrive·receipt), `confirm_receipt.py`(마커 수령), `import_pinky_dests.py`(Pinky `/dests`로 장소 만들기 — EMR이 Pinky에 직접 붙는 길) | v1 시험은 팀원 시뮬레이터 `fms/sim_server.py --control-url`로 한다. 장소는 방 번호로 손으로 고친다 |
| 화면 | `features/robots/RobotApiKeyDialog.tsx`, `pages/Sites.tsx` 로봇 탭의 키 발급 버튼·로봇 서버 칸·배터리/오염도 열(claim 때 값) | 로봇 탭은 FMS 번호·온라인·위치로 바뀐다 |
| 화면 | `api/errorMessages.ts`의 claim·로봇 키 오류 안내 | `robot_key_*`, `robot_not_amr`, `robot_no_active_delivery`, `robot_server_*`, `robot_battery_low` 등. 화면에 뜰 일이 없다 |
| 테스트 | `tests/test_api/test_dispatch.py`(claim·arrived·progress), `test_robot_status.py`, `test_services/test_robot_server.py`, `test_delivery_receipt.py`의 로봇 마커 수령 | 막기 단계에서는 "스위치가 켜지면 claim이 204" 시험을 더한다 |

### 지금도 이미 쓰이지 않는 코드
- `services/quick_dispatch.py`
  - 10-22 시험용 v2 간단 API의 서비스다.
  - 그 API 파일(`api/v2/quick.py`)은 없어졌고, 이 서비스를 부르는 곳이 없다(10-27 `grep` 확인).
  - FMS 연동과 상관없이 지워도 된다.

## 4. 오류 코드 (FMS 연동 뒤 나오지 않음)

- **claim**:
  - `robot_not_amr`
  - `robot_server_not_set` · `robot_server_unreachable` · `robot_status_incomplete` · `robot_not_ready` · `robot_battery_low` · `robot_contamination_high` (204 헤더)
- **로봇 진행 보고**: `robot_no_active_delivery`, `delivery_not_assigned_to_robot`
  - `delivery_invalid_transition`·`delivery_already_received`는 이벤트 처리 안에서 계속 쓸 수 있다
- **마커**: `receipt_marker_not_for_delivery`, `receipt_marker_exhausted`, `delivery_receipt_by_button`
- **로봇 키**: `robot_key_missing`, `robot_key_invalid`

## 5. 정리 순서

| 단계 | 언제 | 할 일 |
|---|---|---|
| 1. 막기 | FMS 연동 코드와 같은 작업 | `DELIVERY_DISPATCH=fms`면 `claim`은 204, `progress`·`receipt`(로봇)는 409. 화면에서 로봇 키·로봇 서버 칸 숨김. 문서에서 "쓰지 않음" 표시 |
| 2. 지우기 | 팀원 시뮬레이터, 그다음 실물 Pinky로 v1이 실제로 돈 뒤 (사용자 결정) | 1~3장의 코드·설정·스크립트·화면·테스트 삭제. DB 칸 삭제 마이그레이션. `quick_dispatch.py`는 지금 지워도 됨 |

- 지울 때는 계약 문서 `docs/api_contract_delivery_2026-10-20.md`를 먼저 고친다(루트 CLAUDE.md 규칙).
- `dispatch.py`는 `report_progress`(도착 마커·알림·기록·재고 복구)를 v1 이벤트 처리가 쓰므로 통째로 지우지 않는다.

## 6. 대신하게 되는 문서

v1 연동 문서가 생기면 아래 문서는 머리에 "예전 방식(claim)"을 표시한다.

| 문서 | 내용 |
|---|---|
| `docs/fms_emr_api_2026-10-27.md` (+ 공유 페이지 https://claude.ai/artifact/TH6bZL1EVRRimPxnGxGrns) | 10-27 오전 claim 방식 정리 |
| `docs/emr_robot_api_for_teammate_2026-10-22.md` | 10-22 팀원 FMS 안내(claim) |
| `docs/emr_robot_data_format/README.md` | 10-23 로봇 API 6개 형식 |
