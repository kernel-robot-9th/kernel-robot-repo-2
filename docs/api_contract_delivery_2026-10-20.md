# 배송 배정·진행 API 계약 — EMR ↔ 관제 PC 배송 실행기 (2026-10-20)

- **역할 분담 (2026-10-23, 사용자 결정)**: 우리(EMR)는 배송을 **시퀀스·미션**으로 만들어 **누가 어떤 Task를 받는지**까지만 정한다. **주행·경로 계획은 팀원**(Pinky API `/goto`·`/plan`, OMX API)이 한다. **우리가 만든 시험용 배송 실행기 `robot/src/fms/delivery_executor`는 쓰지 않는다**(띄우지도, 고치지도 않음 — 코드만 남김). 4장(실행기 동작)은 참고용으로만 남긴다. 팀원 쪽 연동 안내: `docs/emr_robot_api_for_teammate_2026-10-22.md`.
- 환자(병상 단말) 배송 추가(2026-10-22): 8장.
- **로봇 상태(배터리·오염도)로 claim 검사 (2026-10-23, 사용자 결정)**: claim할 때마다 **EMR이 로봇 서버(팀원 Pinky API)의 `GET /status`를 물어** 기준 밖이면 새 배송을 주지 않는다(3.2·3.6). 오염도는 로봇이 재는 0~100. 같은 날 잠깐 있던 로봇 보고 방식(`POST /robot/status`)은 "팀원도 서버가 있으니 로봇에 정확한 정보를 요청해야"로 없앴다.
- **2026-10-22 변경 (사용자 결정)**: ① 수령 마커는 **일단 끔** — 간호사 배송도 화면의 **"받았습니다" 버튼**으로 수령(EMR 설정 `NURSE_RECEIPT_METHOD=button`, 기본). 마커 코드는 남아 있어 `marker`로 되살린다(2·3.4·5장). ② 실행기 주행은 **팀원 Pinky API(로봇 `:8080`)**, **인증 없이** 진행 — 운영 전에 인증을 넣는다(4장, 분석 `docs/pinky_fms_api_review_2026-10-22.md`).
- 구현(2026-10-20): EMR 마이그레이션 0008·`app/services/dispatch.py`·`delivery_notifier.py`·배송 화면, 관제 PC `robot/src/fms/delivery_executor`. 실제 EMR + 가짜 Nav2(도메인 77)로 확인, **실물 Pinky 종단 시험은 비품실 모방학습이 끝난 뒤**.
- 범위: EMR 로드맵 2단계(배송 배정·진행) + 간호사 알림(5단계 일부). 양쪽(`emr/`, `robot/src/fms/delivery_executor`)이 이 문서를 기준으로 구현한다. 바꿀 때는 이 문서부터 고친다.
- 사용자 결정(2026-10-20): 로봇 쪽이 EMR을 조회(claim) · 예약 시각이 지난 것부터 한 건씩 · 적재 없이 출발 · 수령은 **알림에 뜨는 일회용 마커를 로봇이 읽어서만** · 실패하면 재고 자동 복구 · 도착 후 5분 미수령이면 실패 + 복귀.

- **2026-10-27 FMS API v1 연동 1단계 (사용자 결정: "단계 변경에 필요한 최소만", 마이그레이션 0015 새로·보관 브랜치는 합치지 않음)**: 10장. FMS를 켜면(`FMS_BASE_URL`) 3장 claim은 늘 204(줄 것 없음)로 막힌다 — EMR은 FMS·OMX만 연결(상위 관제).

## 1. 배송 상태

```
reserved ──(로봇 claim)──▶ dispatched ──(로봇 도착 보고)──▶ arrived ──(로봇이 일회용 마커 읽음)──▶ received
   │                           │                               │
   └─(간호사 취소)─▶ cancelled  └──(로봇 실패 보고)──▶ failed ◀──┘ (미수령 5분 · 주행 실패 · 금지 장소)
```

| 상태 | 뜻 | 누가 바꾸나 | 재고 |
|---|---|---|---|
| `reserved` | 예약됨, 로봇 배정 전 | 간호사 생성 | 예약 때 차감 |
| `cancelled` | 취소 | 간호사(본인, reserved에서만) | 복구 |
| `dispatched` | 로봇이 맡아 출발 | 로봇 claim | 그대로 |
| `arrived` | 목적지 도착, 수령 대기. 일회용 마커가 생김 | 로봇 progress | 그대로 |
| `received` | 수령 완료 | 로봇 receipt (일회용 마커) | 그대로 |
| `failed` | 실패 (사유 있음) | 로봇 progress | **복구** |

- 간호사 변경·취소는 `reserved`에서만(출발 뒤 취소는 이번 범위 밖).
- 2026-10-19 이전에 로봇 없이 수령된 행(`received`, 배정 로봇 없음)은 그대로 둔다.

실패 사유 `failure_reason`:

| 값 | 뜻 |
|---|---|
| `navigation_failed` | 목적지까지 주행 실패(Nav2 중단·시간 초과) |
| `not_received` | 도착 후 `receipt_wait_seconds`(300초) 안에 수령 없음 |
| `destination_blocked` | 목적지가 실행기 설정의 금지 장소(2026-10-22 비품실 금지 해제 — 지금 없음)이거나 Pinky가 갈 수 없는 곳 — 움직이지 않음 |
| `robot_error` | 그 밖의 로봇 쪽 오류 |

