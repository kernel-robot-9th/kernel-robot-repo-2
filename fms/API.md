# Pinky FMS API v1 — 관제 PC ↔ FMS

관제 PC는 배송 요청(방 번호 + 물품)과 OMX 준비·적재 완료만 FMS에 보낸다. 배차·경로·로봇 실행은 모두 FMS가 맡는다.
FMS는 로봇 상태(1초마다)와 이벤트를 관제 PC 주소로 직접 POST 한다.

- 설계 문서 (같은 내용, 그림 포함): https://claude.ai/artifact/BWUmL2VRThWKFZiocAKHYT
- 구현: 지금은 시뮬레이터 서버 `fms/sim_server.py` (가상 핑키). Swagger UI = `http://<FMS>:8770/docs`, 명세 = `/api/v1/openapi.json`
- 2026-10-27 확정. 바꾸면 이 파일, `openapi_v1.py`, 설계 문서를 같이 고친다.

## 배송 한 번의 순서

```
관제 PC                      FMS                          핑키              OMX
  │ 1 POST /orders  ─────────▶│                               │                 │
  │◀──── 2 batch_assigned ────│  (묶음 + 맡은 핑키, 핑키는 제자리 대기)          │
  │ 3 물품 준비 ───────────────────────────────────────────────────────────────▶│
  │ 4 POST /batches/{id}/ready ▶│                               │                 │
  │                            │ 5 약제실로 ─────────────────▶│                 │
  │                            │◀──────────── 6 정밀 주차 끝 ─│                 │
  │◀── 7 robot_at_pharmacy ────│                               │                 │
  │ 8 핑키에 싣기 ─────────────────────────────────────────────────────────────▶│
  │ 9 POST /batches/{id}/loaded▶│                               │                 │
  │                            │ 10 병실로 ──────────────────▶│                 │
  │                            │◀────── 11 병실에서 한 바퀴 끝 ─│                 │
  │◀── 12 order_delivered ─────│   (병실이 여럿이면 10~12 반복, 끝에 batch_completed)
```

병실에서는 제자리 한 바퀴가 배송 완료다. 다음 일이 있으면 1~5초(무작위) 쉬고 출발한다.

## 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| FMS 주소 | `http://<FMS IP>:8770` (시뮬레이터 기본 포트) |
| 관제 PC 주소 | FMS 를 띄울 때 `--control-url http://<관제 PC IP>:8000` 으로 알려 준다 |
| 형식 | HTTP + JSON(UTF-8), 경로는 `/api/v1/`. 키는 영어 snake_case 만 |
| 시간 | ISO 8601, 한국 시간 (`2026-10-27T14:03:21+09:00`) |
| ID | 문자열. 주문 `o-17`, 묶음 `b-5`, 이벤트 `e-1203`. `request_id` 는 관제 PC 가 만든다 |
| 좌표 | cm, 경기장 그림 왼쪽 아래 = (0, 0), x 오른쪽 · y 위, 위치 = 로봇 라이다 중심, 방향 0° = +x, 90° = +y |
| 물품 | 자유 문자열. FMS 는 내용을 보지 않는다. **주문 1건 = 물품 1개** (2개면 주문 2번) |
| 묶음 | 핑키 한 대가 한 번에 싣는 주문 (최대 3건). 배차 때 정해지면 바뀌지 않는다. 맡은 주문 수만큼만 싣는다 (여분 없음) |

오류 본문은 항상 `{"error": "<코드>", "message": "<설명>", ...}`.

**방 번호** — 주문의 `room`. "101" 처럼 숫자만도 받는다. 약제실은 상태 표시에만 나오고 주문 목적지가 아니다.

| 방 번호 | 방 | 방문 때 오염도 |
| --- | --- | --- |
| 101호 | 4인실 왼쪽 | +50 |
| 102호 | 4인실 오른쪽 | +50 |
| 103호 | 1인실 왼쪽 위 | +10 |
| 104호 | 1인실 가운데 위-왼 | +10 |
| 105호 | 1인실 가운데 위-오른 | +10 |
| 106호 | 1인실 왼쪽 아래 | +10 |
| 107호 | 1인실 가운데 아래-왼 | +10 |
| 108호 | 1인실 가운데 아래-오른 | +10 |
| 수술실 | 수술실 (오염도 0 인 로봇만 들어감) | 0 |
| 약제실 | 상태 표시용 | — |

**로봇 번호** — 메시지의 `robot` 은 관제 PC 번호, `name` 은 핑키 이름. 표는 `fms/robots.yaml`.

| robot | name |
| --- | --- |
| 1 | pinky_6364 |
| 2 | pinky_ee3e |
| 3 | pinky_62f4 |

## 관제 PC → FMS

