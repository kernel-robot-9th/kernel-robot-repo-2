<callout icon="📄" color="gray_bg">
원본: 저장소 `docs/api_contract_delivery_2026-10-20.md` (2026-10-22 기준). 바꿀 때는 원본부터 고치고 이 페이지를 다시 올린다.
</callout>

- 환자(병상 단말) 배송 추가(2026-10-22): 8장.
- 구현(2026-10-20): EMR 마이그레이션 0008·`app/services/dispatch.py`·`delivery_notifier.py`·배송 화면, 관제 PC `robot/src/fms/delivery_executor`. 실제 EMR + 가짜 Nav2(도메인 77)로 확인, <b>실물 Pinky 종단 시험은 비품실 모방학습이 끝난 뒤</b>.
- 범위: EMR 로드맵 2단계(배송 배정·진행) + 간호사 알림(5단계 일부). 양쪽(`emr/`, `robot/src/fms/delivery_executor`)이 이 문서를 기준으로 구현한다. 바꿀 때는 이 문서부터 고친다.
- 사용자 결정(2026-10-20): 로봇 쪽이 EMR을 조회(claim) · 예약 시각이 지난 것부터 한 건씩 · 적재 없이 출발 · 수령은 <b>알림에 뜨는 일회용 마커를 로봇이 읽어서만</b> · 실패하면 재고 자동 복구 · 도착 후 5분 미수령이면 실패 + 복귀.

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
| `failed` | 실패 (사유 있음) | 로봇 progress | <b>복구</b> |

- 간호사 변경·취소는 `reserved`에서만(출발 뒤 취소는 이번 범위 밖).
- 2026-10-19 이전에 로봇 없이 수령된 행(`received`, 배정 로봇 없음)은 그대로 둔다.

실패 사유 `failure_reason`:

| 값 | 뜻 |
|---|---|
| `navigation_failed` | 목적지까지 주행 실패(Nav2 중단·시간 초과) |
| `not_received` | 도착 후 `receipt_wait_seconds`(300초) 안에 수령 없음 |
| `destination_blocked` | 목적지가 실행기 설정의 금지 장소(지금 비품실) — 움직이지 않음 |
| `robot_error` | 그 밖의 로봇 쪽 오류 |

## 2. 일회용 수령 마커

- ArUco <b>`DICT_4X4_250`</b>. 앞 50개(0–49)는 간호사 고정 마커(`DICT_4X4_50`)와 같고, 일회용 마커는 <b>50–249</b>.
- `arrived`가 될 때 EMR이 지금 `arrived`인 다른 배송이 쓰지 않는 번호를 무작위로 하나 배정(`receipt_marker_id`). 그 배송이 `arrived`인 동안만 유효.
- 예약한 간호사에게만 보인다: 도착 알림과 그 간호사의 배송 목록. <b>로봇용 응답에는 절대 넣지 않는다</b>(로봇은 읽은 번호를 보내기만 하고 맞는지는 EMR이 판정).
- 간호사 고정 마커(0–49)로는 수령할 수 없다(2026-10-20 변경).
- 로봇 카메라는 `DICT_4X4_250`으로 검출한다(오류 보정 1비트. `DICT_4X4_1000`은 0비트라 쓰지 않음).

## 3. 로봇 API

공통: 주소 `{EMR}/api/v1/robot/...`, 헤더 `X-Robot-Api-Key: <로봇별 키>`(관리자가 EMR 로봇 탭에서 발급). 키 오류는 401 `robot_key_missing`·`robot_key_invalid`. 오류 본문은 `{"code", "detail"}`. 시각은 ISO 8601(UTC, `Z` 또는 `+00:00`).

### 3.1 `GET /robot/me` — 시작할 때·복구할 때
```json
{
  "robot": {"id": 1, "name": "배송로봇 1호", "robot_type": "amr"},
  "home_location": {"id": 2, "name": "간호사스테이션", "map_id": 4, "map_x_m": -0.6, "map_y_m": -1.55, "map_yaw_rad": 0.0},
  "active_delivery": null,
  "receipt_wait_seconds": 300
}
```
- `home_location`: 관리자가 정한 복귀 장소. 없거나 좌표가 없으면 `null`.
- `active_delivery`: 이 로봇이 맡은 `dispatched`·`arrived` 배송(3.4 형식) 또는 `null` — 실행기가 재시작했을 때 이어서 한다.

### 3.2 `POST /robot/deliveries/claim` — 배송 가져가기 (실행기가 3초마다)
- 본문 없음. <b>멱등</b>: 이 로봇이 이미 `dispatched`·`arrived` 배송을 갖고 있으면 그것을 200으로 돌려준다(응답을 잃어도 다시 부르면 된다).
- 없으면 다음 조건 중 `scheduled_at`이 가장 이른(같으면 id 작은) 한 건을 `dispatched`로 바꿔 200:
  `status = reserved`, `scheduled_at <= 지금`, 목적지에 맵 좌표가 있고, 목적지 맵 = 복귀 장소 맵.
  여러 로봇이 동시에 불러도 한 건은 한 로봇에만 간다(`FOR UPDATE SKIP LOCKED`).
