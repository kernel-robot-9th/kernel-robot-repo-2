# FMS가 EMR에서 쓰는 API — 배송·로봇 상태 (2026-10-27)

팀원 FMS(Pinky 관제)가 EMR에서 **배송을 받아 가고 진행을 알리는 API**와 **로봇 상태를 보는 API**를 한 곳에 모았다.
코드 기준: `emr/backend/app/api/v1/robot_access.py`(로봇 전용 `/robot`), `app/api/v1/robots.py`(로봇 조회 `/robots`).
2026-10-27 실제 스택에서 GET으로 확인했다(배송 상태를 바꾸는 POST 예시는 10-23 실측값).

> 이전 문서 `emr_robot_api_for_teammate_2026-10-22.md`·`emr_robot_data_format/README.md`(10-23)를 대신한다. **10-27에 바뀐 점**: EMR은 복귀 장소를 정하지 않는다 — `/robot/me`의 `home_location`, claim 오류 409 `robot_home_not_set`이 없어졌고, 배송이 끝난 뒤 어디로 갈지는 FMS가 정한다. 그리고 **`POST /robot/arrived`는 약제실 도착 전용**이 되었다(EMR은 로그만 남김) — 병실 도착은 `POST /robot/deliveries/{id}/progress {"stage":"arrived"}`.

## 0. 공통

| 항목 | 값 |
|---|---|
| 주소 | `http://192.168.129.135:8000/api/v1` (시험 화면 `/docs`) |
| 인증 | 헤더 `X-Robot-Api-Key: <로봇별 키>`. **지금 개발 스택은 꺼 둠**(`ROBOT_KEY_DISABLED=1`) — 키 없이 부르면 **배송로봇 1호(id 1)**로 처리 |
| 본문 | JSON. 시각은 UTC ISO 8601 |
| 오류 | `{"code": "...", "detail": "..."}` — `code`로 분기, `detail`은 개발자용 영어 문장 |
| 목적지 | EMR 장소의 `robot_dest` = Pinky `GET /dests`의 이름. FMS는 그대로 `POST /goto {"dest": ...}` |

## 1. 배송 한 건의 흐름

```
간호사가 EMR에서 물품 신청 (status: reserved)
 │
 ├ (선택) GET  /robot/deliveries          맡지 않고 목록만 보기
 ① POST /robot/deliveries/claim           배송 하나 맡기 → dispatched
 │      EMR이 그 전에 Pinky GET /status를 물어 기준 밖이면 204
 ② FMS → Pinky POST /goto {"dest": "PHARMACY"}
 ③ POST /robot/arrived                    약제실 도착 알림 — EMR은 로그만, 상태는 dispatched 그대로
      약제실에서 탑재(사람 또는 OMX) — EMR API 없음
 ④ FMS → Pinky POST /goto {"dest": destination.robot_dest}
 ⑤ POST /robot/deliveries/{id}/progress {"stage":"arrived"}
                                          병실 도착 → arrived (간호사 화면에 "받아 주세요")
 ⑥ 간호사가 EMR 화면에서 "받았습니다"    → received
 │      FMS는 GET /robot/me의 active_delivery가 null이 되면 끝난 것 → 다음 행선지는 FMS가 정함
 └ 실패면 ⑤·⑥ 대신 POST /robot/deliveries/{id}/progress {"stage":"failed", ...} → failed (재고 복구)
```

배송은 약제실 → 병실만 있다. 로봇을 약제실로 부르고 물품을 싣는 일은 FMS가 claim을 받은 뒤 스스로 처리한다. EMR은 약제실 도착(`/robot/arrived`)을 로그로만 받고, 화면에는 병실 도착 전까지 "출발"로 보인다. 탑재가 실패하면 `robot_error`로 실패를 보고한다.

로봇 한 대는 배송을 하나씩만 맡는다. 맡은 배송이 끝나야(received·failed) 다음 claim이 새 배송을 준다.

## 2. 배송 API