| 메서드 | 경로 | 하는 일 | 성공 | 실패 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/orders` | 배송 요청 1건 | 202 새 주문 · 200 같은 `request_id` 다시 | 400 `missing_field` `unknown_room` `bad_json` |
| GET | `/api/v1/orders/{order_id}` | 주문 조회 | 200 | 404 |
| DELETE | `/api/v1/orders/{order_id}` | 취소 (`queued` 일 때만) | 200 | 404 · 409 `order_locked` |
| GET | `/api/v1/batches/{batch_id}` | 묶음 조회 | 200 | 404 |
| POST | `/api/v1/batches/{batch_id}/ready` | OMX 준비 끝 → 핑키를 약제실로 | 200 (`eta_s`) | 404 · 409 `bad_batch_state` |
| POST | `/api/v1/batches/{batch_id}/loaded` | OMX 가 핑키에 다 실음 → 병실로 출발 | 200 | 404 · 409 `bad_batch_state` |
| GET | `/api/v1/state` | 로봇 전부 + 끝나지 않은 주문·묶음 + `last_seq` | 200 | |
| GET | `/api/v1/rooms` · `/api/v1/map` | 방 번호 목록 · 지도(벽, 노드 좌표, 엣지) | 200 | |
| GET | `/api/v1/events?after=<seq>` | 최근 이벤트 (시험용: 관제 PC 서버 없이 확인) | 200 | |

```bash
F=http://<FMS IP>:8770
curl -X POST -H "Content-Type: application/json" \
     -d '{"request_id":"pc-20261027-0001","room":"101호","item":"진통제"}' $F/api/v1/orders
# → 202 {"order_id":"o-17","request_id":"pc-20261027-0001","room":"101호","item":"진통제","status":"queued",
#        "batch_id":null,"robot":null,"created_at":"2026-10-27T14:03:21+09:00","delivered_at":null,"fail_reason":null}
curl -X POST $F/api/v1/batches/b-5/ready      # → 200 {"batch_id":"b-5","status":"called","robot":1,"name":"pinky_6364","eta_s":42}
curl -X POST $F/api/v1/batches/b-5/loaded     # → 200 {"batch_id":"b-5","status":"delivering"}
curl $F/api/v1/state
```

- `request_id` 가 같으면 새 주문을 만들지 않고 처음 주문을 돌려준다 (네트워크가 끊겨 다시 보내도 안전).
- 로봇이 모두 바빠도 거절하지 않고 대기열에 넣는다.
- `ready` 는 묶음이 `assigned` 일 때만, `loaded` 는 `at_pharmacy` 일 때만 받는다. `eta_s` = 핑키가 약제실 정밀 주차를 끝낼 때까지 예상 초.

## FMS → 관제 PC

| FMS 가 보내는 곳 (관제 PC 쪽) | 언제 | 실패하면 |
| --- | --- | --- |
| `POST /api/v1/fms/robot-status` | 1초마다, 로봇 전부 | 다시 안 보냄 (1초 뒤 새 상태) |
| `POST /api/v1/fms/events` | 일이 생길 때 1건씩 | 연결 실패·5xx 면 1, 2, 4초 뒤 다시. 4xx 는 다시 안 보냄 |

관제 PC 는 2xx 만 돌려주면 된다. FMS 는 1초 넘게 기다리지 않고, 관제 PC 가 꺼져 있어도 배송은 계속한다.
같은 `event_id` 가 두 번 오면 한 번만 처리하고, `seq` 가 비면 `GET /api/v1/state` 로 다시 맞춘다.

**로봇 상태**

```json
{"time": "2026-10-27T14:05:02+09:00",
 "robots": [{"robot": 1, "name": "pinky_6364", "online": true, "state": "moving", "task": "delivery",
             "pose": {"x": 130.0, "y": 80.1, "heading": 90.4},
             "node": "R58", "next_node": "GB130", "place": "오른쪽 협로",
             "destination": {"node": "ROOM1_CLR", "room": "108호"},
             "path": ["R58", "GB130", "B2_130", "B2_78"],
             "battery": 70, "contamination": 10, "load": 2, "capacity": 3,
             "batch_id": "b-5", "orders": ["o-17", "o-18"]}]}
```

| 필드 | 뜻 |
| --- | --- |
| `state` / `task` | 지금 동작 / 맡은 일 (아래 상태 값) |
| `pose` | 위치 cm, 방향 ° |
| `node`, `next_node`, `path` | 지도 노드 이름 (`GET /api/v1/map`): 마지막으로 지난 곳, 다음, 남은 길 |
| `place` | 사람이 읽는 위치: 아래 복도, 위 복도, 왼쪽 협로, 오른쪽 협로, 단일차선 협로, 약제실, 101호…, POCKET(대기), 충전기 |
| `destination` | 지금 가는 곳. 병실·약제실이면 `room` 에 이름, 아니면 `null` |
| `battery` | 0~100. 병실 하나당 −10, 20 이하면 충전하러 감 |
| `contamination` | 0~100. 1인실 +10, 4인실 +50, POCKET 5초면 0 |
| `load` / `capacity` | 실은 물품 수 / 최대 3 |
| `batch_id`, `orders` | 맡은 묶음, 아직 배송 안 끝난 주문 |

**이벤트** — 공통 `event_id`, `seq`, `time`, `type` + 종류별 필드.

```json
{"event_id": "e-1203", "seq": 1203, "time": "2026-10-27T14:03:22+09:00", "type": "batch_assigned",
 "batch_id": "b-5", "robot": 1, "name": "pinky_6364",
 "orders": [{"order_id": "o-17", "room": "101호", "item": "진통제"}, {"order_id": "o-18", "room": "104호", "item": "해열제"}],
 "count": 2, "rooms": ["104호", "101호"]}