## 2. 일회용 수령 마커

> **2026-10-22부터 꺼 둠**: 간호사 배송도 "받았습니다" 버튼으로 받는다(`NURSE_RECEIPT_METHOD=button`). 마커는 DB 규칙(`ck_deliveries_arrival`) 때문에 도착 때 여전히 만들지만 화면에 보이지 않고, 실행기도 읽지 않는다(`receipt_markers: false`). 로봇이 번호를 보내면(3.5) 지금도 받는다. 아래는 `NURSE_RECEIPT_METHOD=marker`로 되살렸을 때의 규칙.

- ArUco **`DICT_4X4_250`**. 앞 50개(0–49)는 간호사 고정 마커(`DICT_4X4_50`)와 같고, 일회용 마커는 **50–249**.
- `arrived`가 될 때 EMR이 지금 `arrived`인 다른 배송이 쓰지 않는 번호를 무작위로 하나 배정(`receipt_marker_id`). 그 배송이 `arrived`인 동안만 유효.
- 예약한 간호사에게만 보인다: 도착 알림과 그 간호사의 배송 목록. **로봇용 응답에는 절대 넣지 않는다**(로봇은 읽은 번호를 보내기만 하고 맞는지는 EMR이 판정).
- 간호사 고정 마커(0–49)로는 수령할 수 없다(2026-10-20 변경).
- 로봇 카메라는 `DICT_4X4_250`으로 검출한다(오류 보정 1비트. `DICT_4X4_1000`은 0비트라 쓰지 않음).

## 3. 로봇 API

공통: 주소 `{EMR}/api/v1/robot/...`, 헤더 `X-Robot-Api-Key: <로봇별 키>`(관리자가 EMR 로봇 탭에서 발급). 키 오류는 401 `robot_key_missing`·`robot_key_invalid`. 오류 본문은 `{"code", "detail"}`. 시각은 ISO 8601(UTC, `Z` 또는 `+00:00`).

### 3.1 `GET /robot/me` — 시작할 때·복구할 때
```json
{
  "robot": {"id": 1, "name": "배송로봇 1호", "robot_type": "amr"},
  "active_delivery": null,
  "receipt_wait_seconds": 300
}
```
- (2026-10-27 없앰) `home_location` — 복귀 장소는 EMR이 정하지 않는다(사용자 결정: 어디로 돌아갈지는 팀원 FMS가 정함). DB 칸만 남아 있고 API에는 없다.
- `active_delivery`: 이 로봇이 맡은 `dispatched`·`arrived` 배송(3.4 형식) 또는 `null` — 실행기가 재시작했을 때 이어서 한다.

### 3.2 `POST /robot/deliveries/claim` — 배송 가져가기 (실행기가 3초마다)
- 본문 없음. **멱등**: 이 로봇이 이미 `dispatched`·`arrived` 배송을 갖고 있으면 그것을 200으로 돌려준다(응답을 잃어도 다시 부르면 된다).
- 없으면 다음 조건 중 `scheduled_at`이 가장 이른(같으면 id 작은) 한 건을 `dispatched`로 바꿔 200:
  `status = reserved`, `scheduled_at <= 지금`, 목적지에 **로봇 목적지 이름(`robot_dest`)이 있음**(2026-10-27 — 전에는 '맵 좌표가 있고 복귀 장소와 같은 맵').
  여러 로봇이 동시에 불러도 한 건은 한 로봇에만 간다(`FOR UPDATE SKIP LOCKED`).
- 줄 배송이 있으면 그 전에 **EMR이 로봇 서버에 지금 상태를 묻는다**(3.6, 2026-10-23). 아래 중 하나면 배송을 주지 않고 **204** + 헤더 `X-Claim-Skip-Reason`:
  `robot_server_not_set`(로봇 서버 주소 없음) · `robot_server_unreachable`(2초 안에 응답 없음·200 아님) · `robot_status_incomplete`(`battery_percent`·`contamination_percent` 0~100이 없음) · `robot_not_ready`(`localized`·`nav2_ready`가 true가 아니거나 `state`가 `idle`이 아님) · `robot_battery_low`(배터리 30 % 미만) · `robot_contamination_high`(오염도 70 초과).
  줄 배송이 없으면 묻지 않는다. 이미 맡은 배송은 상태와 상관없이 그대로 돌려준다(멱등, 묻지 않음). 기준값은 EMR 설정 `CLAIM_MIN_BATTERY_PERCENT`·`CLAIM_MAX_CONTAMINATION_PERCENT`·`ROBOT_SERVER_TIMEOUT_SECONDS`(가정값).
- 줄 것이 없으면 **204**(본문 없음, 상태 문제가 아니면 헤더 없음).

| 오류 | 코드 |
|---|---|
| 403 | `robot_not_amr` — AMR만 배송을 맡는다 |