| 메서드·경로 | 하는 일 | 성공 | 오류 |
|---|---|---|---|
| `GET /robot/deliveries?due_only=true&limit=50` | 아직 아무 로봇도 맡지 않은 `reserved` 배송 목록(예약 시각 순). **상태를 바꾸지 않음** | 200 배송 배열 | — |
| `POST /robot/deliveries/claim` | 배송 하나 맡기 (본문 없음) | 200 배송 · 204 없음 | 403 `robot_not_amr` |
| `POST /robot/arrived` | **약제실 도착** 알림 (본문 없음, id 필요 없음). 로그만, 상태 그대로 | 200 배송 | 409 `robot_no_active_delivery` · `delivery_invalid_transition` |
| `POST /robot/deliveries/{id}/progress` | **병실 도착**·실패 보고 | 200 배송 | 403·404·409 (아래) |

수령은 간호사가 EMR 화면에서 "받았습니다"를 누르는 방식이라 FMS가 부를 API가 없다(`/robot/me`로 알아차린다).

### 2.1 `GET /robot/deliveries` — 목록만 보기

| 질의 | 기본 | 뜻 |
|---|---|---|
| `due_only` | `true` | 예약 시각이 지난 것만. `false`면 앞으로 예정된 것까지 |
| `limit` | 50 | 1~200 |

어느 로봇을 보낼지 FMS가 먼저 보고 싶을 때 쓴다. 실제로 맡으려면 그 로봇으로 claim을 불러야 한다(목록에서 특정 배송을 골라 맡는 API는 없음 — claim은 가장 이른 것을 준다).

### 2.2 `POST /robot/deliveries/claim` — 배송 하나 맡기

- **멱등**: 이미 맡은 배송(dispatched·arrived)이 있으면 그것을 다시 200으로 준다. 응답을 잃어도 다시 부르면 된다.
- 새로 줄 때 조건: `reserved` · 예약 시각이 지남 · 목적지 장소에 `robot_dest`가 있음 → 그중 가장 이른 것 하나가 `dispatched`가 된다. 여러 로봇이 동시에 불러도 한 배송은 한 로봇에만 간다.
- AMR(운반 로봇)만 부를 수 있다(아니면 403 `robot_not_amr`).
- 새 배송을 주기 전에 EMR이 그 로봇의 Pinky `GET /status`를 묻는다(3장). 기준 밖이면 **204 + 헤더 `X-Claim-Skip-Reason`**.

| 204일 때 `X-Claim-Skip-Reason` | 뜻 | 할 일 |
|---|---|---|
| (헤더 없음) | 줄 배송이 없음 | 잠시 뒤 다시 |
| `robot_server_not_set` | EMR에 그 로봇의 서버 주소가 없음 | EMR 관리자가 환경 설정 → 로봇 탭에 입력 |
| `robot_server_unreachable` | Pinky가 2초 안에 답하지 않음·200 아님 | Pinky API 확인 |
| `robot_status_incomplete` | `/status`에 `battery_percent`·`contamination_percent`가 없음 | Pinky `/status`에 칸 추가 |
| `robot_not_ready` | `localized`·`nav2_ready`가 true가 아니거나 `state`가 `idle`이 아님 | 위치 다시 잡기·작업 끝내기 |
| `robot_battery_low` | 배터리 30 % 미만 | 충전 |
| `robot_contamination_high` | 오염도 70 초과 | 소독 |

응답 200 예 (10-23 실측):

```json
{
  "id": 41, "status": "dispatched", "scheduled_at": "2026-10-23T08:47:36Z",
  "destination": {"id": 8, "name": "4인실 왼쪽", "map_id": 5, "map_x_m": 0.35, "map_y_m": 1.78, "map_yaw_rad": 1.5708, "robot_dest": "ROOM4_L"},
  "items": [{"name": "B 약품", "quantity": 2}],
  "dispatched_at": "2026-10-23T08:47:36.403163Z", "arrived_at": null,
  "receipt_deadline_at": null, "receipt_method": "button"
}
```

### 2.3 `POST /robot/arrived` — 약제실 도착 (2026-10-27부터)

Pinky가 약제실 정밀 주차를 마치면 한 번 부른다. 본문 없음, 배송 id 필요 없음(이 로봇이 맡은 배송), 여러 번 불러도 같다.
**EMR은 서버 로그(`robot_at_pharmacy`)만 남긴다** — 배송 상태는 `dispatched` 그대로, 간호사 알림·배송 기록 없음. 응답은 맡은 배송(`status: "dispatched"`).