```

| type | 언제 | 더 붙는 필드 |
| --- | --- | --- |
| `order_created` | 주문 받음 | `order_id`, `request_id`, `room`, `item` |
| `batch_assigned` | 배차 → **OMX 준비 시작** | `batch_id`, `robot`, `name`, `orders`, `count`, `rooms`(방문 순서) |
| `robot_called` | `ready` 받고 핑키가 약제실로 출발 | `batch_id`, `robot`, `eta_s` |
| `robot_at_pharmacy` | 약제실 정밀 주차 끝 → **OMX 적재 시작** | `batch_id`, `robot` |
| `batch_departed` | `loaded` 받고 병실로 출발 | `batch_id`, `robot`, `rooms` |
| `robot_departed` | 로봇이 다음 목적지로 출발 (약제실·병실·POCKET·충전·주차) | `robot`, `task`, `from`, `to`(`node`, `room`) |
| `robot_arrived` | 목적지 도착 | `robot`, `node`, `room` |
| `order_delivered` | 병실에서 한 바퀴 끝 = 배송 완료 | `order_id`, `room`, `robot`, `batch_id` |
| `batch_completed` | 묶음의 마지막 배송 끝 | `batch_id`, `robot` |
| `order_canceled` | 취소됨 | `order_id` |
| `order_failed` | 배송 실패 (아직 시뮬레이터에 없음) | `order_id`, `batch_id`, `reason` |
| `robot_error` | 로봇 멈춤·통신 끊김·복구 (아직 시뮬레이터에 없음) | `robot`, `reason`, `online` |

## 상태 값

| 주문 `status` | 뜻 |
| --- | --- |
| `queued` | 노는 핑키를 기다림. 이때만 취소 가능 |
| `assigned` | 묶음에 들어감 (OMX 준비 중 / 핑키가 약제실로 가는 중) |
| `loaded` | 핑키에 실려 병실로 가는 중 |
| `delivered` · `canceled` · `failed` | 끝 |

| 묶음 `status` | 뜻 | 다음으로 넘어가는 계기 |
| --- | --- | --- |
| `assigned` | OMX 준비 중, 핑키는 제자리에서 기다림 | 관제 PC `ready` |
| `called` | 핑키가 약제실로 가는 중 | 정밀 주차 끝 |
| `at_pharmacy` | OMX 적재 기다림 | 관제 PC `loaded` |
| `delivering` | 병실을 도는 중 | 마지막 병실 한 바퀴 끝 |
| `completed` · `failed` | 끝 | |

로봇 `state`: `idle` 대기 · `reserved` 묶음을 맡고 `ready` 기다림 · `moving` 이동 · `waiting` 길 막혀 기다림 · `docking` 정밀 주차 ·
`loading` 적재 기다림 · `spinning` 병실 한 바퀴 · `pausing` 다음 일 전 1~5초 · `decon` POCKET 5초 · `charging` 충전 · `error` 멈춤.
로봇 `task`: `none` · `delivery` · `decon` · `charge` · `park` · `yield`(비켜 주기).

## 시뮬레이터로 시험하기

```bash
python3 fms/sim_server.py --host 0.0.0.0 --control-url http://<관제 PC IP>:8000 --no-auto-omx
```

- `--control-url` 을 주면 로봇 상태·이벤트를 그 주소로 보낸다. 없으면 안 보내고 `GET /api/v1/events?after=0` 으로만 볼 수 있다.
- **가상 OMX** (기본 켬): `ready` 는 배차 15초 뒤, `loaded` 는 주차 10초 뒤 시뮬레이터가 스스로 보낸다. 진짜 관제 PC 를 붙일 땐
  `--no-auto-omx`, 화면의 "가상 OMX" 체크 해제, 또는 `POST /api/control {"auto_omx": false}`. 끄면 화면 "묶음" 칸의
  "준비 완료"·"적재 완료" 버튼으로 관제 PC 대신 보낼 수도 있다.
- 실행 중에 바꾸기: `POST /api/control {"control_url": "http://…:8000"}` (null = 끔).

## 아직 정할 것

- 관제 PC 가 받을 경로 (`/api/v1/fms/robot-status`, `/api/v1/fms/events` 제안) — 관제 PC 담당
- FMS 서버가 돌 컴퓨터와 IP, 로봇 2·3번에 배정할 핑키
- `ready`·`loaded` 가 오래 안 오면 (지금은 핑키가 계속 기다림), 배송 중 로봇이 멈추면 실은 주문 처리 (`order_failed` 뒤 다시 넣기?)
- 관제 PC 서버의 예전 '배송 배정'(`/api/v1/robot/arrived`, `robot_no_active_delivery`)은 없앤다. 배송 배정·실행은 FMS 가 맡는다