- 줄 것이 없으면 <b>204</b>(본문 없음).

| 오류 | 코드 |
|---|---|
| 403 | `robot_not_amr` — AMR만 배송을 맡는다 |
| 409 | `robot_home_not_set` — 복귀 장소가 없거나 좌표가 없음 |

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
- `receipt_deadline_at` = `arrived_at + receipt_wait_seconds` (arrived일 때만).
- `receipt_method` (2026-10-22): `marker` = 간호사 배송, 로봇이 일회용 마커를 읽어 `receipt` 호출 / `button` = 환자(병상) 배송, 환자가 병상 화면 "받았습니다"로 수령(8장). `button`이면 로봇의 `receipt` 호출은 409 `delivery_receipt_by_button`.
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

## 4. 실행기 동작 (관제 PC, 로봇마다)

1. 시작: `GET /robot/me`. 복귀 장소가 없으면 기다리며 경고. `active_delivery`가 있으면 그 단계부터 이어서.
2. 출발 전: 로봇 `/map`(해상도·원점·크기)이 EMR 맵과 같은지 확인. 다르면 배송을 맡지 않는다.
3. 3초마다 `claim`. 받은 배송의 목적지가 금지 장소면 바로 `failed destination_blocked`(움직이지 않음).
4. Nav2 `navigate_to_pose`(map 프레임, 목적지 x·y·yaw). 성공 → `progress arrived`. 실패·시간 초과 → `failed navigation_failed` → 복귀.
5. 도착 후 ROS 토픽 `receipt_marker`(std_msgs/Int32, 카메라 마커 노드가 발행 — 카메라가 없으면 사람이 `ros2 topic pub`)에서 번호를 받아 `receipt` 호출. 같은 번호는 3초에 한 번만 보낸다. 403이면 계속 기다린다.
6. `receipt_deadline_at`까지 수령이 없으면 `failed not_received` → 복귀. `409 delivery_already_received`면 성공으로 본다. 대기 중 `receipt_poll_s`(기본 2초)마다 `GET /robot/me`를 불러 `active_delivery`가 없거나 다른 배송이면 <b>수령된 것</b>으로 보고 복귀한다 — 환자 배송의 버튼 수령을 알아차리는 방법 (2026-10-22).
7. 복귀 주행 실패는 로그만 남기고 다음 claim을 하지 않는다(사람 확인 필요).

설정(`robot/src/fms/delivery_executor/config/executor.yaml`): EMR 주소, 로봇별 이름·EMR 로봇 id·ROS 도메인·키 파일 경로(권한 600, 저장소 밖)·금지 장소 id, claim 주기, 주행 제한 시간.

## 5. 간호사 화면·알림

| 사건 | 알림 이벤트 | 받는 사람 | 화면 |
|---|---|---|---|
| 출발 | `delivery_dispatched` | 예약 간호사 | 토스트 "출발했습니다" |
| 도착 | `delivery_arrived` (+ `receipt_marker_id`) | 예약 간호사 | 일회용 마커 창(수령·실패 때까지) |
| 수령 | `delivery_received` (기존) | 예약 간호사 | 초록 토스트 |
| 실패 | `delivery_failed` (+ `failure_reason`) | 예약 간호사 + 관리자 | 빨간 토스트 |

- 알림은 저장하지 않는다. 마커 창은 알림이 아니라 <b>내 배송 목록(arrived + 마커)</b>을 보고 띄운다 — 새로고침·끊김에도 다시 보인다.
- 배송 목록은 진행 중 배송이 있으면 5초, 없으면 30초마다 새로 고친다.

## 6. 관리자

- 로봇 탭에서 로봇별 <b>복귀 장소</b>를 고른다(`PATCH /robots/{id}` `home_location_id`).
- 진행 중 배송이 있는 로봇은 삭제할 수 없다(409 `robot_has_active_delivery`). 복귀 장소로 쓰는 장소는 삭제할 수 없다(409 `location_is_robot_home`).

## 7. 열린 질문

- 출발 뒤 간호사 취소(로봇 되돌리기) — 지금은 불가, 5분 미수령으로 끝남.
- 관리자 강제 실패(실행기가 죽어 `arrived`로 남은 배송) — 지금은 실행기 재시작으로 이어서 처리.
- 카메라 마커 노드(Pinky 카메라 드라이버 + `DICT_4X4_250` 검출 → `receipt_marker` 발행) — 로봇 쪽 별도 과제.
- 로봇 상태 보고(3단계)·배터리·끊김 알림.

## 8. 환자(병상 단말) 배송 (2026-10-22)

사용자 결정: 환자 비품 요청(SR-02) + "받았습니다" 버튼 수령(SR-06), <b>간호사 승인 없이 바로</b>, 환자 식별은 <b>병상 단말 키</b>(환자 개인정보 저장 안 함), 알림은 <b>실패만 관리자에게</b>, <b>병상당 진행 중 1건</b>.

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