- 409 `robot_no_active_delivery`: 맡은 배송이 없음
- 409 `delivery_invalid_transition`: 이미 병실 도착(`arrived`)한 배송

### 2.4 `POST /robot/deliveries/{id}/progress` — 병실 도착·실패 보고

```json
{"stage": "arrived"}
{"stage": "failed", "failure_reason": "navigation_failed"}
```

| 필드 | 값 |
|---|---|
| `stage` | `arrived` = **병실 도착** → 배송 `arrived`, 간호사 화면에 "병동에 도착했습니다. 받아 주세요.", `receipt_deadline_at`(도착 + 5분) 채워짐 · `failed` |
| `failure_reason` | `failed`일 때만, 필수: `navigation_failed`(주행 실패) · `not_received`(마감까지 수령 없음) · `destination_blocked`(갈 수 없는 곳) · `robot_error`(그 밖) |

`failed`면 예약 때 뺀 재고를 EMR이 되돌린다. 같은 보고를 다시 보내도 200.
오류: 403 `delivery_not_assigned_to_robot`(다른 로봇의 배송) · 404 `delivery_not_found` · 409 `delivery_already_received`(이미 수령됨 — **성공으로 볼 것**) · 409 `delivery_invalid_transition`(예: 실패한 배송에 arrived).

도착 후 `receipt_deadline_at`까지 수령이 없으면 FMS가 `not_received`로 실패를 보고하는 것을 권한다 — EMR이 스스로 실패시키지 않는다.

### 2.5 배송 객체 (claim·arrived·progress·목록·`/robot/me` 공통)

| 필드 | 형식 | 뜻 |
|---|---|---|
| `id` | int | 배송 번호 |
| `status` | string | `reserved` · `dispatched` · `arrived` · `received` · `failed` · `cancelled` |
| `scheduled_at` | 시각 | 보낼 시간(예약 시각) |
| `destination` | 장소 | `{id, name, map_id, map_x_m, map_y_m, map_yaw_rad, robot_dest}` — **`robot_dest`를 Pinky `/goto`에** |
| `items` | `[{name, quantity}]` | 실을 물품 이름·수량 |
| `dispatched_at` · `arrived_at` | 시각 \| null | 맡은 시각 · 도착 시각 |
| `receipt_deadline_at` | 시각 \| null | arrived일 때 수령 마감 |
| `receipt_method` | string | `button`(사람이 화면에서 "받았습니다") · `none`(로봇 전용 장소 이동, 도착 보고가 곧 완료) |

간호사 정보는 로봇용 응답에 넣지 않는다.
좌표 `map_x_m`·`map_y_m`은 Pinky 그림 cm를 m로 바꾼 값이다(ROS map 프레임 아님) — 주행은 `robot_dest`로 한다.

지금 `robot_dest`가 있는 장소(10-27): `ROOM4_L`·`ROOM4_R`·`ROOM1_CUL`·`ROOM1_CUR`·`ROOM1_CLL`·`ROOM1_CLR`·`PHARMACY`(약제실)·`SURGERY`·`POCKET`·`CHARGER`·`START_A`.

## 3. 로봇 상태 API

먼저 알아 둘 것: **EMR은 로봇의 실시간 위치·배터리를 갖고 있지 않다.** 로봇이 EMR에 상태를 보고하는 API는 없고(로드맵 3단계, 미구현), 실시간 상태는 FMS가 Pinky `/status`를 직접 본다. EMR이 주는 로봇 상태는 아래 두 가지다.

| 메서드·경로 | 인증 | 주는 것 |
|---|---|---|
| `GET /robot/me` | 로봇 키 | 이 로봇 정보 · **맡고 있는 배송** · 수령 대기 시간 |
| `GET /robots` · `GET /robots/{id}` | 없음 | 등록된 로봇 목록·한 대: 종류, 상태 값, 로봇 서버 주소, **claim 때 받은 마지막 배터리·오염도** |

### 3.1 `GET /robot/me` — 내 정보·맡은 배송

언제: FMS를 시작·재시작할 때(맡던 배송 복구), 도착 후 수령을 기다리는 동안(수령 감지).