### 3.3 `POST /robot/deliveries/{id}/progress` — 진행 보고
```json
{"stage": "arrived"}
{"stage": "failed", "failure_reason": "navigation_failed"}
```
| 지금 → 보고 | 결과 |
|---|---|
| `dispatched` → `arrived` | `arrived`, `arrived_at`, 일회용 마커 배정, 예약 간호사에게 도착 알림 |
| `arrived` → `arrived` | 200 그대로(멱등) |
| `dispatched`·`arrived` → `failed` | `failed`, `failed_at`, 재고 복구, 알림(예약 간호사 + 관리자) |
| `failed` → `failed` | 200 그대로(멱등) |
| `received` → `failed` | 409 `delivery_already_received` — 실행기는 성공으로 본다(5분 직전에 수령된 경우) |
| 그 밖 | 409 `delivery_invalid_transition` |

| 오류 | 코드 |
|---|---|
| 404 | `delivery_not_found` |
| 403 | `delivery_not_assigned_to_robot` — 이 로봇이 맡은 배송이 아님 |
| 422 | `stage`가 `failed`인데 `failure_reason` 없음 등 |

### 3.4 로봇용 배송 형식 (`claim`·`progress`·`me.active_delivery`)
```json
{
  "id": 12,
  "status": "dispatched",
  "scheduled_at": "2026-10-20T03:00:00Z",
  "destination": {"id": 3, "name": "301호", "map_id": 4, "map_x_m": 0.26, "map_y_m": -0.92, "map_yaw_rad": 0.0},
  "items": [{"name": "A 약품", "quantity": 3}],
  "dispatched_at": "2026-10-20T03:00:02Z",
  "arrived_at": null,
  "receipt_deadline_at": null,
  "receipt_method": "marker"
}
```
- `destination`의 `robot_dest` (2026-10-22): 팀원 Pinky API 목적지 이름(`GET /dests`). 실행기가 `POST /goto {"dest"}`로 쓴다. 채우기: `emr/backend/scripts/import_pinky_dests.py`(Pinky 목적지 → EMR 맵 "Pinky 아레나"·장소, 다시 돌리면 갱신).
- `receipt_deadline_at` = `arrived_at + receipt_wait_seconds` (arrived일 때만).
- `receipt_method` (2026-10-22): `button` = 사람이 화면에서 "받았습니다"로 수령 — 환자(병상) 배송은 항상(8장), 간호사 배송은 `NURSE_RECEIPT_METHOD=button`(지금 기본, 5장) / `marker` = 간호사 배송, 로봇이 일회용 마커를 읽어 `receipt` 호출(`NURSE_RECEIPT_METHOD=marker`). 병상 배송에 로봇이 `receipt`를 부르면 409 `delivery_receipt_by_button`.
- 넣지 않는 것: 일회용 마커, 간호사 이름·id.

### 3.5 `POST /robot/deliveries/{id}/receipt` — 수령 확인 (기존 API, 규칙 변경)
```json
{"aruco_marker_id": 137}
```
- `arrived`이고 이 로봇이 맡은 배송이며, 번호가 그 배송의 일회용 마커일 때만 `received`(받은 간호사 = 예약 간호사, 받은 로봇 = 이 로봇). 200 + 3.4 형식.

| 오류 | 코드 |
|---|---|
| 409 | `delivery_not_arrived` — 아직 도착 전이거나 끝난 배송 |
| 409 | `delivery_receipt_by_button` — 환자(병상) 배송은 마커로 받지 않음 (2026-10-22) |
| 403 | `delivery_not_assigned_to_robot` |
| 403 | `receipt_marker_not_for_delivery` — 번호가 이 배송의 마커가 아님(간호사 고정 마커 포함) |
| 422 | 번호가 0–249 밖 |

### 3.6 EMR → 로봇 서버 `GET {robot_server_url}/status` — claim 때 상태 묻기 (2026-10-23)
- 방향이 반대다: **EMR이 부른다.** 로봇 서버 = 팀원 Pinky API(로봇마다 `:8080`). 주소는 관리자가 EMR 로봇 탭 "로봇 서버"에 넣는다(`robots.robot_server_url`, 예: `http://192.168.129.107:8080`, 0014).
- 언제: 로봇이 claim을 불렀고 줄 배송이 있을 때 한 번. 제한 시간 2초. GET만 부른다(로봇을 움직이지 않음).
- EMR이 읽는 필드(나머지는 무시):

| 필드 | 형식 | 지금 Pinky `/status` | 판정 |
|---|---|---|---|
| `battery_percent` | number 0~100 | **없음 — 팀원이 넣어야 함** | 30 미만이면 `robot_battery_low` |
| `contamination_percent` | number 0~100, 0 = 깨끗 | **없음 — 팀원이 넣어야 함** | 70 초과면 `robot_contamination_high` |
| `localized` | bool | 있음 | true가 아니면 `robot_not_ready` |
| `nav2_ready` | bool | 있음 | true가 아니면 `robot_not_ready` |
| `state` | string | 있음(`idle`·`running`) | `idle`이 아니면 `robot_not_ready` |

- 예(팀원이 두 칸을 넣은 뒤): `{"localized": true, "nav2_ready": true, "state": "idle", "battery_percent": 82.5, "contamination_percent": 12, "pose": {...}, "job": {...}}`
- 받은 배터리·오염도는 관리자 화면(로봇 탭, `GET /robots`의 `status_report`)에 마지막 값으로 남는다(`robot_status_reports`, 이력 없음).
- 2026-10-23 실측: 팀원 서버 `.107` 응답 0.1초, 배터리·오염도 칸이 없어 `robot_status_incomplete` — **팀원이 두 칸을 넣기 전까지 claim은 배송을 주지 않는다.**