```json
{
  "robot": {"id": 1, "name": "배송로봇 1호", "robot_type": "amr"},
  "active_delivery": null,
  "receipt_wait_seconds": 300
}
```

- `active_delivery`: 이 로봇이 맡은 `dispatched`·`arrived` 배송(형식 2.5), 없으면 `null`.
- 도착 뒤 `active_delivery`가 `null`로 바뀌면 간호사가 받은 것이다 → 다음 행선지는 FMS가 정한다.

### 3.2 `GET /robots` · `GET /robots/{id}` — 로봇 목록·한 대 (10-27 실측)

```json
{
  "id": 1, "name": "배송로봇 1호", "robot_type": "amr", "status": "idle",
  "updated_at": "2026-10-23T09:12:59.060249Z",
  "has_api_key": false, "api_key_issued_at": null,
  "robot_server_url": "http://192.168.129.107:8080",
  "status_report": null
}
```

| 필드 | 뜻 |
|---|---|
| `robot_type` | `amr`(운반 로봇 — 배송) · `manipulator`(탑재 로봇) |
| `status` | `idle`·`delivering`·`charging`·`maintenance` — **관리자가 손으로 넣는 가정값**, 실제 상태가 아님 |
| `robot_server_url` | EMR이 claim 때 `/status`를 물을 Pinky API 주소 |
| `status_report` | `{battery_percent, contamination_percent, reported_at}` — **claim 때 EMR이 Pinky에서 받은 마지막 값**. 받은 적 없으면 `null` |

### 3.3 (참고) EMR이 Pinky `GET /status`에서 읽는 칸

claim이 새 배송을 줄 때 한 번, 2초 제한, GET만(로봇을 움직이지 않음).

| 칸 | 형식 | 기준 |
|---|---|---|
| `battery_percent` | number 0~100 | 30 미만이면 배송 안 줌 |
| `contamination_percent` | number 0~100 (0 = 깨끗) | 70 초과면 배송 안 줌 |
| `localized` · `nav2_ready` | bool | true가 아니면 배송 안 줌 |
| `state` | string | `idle`이 아니면 배송 안 줌 |

`battery_percent`·`contamination_percent`는 10-23 확인 때 Pinky `/status`에 없었다. 두 칸이 없으면 claim은 늘 204 `robot_status_incomplete`다.

## 4. 오류 코드

| HTTP | `code` | 언제 |
|---|---|---|
| 401 | `robot_key_missing` · `robot_key_invalid` | 키 없음·틀림·폐기 (지금은 꺼 둠) |
| 403 | `robot_not_amr` | AMR이 아닌 로봇이 claim |
| 403 | `delivery_not_assigned_to_robot` | 다른 로봇이 맡은 배송에 보고 |
| 404 | `delivery_not_found` | 없는 배송 번호 |
| 409 | `robot_no_active_delivery` | 맡은 배송 없이 `/robot/arrived` |
| 409 | `delivery_invalid_transition` | 병실 도착한 배송에 `/robot/arrived` 등 맞지 않는 단계 보고 |
| 409 | `delivery_already_received` | 수령된 배송에 failed — 성공으로 볼 것 |
| 422 | (FastAPI 형식) | 본문 값이 틀림 |

## 5. curl로 해 보기

```bash
E=http://192.168.129.135:8000/api/v1          # 지금은 키 없이 → 배송로봇 1호
curl $E/robot/me
curl "$E/robot/deliveries?due_only=false"
curl $E/robots/1
curl -i -X POST $E/robot/deliveries/claim     # 배송 상태가 바뀐다. 204면 -i로 X-Claim-Skip-Reason 확인
curl -X POST $E/robot/arrived                 # 약제실 도착 (로그만)
curl -X POST -H 'Content-Type: application/json' -d '{"stage":"arrived"}' $E/robot/deliveries/41/progress   # 병실 도착
curl -X POST -H 'Content-Type: application/json' -d '{"stage":"failed","failure_reason":"navigation_failed"}' $E/robot/deliveries/41/progress
```

OMX(로봇팔) 완료 신호 `GET /robot/{request_id}/end-point`는 따로: `omx_end_point_spec_2026-10-26.md`.