## 4. 실행기 동작 (관제 PC, 로봇마다)

주행 방식은 로봇마다 설정 `navigation`으로 고른다 (2026-10-22):

| `navigation` | 주행 | 목적지 | 맵 확인 | ROS |
|---|---|---|---|---|
| `pinky_api` (**지금**) | 팀원 Pinky API `POST /goto {"dest", "dock"}` → 끝날 때까지 `GET /jobs/{id}` | EMR 장소의 **로봇 목적지**(`robot_dest`, 로봇용 응답 `destination`·`home_location`에 실림 — 2026-10-22, 0011). 설정 `dests` 표는 덮어쓰기(정밀 주차 등)(좌표를 넘기지 않음 — Pinky는 그림 cm) | 안 함(맵 API 없음). 대신 claim 전마다 `GET /status`: 위치 추정·Nav2 준비·`idle`이 아니면 맡지 않음 | 필요 없음 |
| `ros` | Nav2 `navigate_to_pose`(map 프레임 x·y·yaw) | EMR 장소 좌표 | 로봇 `/map` = EMR 맵 | 같은 네트워크·도메인 |

Pinky API는 **인증이 없다** — 지금은 그대로 진행(사용자 결정 2026-10-22), 운영 전에 토큰을 넣는다. 실행기는 자기가 시작한 작업(job)만 기다리고 취소한다.

**주행은 비동기**(2026-10-22): 실행기는 주행을 보내고(`/goto` 202 → 작업 id) 기다리지 않는다. 반복마다(`navigation_poll_s`, 1초) `GET /jobs/{id}`를 한 번 보고, 끝나면 다음 단계(도착 보고·복귀)로 간다. 다른 작업 중(409)이면 다음 반복에서 다시 보낸다. 보내기 전에 `GET /plan`으로 갈 거리가 없으면(이미 그 목적지에 있음) `/goto` 없이 도착으로 본다. 연결 점검은 `executor --check`(GET만, 로봇을 움직이지 않음). **주행 제한 시간은 없다**(`navigation_timeout_s: null`, 사용자 결정) — 로봇 작업이 끝날 때까지 기다리고, 숫자를 넣으면 넘을 때 취소·`navigation_failed`.

1. 시작: `GET /robot/me`. `active_delivery`가 있으면 그 단계부터 이어서. (복귀 장소 확인은 2026-10-27 없앰 — 실행기도 10-23 삭제)
2. 출발 전: (`ros`) 로봇 `/map`(해상도·원점·크기)이 EMR 맵과 같은지 확인. 다르면 배송을 맡지 않는다. (`pinky_api`) claim 전마다 `/status` 확인.
3. 3초마다 `claim`(주행 중에는 하지 않음). 받은 배송의 목적지가 금지 장소(지금 없음)면 바로 `failed destination_blocked`(움직이지 않음). `pinky_api`에서 로봇 목적지가 없는 장소, Pinky가 못 간다는 곳(`/goto` 400)도 `destination_blocked`(움직이지 않음, 복귀 없음). Pinky가 다른 작업 중(409)이 30초 넘게 이어지면 `robot_error`.
4. 주행 성공 → `progress arrived`. 실패(Pinky 작업 `failed` — 구간 결과 `blocked·contact·timeout·lost`)·(제한 시간을 정했을 때) 시간 초과 → `failed navigation_failed` → 복귀.
5. (마커를 켰을 때만, `receipt_markers: true`) 도착 후 ROS 토픽 `receipt_marker`(std_msgs/Int32, 카메라 마커 노드가 발행 — 카메라가 없으면 사람이 `ros2 topic pub`)에서 번호를 받아 `receipt` 호출. 같은 번호는 3초에 한 번만 보낸다. 403이면 계속 기다린다. **지금은 꺼 둠** — 수령은 6번의 "받았습니다" 확인으로만.
6. `receipt_deadline_at`까지 수령이 없으면 `failed not_received` → 복귀. `409 delivery_already_received`면 성공으로 본다.
   대기 중 `receipt_poll_s`(기본 2초)마다 `GET /robot/me`를 불러 `active_delivery`가 없거나 다른 배송이면 **수령된 것**으로 보고 복귀한다 — 간호사·환자의 "받았습니다" 버튼 수령을 알아차리는 방법 (2026-10-22).
7. 복귀 주행 실패는 로그만 남기고 다음 claim을 하지 않는다(사람 확인 필요).

설정(`robot/src/fms/delivery_executor/config/executor.yaml`): EMR 주소, 로봇별 이름·EMR 로봇 id·키 파일 경로(권한 600, 저장소 밖)·금지 장소 id, `navigation`(`pinky_api`·`ros`)·`pinky_api` 주소·`dests` 표(복귀 장소도 포함), `receipt_markers`(지금 `false`), `ros_domain_id`(ROS를 쓸 때만), claim 주기, 주행 제한 시간.

## 5. 간호사 화면·알림

| 사건 | 알림 이벤트 | 받는 사람 | 화면 |
|---|---|---|---|
| 출발 | `delivery_dispatched` | 예약 간호사 | 토스트 "출발했습니다" |
| 도착 | `delivery_arrived` (+ `receipt_method`, `receipt_marker_id`) | 예약 간호사 | 도착 창: **"받았습니다" 버튼**(지금) 또는 일회용 마커(`marker`일 때). 수령·실패 때까지 |
| 수령 | `delivery_received` (기존) | 예약 간호사 | 초록 토스트 |
| 실패 | `delivery_failed` (+ `failure_reason`) | 예약 간호사 + 관리자 | 빨간 토스트 |

- 알림은 저장하지 않는다. 도착 창은 알림이 아니라 **내 배송 목록(arrived)**을 보고 띄운다 — 새로고침·끊김에도 다시 보인다.
- **"받았습니다" (2026-10-22)**: `POST /deliveries/{id}/receipt`(간호사 JWT, 본인 배송) — `arrived`일 때만 `received`(받은 간호사 = 본인, 받은 로봇 = 맡은 로봇), 배송 기록 행위자 `nurse`. 거부: 403 `delivery_not_owned`, 404, 409 `delivery_not_arrived`, 409 `delivery_receipt_by_marker`(`NURSE_RECEIPT_METHOD=marker`일 때). 배송 목록 행에도 '받았습니다' 버튼. 실행기는 4장 6번으로 알아차린다.
- 배송 목록은 진행 중 배송이 있으면 5초, 없으면 30초마다 새로 고친다.

## 6. 관리자

- (2026-10-27 없앰) 로봇별 복귀 장소 — 로봇 탭 칸과 `PATCH /robots/{id}` `home_location_id`를 뺐다. 보내도 무시한다.
- 진행 중 배송이 있는 로봇은 삭제할 수 없다(409 `robot_has_active_delivery`). 예전 복귀 장소로 남은 장소도 지울 수 있다(EMR이 로봇의 값을 비우고 지움 — `location_is_robot_home`은 없앰).

## 7. 열린 질문

- 출발 뒤 간호사 취소(로봇 되돌리기) — 지금은 불가, 5분 미수령으로 끝남.
- 관리자 강제 실패(실행기가 죽어 `arrived`로 남은 배송) — 지금은 실행기 재시작으로 이어서 처리.
- 카메라 마커 노드(Pinky 카메라 드라이버 + `DICT_4X4_250` 검출 → `receipt_marker` 발행) — 로봇 쪽 별도 과제. 마커는 2026-10-22부터 꺼 둠 — 되살릴 때 Pinky API에 마커 경로를 둘지(ROS가 LAN 너머로 안 보임) 정한다.
- Pinky API 인증(지금 없음)·EMR 장소 ↔ Pinky 목적지 대응(`stops` 표는 임시)·좌표 변환 — `docs/pinky_fms_api_review_2026-10-22.md` 9장. 팀원 API는 2026-10-22에 `/stops` → `/dests`, `{"stop"}` → `{"dest"}`로 이름을 바꿨다(반영함).
- 로봇 상태 보고(3단계)·배터리·끊김 알림.

## 8. 환자(병상 단말) 배송 (2026-10-22)

사용자 결정: 환자 비품 요청(SR-02) + "받았습니다" 버튼 수령(SR-06), **간호사 승인 없이 바로**, 환자 식별은 **병상 단말 키**(환자 개인정보 저장 안 함), 알림은 **실패만 관리자에게**, **병상당 진행 중 1건**.

```
환자 요청 ──▶ reserved(scheduled_at = 요청 시각, 목적지 = 병상의 병실) ──▶ 로봇 claim(3.2 그대로) ──▶ dispatched ──▶ arrived
                                                                                  │ 마커는 내부에만 만들고 보여 주지 않음
                                     환자 병상 화면 "받았습니다" ─▶ received        └ 5분 미수령 ─▶ failed (재고 복구, 관리자 알림)
```

### 8.1 관리자 — 병상 단말 등록 (간호사 JWT, 관리자만)
| API | 내용 |
|---|---|
| `GET/POST /bedside-devices`, `PATCH/DELETE /bedside-devices/{id}` | 병상 이름(유일, 예 `301호-1`)·병실 장소. 진행 중 배송이 있으면 삭제 409 `bedside_has_active_delivery` |
| `POST /bedside-devices/{id}/api-key` (201) · `DELETE …/api-key` (204) | 키 발급(평문은 응답에 한 번, `emr_bk_…`)·폐기. 재발급하면 이전 키 무효 |
- 병상이 쓰는 장소는 삭제할 수 없다(409 `location_is_bedside_room`).

### 8.2 병상 단말 API — 헤더 `X-Bedside-Api-Key` (간호사 JWT와 별개)
키 오류는 401 `bedside_key_missing`·`bedside_key_invalid`.

| API | 내용 |
|---|---|
| `GET /bedside/me` | 병상 이름, 병실(이름·좌표가 있는지), 진행 중 배송(없으면 null) |
| `GET /bedside/supplies` | 환자가 요청할 수 있는 품목(`requestable_by = patient`, 삭제 안 됨): id·이름·재고 있음 여부(수량은 숨김) |
| `POST /bedside/requests` `{"items": [{"supply_id": 3, "quantity": 1}]}` | 배송을 바로 만든다(201). 품목당 수량 1–5 |
| `GET /bedside/deliveries` | 이 병상의 최근 배송 10건 (마커 없음) |
| `POST /bedside/deliveries/{id}/receipt` | 도착한 이 병상의 배송을 수령 처리(200) |

| 오류 | 코드 |
|---|---|
| 400 | `supply_not_found`, `supply_not_patient_requestable`, `delivery_item_duplicate` |
| 409 | `bedside_request_in_progress` — 진행 중(예약·출발·도착) 배송이 이미 있음 |
| 409 | `bedside_room_has_no_position` — 병실에 맵 좌표가 없어 로봇이 갈 수 없음 |
| 409 | `stock_insufficient` |
| 409 | `delivery_not_arrived` (수령) · 403 `delivery_not_for_bedside` (다른 병상 배송) |

### 8.3 정해진 것
- 배송 행의 예약한 쪽: `requester_type` = `nurse` | `bedside`. 병상 배송은 `nurse_id`가 없고 `bedside_name`(스냅숏)이 있다.
- 로봇 쪽은 3.2 claim 규칙 그대로 환자 배송도 가져간다. 3.4의 `receipt_method`가 `button`이면 마커를 기다릴 필요가 없고, 4장 6번의 `/robot/me` 확인으로 수령을 알아차린다.
- 알림: 환자 배송의 출발·도착·수령은 간호사에게 보내지 않는다. 실패만 관리자에게(`delivery_failed`, `recipient_role: admin`).
- 배송 기록: 행위자 `bedside`(병상 이름 스냅숏)로 예약·수령을 남긴다.

## 9. OMX → EMR 완료 신호 (2026-10-26)

팀원 OMX(로봇팔 API `192.168.129.86:8000`)가 작업을 마치면 EMR에 알리는 곳이다. 사용자 결정: 단순하게 GET, 지금은 성공 신호만, 인증 없음.

- `GET {EMR}/api/v1/robot/{request_id}/end-point` — `request_id`는 OMX `/command`·`/pinky`에 넣은 값 그대로(영문·숫자·`._-`, 1~64자, 아니면 422).
- 응답 200 `{"request_id": "yolo-8b5efa75", "received": true, "received_at": "2026-10-26T06:29:16Z"}`, 헤더 `Cache-Control: no-store`. 같은 id를 여러 번 보내도 매번 200.
- EMR은 서버 로그(`omx_end_point`: request_id·보낸 주소·시각)에만 남긴다. DB·배송 상태·화면은 바꾸지 않는다 — 적재 흐름(FMS `/loaded` 등)과는 FMS 연동 때 잇는다.
- 팀원 공유용 명세: `docs/omx_end_point_spec_2026-10-26.md`.
- **OMX `POST /command` 형식 바뀜(10-26 합의)**: `{"command": {"blue": 개수, "green": 개수}, "request_id": "..."}` — 문장 대신 색깔별 개수. 같은 `request_id`로 위 완료 신호를 부른다. 0개 색 표기·최대 개수·EMR 비품 ↔ blue/green 대응은 미정(명세 8장).
- **EMR → OMX 명령(2026-10-26)**: 관리자 API `POST {EMR}/api/v1/omx/command {command: 문장}`이 OMX `POST /command`를 **예전 형식**(`{"command": "pick and place green gauze", "request_id": "emr-..."}`)으로 부른다. `request_id`는 EMR이 만들고(`emr-` + 시각 + 16진 6자리), OMX는 끝나면 그 값으로 위 완료 신호를 부른다. `GET {EMR}/api/v1/omx/status`는 OMX `/status` 그대로. 새 형식(색깔별 개수)은 OMX가 바뀐 뒤 맞춘다.

## 10. FMS API v1 연동 (2026-10-27)

| 단계 | 내용 | 상태 (10-27 저녁) |
|---|---|---|
| 1단계 | 주문 보내기(10.1) + FMS 이벤트로 배송 단계 바꾸기(10.2) | **구현·시험함** — 시뮬레이터로 NO 55·56·57 신청 → 출발 → 도착. 테스트 9개 |
| 2단계 | 실제 OMX로 적재·탑재 + FMS `ready`·`loaded`(10.4) | **구현·실물 시험함**(10-27, 시뮬레이터 Pinky + 실물 OMX, 임시 문장 형식) — NO 59·60 신청 → 도착. 합의한 개수 형식은 팀원 OMX 변경 뒤 |


팀원 FMS API v1(`kernel-robot-repo-2/fms/API.md`, OpenAPI `fms/openapi_v1.py`)에 붙는다. 분석은 `docs/fms_emr_interface_2026-10-27.md`. EMR이 주문을 보내고 FMS가 이벤트를 EMR로 보낸다(3장 claim의 반대 방향).
**1단계 범위(사용자 결정)**: 주문 보내기 + 이벤트 받아 배송 단계 바꾸기. `ready`·`loaded`(OMX 연동)는 2단계 — 그 전에는 FMS(시뮬레이터)의 가상 OMX가 보낸다.

### 10.1 EMR → FMS `POST {FMS_BASE_URL}/api/v1/orders`
- EMR 주기 작업(`FMS_SEND_INTERVAL_SECONDS`, 기본 5초)이 **reserved이고 예약 시각이 지났고 목적지에 `robot_dest`가 있는** 배송을 이른 순으로 읽어, **물품 1개당 1건** 보낸다.
- 본문 `{"request_id": "emr-d{배송 id}-s{비품 id}-{n번째}", "room": 장소 robot_dest(= FMS 방 번호, 10-27 데이터 변경), "item": 비품 이름}`.
- 202·200이면 `fms_orders`에 한 줄(배송·비품·n번째·`request_id`·FMS `order_id`). 다음 회차에 다시 보내지 않는다. 같은 `request_id`는 FMS가 처음 주문(200)을 돌려주므로 응답을 잃어도 안전.
- 400(`unknown_room` 등)이면 로그만 남기고 다음 회차에 다시. 연결 실패·5xx면 그 회차를 멈춘다. 1단계에서는 실패로 바꾸지 않는다.
- **한 개라도 보낸 배송은 간호사가 변경·취소할 수 없다**: 409 `delivery_sent_to_fms`(FMS는 `queued`일 때만 취소를 받으므로 — 취소 연동은 다음 단계).

### 10.2 FMS → EMR
| 경로 | 인증 | 응답 | EMR이 하는 일 |
|---|---|---|---|
| `POST /api/v1/fms/robot-status` | 없음(사용자 결정) | 200 `{"ok": true}` | 1단계는 받기만(저장·표시는 다음 단계) |
| `POST /api/v1/fms/events` | 없음 | 200 `{"ok": true, "handled": bool}` — **올바른 JSON이면 4xx를 주지 않는다**(FMS가 다시 안 보냄) | 아래 표. 바깥 HTTP 호출 없음, DB만 |

| 이벤트 | EMR |
|---|---|
| `batch_assigned` | 묶음의 EMR 주문에 `batch_id`·FMS 로봇 번호. 그 주문의 배송이 reserved면 **dispatched**(로봇 = 설정 `FMS_ROBOT_MAP`으로 바꾼 EMR 로봇, 출발 알림·배송 기록) |
| `order_delivered` | 그 주문을 delivered로. **배송의 물품이 모두 보내졌고 모두 delivered면 arrived**(일회용 마커·도착 알림·기록 — `report_progress`와 같은 처리) |
| `order_failed` | 그 주문의 배송을 failed(`robot_error`, 재고 복구·실패 알림). 시뮬레이터에는 아직 없음 |
| `order_canceled` | 주문 상태만 |
| 그 밖·우리 주문이 아님 | 무시(`handled: false`) |

- 같은 이벤트가 다시 와도 결과가 같다(상태 전이가 멱등). `event_id` 표는 두지 않는다.
- **한 로봇이 여러 배송을 함께 맡는다** — FMS 묶음(최대 3개)에 여러 신청이 섞이므로 0015에서 '로봇 한 대 = 진행 중 배송 하나' 유일 인덱스를 없앴다.
- 한 신청이 여러 로봇으로 나뉘면 처음 배차된 로봇을 적는다(분석 문서 4장 결정 2 권하는 안).

### 10.3 설정
`FMS_BASE_URL`(빈 값 = 끔, 주기 작업 없음·claim 그대로), `FMS_TIMEOUT_SECONDS`(3), `FMS_SEND_INTERVAL_SECONDS`(5), `FMS_ROBOT_MAP`(FMS 로봇 번호 → EMR 로봇 id, 기본 `{"1": 1, "2": 3, "3": 4}` — 10-27 EMR 로봇 1 배송로봇 1호·3 2호·4 3호, 2는 OMX).
FMS는 `--control-url http://<EMR>:8000`으로 띄운다.

### 10.4 2단계: 실제 OMX로 싣기 — EMR ↔ OMX (2026-10-27, 구현함·꺼짐)

사용자 결정(10-27): "OMX만 실제로 변경하고 2개 약품해서 진행" — FMS는 시뮬레이터 그대로, OMX만 실물. 양팔 **탑재(/pinky)까지 실제**, `/pinky` = **Pinky 정밀 주차가 끝난 뒤 내려놓기**.
같은 날 명령 형식을 **`{"command": {"blue": N, "green": N}, "request_id"}`로 정함 — FMS 묶음 하나에 한 번**(잠깐 쓴 '물품마다 문장 한 번씩' 안은 버림).
⚠️ 10-27 실제 OMX(팀원 `vision` `47bcb47`)는 아직 **문장만 받는다**(`command`가 문자열).
**임시 방편(10-27 사용자: "이전 버전 API, 수량 무시하고 거즈 문장으로" — 시험 뒤 "합의한 내용으로 변경"으로 **끔**)**: 설정 `OMX_COMMAND_FORMAT=sentence`면 개수 대신 문장 하나 `"pick and place blue gauze"`를 보낸다 — 파란 거즈가 하나라도 있으면 blue, 아니면 green, **수량은 무시**(OMX가 한 개만 집음). FMS 묶음과 관리자 API 둘 다. 관리자 API는 이 스위치가 켜졌을 때만 문장 본문 `{"command": "pick and place blue gauze"}`도 받는다(기본 `counts`면 400 `omx_sentence_disabled`). 10-27 실물 시험(NO 59·60)은 이 스위치로 했다 — `docs/emr_fms_omx_integration_2026-10-27.md` 3장.

**EMR이 부르는 OMX API** (`http://192.168.129.86:8000`, 인증 없음)

| 요청 | 본문 | 언제 |
|---|---|---|
| `POST /command` | `{"command": {"blue": 2, "green": 0}, "request_id": "emr-b{묶음 행 id}"}` — 약품 → blue, 비품 → green(`services/omx_items.py`), 두 색 모두 키, 합계 1~3 | FMS `batch_assigned` 뒤, OMX가 움직이거나 들고 있지 않을 때 |
| `POST /pinky` | `{"pinky_arrive": true, "request_id": 같은 값}` | FMS `robot_at_pharmacy`(**정밀 주차 끝**) 뒤 — 들고 있는 물품을 Pinky 위에 내려놓기 |
| `GET /status` | — | 끝났는지 판단(1초마다). `state`(running·completed·failed), `pinky`(grabbing → holding → releasing → returning → completed, 실패 grab_failed·release_failed·return_failed) |
| OMX → EMR `GET /api/v1/robot/{request_id}/end-point` | — | 집기 끝·내려놓고 복귀 끝에 같은 `request_id`로 두 번. **EMR은 로그만, 판단은 `/status`로** — OMX가 EMR에 닿지 못해도 흐름이 선다 |

**EMR이 부르는 FMS API** (10.1과 같은 서버)

| 요청 | 언제 | 응답 처리 |
|---|---|---|
| `POST /api/v1/batches/{id}/ready` | OMX가 **집어서 양팔로 들었을 때**(`state=completed`, `pinky=grabbing·holding`) — Pinky를 약제실로 | 200, 또는 409 `bad_batch_state` = 이미 넘어감(사용자 결정) |
| `POST /api/v1/batches/{id}/loaded` | **내려놓고 팔이 돌아왔을 때**(`pinky=completed`) — Pinky를 병실로 | 같음 |

**순서 (묶음 하나)**

```
FMS batch_assigned ─▶ EMR: fms_batches 한 줄 (blue N·green N, 단계 pick)
EMR ─POST /command {"blue": N, "green": N}─▶ OMX 집기 → 시작 자세 → 스스로 양팔로 들고 대기 (pinky=holding)
EMR ─POST /batches/{id}/ready─▶ FMS ─▶ Pinky 약제실로, 정밀 주차 ─▶ FMS 이벤트 robot_at_pharmacy
EMR ─POST /pinky─▶ OMX 내려놓기 → 시작 자세 (pinky=completed)
EMR ─POST /batches/{id}/loaded─▶ FMS ─▶ Pinky 병실로 (그 뒤는 10.2: order_delivered → 도착)
```

- 단계(`fms_batches.step`): `pick → picking → ready → called → pinky → loading → loaded → delivering`, 멈춤 `failed`.
- **안전 규칙**: OMX `/status`가 `running`이거나 `pinky`가 grabbing·holding·releasing·returning이면 `/command`를 보내지 않는다 — 팀원 OMX는 들고 있는 동안에도 `/command`를 받아 왼팔을 움직이기 때문(10-27 코드 확인). OMX는 한 번에 묶음 하나만 쓴다(다른 묶음은 `pick`에서 기다림). 정밀 주차(`robot_at_pharmacy`) 전에는 `/pinky`를 보내지 않는다.
- **실패**: OMX 4xx 거절, `state=failed`(못 찾음 — 실패는 EMR로 오지 않음), `pinky=*_failed`, FMS 4xx(409 bad_batch_state 말고)면 묶음을 `failed`로 멈추고 로그 `fms_omx_failed`(error에 까닭). 배송 상태는 바꾸지 않는다 — 사람이 팔·Pinky를 확인한다. 응답 없음은 다음 회차에 다시. 시간 초과는 아직 없음.
- **저장**: `fms_batches`(0016) — FMS `batch_id`(FMS를 다시 켜면 b-1부터라 UNIQUE 아님), 로봇 번호, `blue_count`·`green_count`, 단계, OMX `request_id`, ready·정밀 주차·loaded 시각, error.
- **바깥 HTTP는 주기 작업에서만**(`services/fms_omx.py`, `FMS_OMX_ROUND_SECONDS` 1초). FMS 이벤트를 받는 요청은 DB만(`batch_assigned` → 묶음 행, `robot_at_pharmacy` → 정밀 주차 시각).
- 설정 `FMS_OMX_ENABLED`(기본 0). 0이면 FMS(시뮬레이터) 가상 OMX가 `ready`·`loaded`를 보낸다. 1로 켤 때는 시뮬레이터 가상 OMX를 끈다(`POST /api/control {"auto_omx": false}`).
- **실제 시험 전 확인**: ① 팀원 OMX가 `{"blue": N, "green": N}`를 받는지 ② OMX를 `--pinky --emr-api http://<EMR>:8000/api/v1`로 실행 ③ 테이블에 파란 거즈 N개 ④ 팔 시작 자세(10-27 마지막 시도 `grab_failed`) ⑤ 한 번에 여러 개 집는지(N ≥ 2).
