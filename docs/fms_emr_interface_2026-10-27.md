# EMR ↔ FMS API v1 인터페이스 분석 (2026-10-27)

> **EMR은 상위 관제다 (2026-10-27 사용자).** EMR이 붙는 바깥 시스템은 **팀원 FMS**(AMR·Pinky 담당)와 **팀원 OMX API**(로봇팔) **둘뿐**이다. Pinky 등 로봇에 직접 붙지 않고, 로봇도 EMR을 직접 부르지 않는다. 배차·경로·교통·충전은 FMS, 집기·놓기는 OMX가 한다.

팀원 FMS가 10-27에 **API v1을 확정**했다(`kernel-robot-repo-2` main의 `fms/API.md`, `fms/openapi_v1.py`, 시뮬레이터 `fms/sim_server.py`).
이 문서는 EMR(관제 PC)이 그 API에 붙으려면 **무엇을 바꿔야 하는지**를 정리한다. **분석만 했고 EMR 코드는 바꾸지 않았다.**
FMS 쪽 문제는 같은 저장소의 `docs/fms_api_v1_review_2026-10-27.md`(시뮬레이터 실측 점검)에 있고, 여기서는 EMR에 영향이 있는 것만 가져왔다.

## 0. 한 줄 요약

- **바뀌는 방향**: 지금 EMR은 로봇이 EMR에서 배송을 가져가는(claim) 방식이다. FMS v1은 반대다. **EMR이 주문을 보내고(`POST /orders`), FMS가 로봇 상태(1초마다)와 이벤트를 EMR로 보낸다.** 배차·경로·교통은 FMS가 한다.
- **지금은 붙지 않는다**: FMS가 보낼 곳 `POST /api/v1/fms/robot-status`·`/api/v1/fms/events`가 EMR에 없다(404). FMS는 4xx를 다시 보내지 않으므로, 이대로 붙이면 이벤트가 소리 없이 모두 버려진다.

**사용자 결정 (10-27)**

| 항목 | 결정 |
|---|---|
| OMX 준비 끝 `ready` | **OMX 적재(이미지·YOLO) 완료 신호**를 받으면 보낸다(10-27 사용자 시나리오: 적재 → 완료 → AMR 호출). 처음 정했던 "배차 즉시 자동"을 바꿨다 |
| OMX 적재 끝 `loaded` | 정밀 주차 뒤 **OMX 탑재 완료 신호**를 받으면 보낸다. 두 완료 신호는 같은 `request_id`로 오므로 OMX `GET /status`의 `pinky` 값(`holding`·`completed`)으로 구분한다 (`robot_access_amr_omx_2026-10-27.md` 2.2) |
| 배송 완료 | FMS `order_delivered` = EMR **arrived**("받아 주세요"). 간호사가 "받았습니다"를 눌러야 received |
| 예전 로봇 API (claim 등) | **남겨 두고 쓰지 않는다** |
| FMS ↔ EMR 인증 (10-27 오후) | **인증 없이 진행한다**(예정). 공유 키 등은 나중에 |
| `ready`·`loaded` 두 번째가 409 (10-27 오후) | **FMS는 그대로 둔다.** EMR이 409 `bad_batch_state`를 "이미 넘어감"으로 보고 오류로 다루지 않는다 |
| `order_failed`·`robot_error` (10-27 오후) | 시뮬레이터에 없으니 **시험에서는 무시**한다. 처리 코드는 API.md 필드대로 만든다 |
| 1초 응답 제한 (10-27 오후) | 걱정하지 않는다. 늦어서 FMS가 다시 보내도 EMR이 받은 것은 저장되어 있고, `event_id`로 한 번만 처리하면 된다. 단, **올바른 이벤트에 4xx를 주지 않는다**(4xx는 FMS가 다시 안 보냄) |
| 장소·지도를 FMS `/rooms`·`/map`에서 가져오기 (10-27 오후) | **아직 하지 않는다. 문서에만 남긴다**(3.11) |

## 1. 시뮬레이터로 확인한 것 (10-27, 포트 18770, 확인 뒤 내림)

| 보낸 `room` | 결과 |
|---|---|
| `4인실 왼쪽` (EMR 장소 이름) | 202, `room: "101호"` |
| `ROOM4_L` (EMR `robot_dest`) | 202, `room: "101호"` |
| `1인실 가운데 위-왼` | 202, `104호` |
| `수술실` | 202, `수술실` |
| `약제실`, `301호` | 400 `unknown_room` (쓸 수 있는 이름: 101호~108호, 수술실) |

- 주문 4건(101호 2건, 104호 1건, 수술실 1건)이 **묶음 2개**로 나뉘었다.
  - `b-1` = 로봇 2번, 3건, 방문 순서 `["101호", "104호"]`
  - `b-2` = 로봇 3번, 수술실
  - **한 묶음에 서로 다른 EMR 신청의 물품이 섞일 수 있다.**
- 이벤트 순서: `order_created` ×4 → `batch_assigned` ×2 → `robot_called` → `robot_departed` …
  - 가상 OMX를 켜 두면 `ready`는 배차 15초 뒤 시뮬레이터가 스스로 보낸다.
- `GET /api/v1/state`의 키: `time`, `robots`, `orders`, `batches`, `last_seq`
  - 로봇 하나의 예: `{"robot":1,"name":"pinky_6364","online":true,"state":"idle","pose":{"x":20,"y":7.5,"heading":0.0},"place":"아래 복도","battery":100,"contamination":0,"load":0,"capacity":3,…}`

### 1.1 점검 문서(`fms_api_v1_review_2026-10-27.md`) 다시 재 봄 (10-27, `--no-auto-omx`)

EMR 동작에 영향이 있는 항목만 다시 쟀다. 모두 문서와 같았다.

| 점검 문서 항목 | 다시 잰 결과 |
|---|---|
| 1. `ready` 두 번 | 첫 번째 200 `{"status":"called","eta_s":32}`, 두 번째 409 `bad_batch_state`. 본문에는 `message` 글자만 있고 `status` 칸은 없다 |
| 1. `called`일 때 `loaded` | 409 `bad_batch_state` ("at_pharmacy 일 때만 loaded") |
| 4. 같은 `request_id` + 다른 방·물품 | 처음 주문(101호, A)을 그대로 돌려준다. 새 주문도 오류도 없다 |
| 5. 이벤트의 `request_id` | `order_created`에만 있다. `batch_assigned`·`robot_called`·`robot_departed`에는 없다 |
| 6. 배정된 주문 취소 | `DELETE /orders/o-1` → 409 `order_locked` |
| 10. 잘못된 요청 | `GET /events?after=abc` → 응답 없이 연결이 끊긴다. PUT·PATCH → 501 |

- 점검 문서 4번의 재현 예시 `{"request_id":"a","room":"101"}`에는 `item`이 빠져 있다. 그대로 보내면 지금 서버는 400 `missing_field`(item)를 준다. 결론은 `item`을 넣어 다시 재도 같았다.
- 점검 문서 0장의 "EMR은 claim·`/robot/arrived`로 가져감"은 10-27 오전 기준이다. 그 뒤 `/robot/arrived`는 약제실 도착 전용(로그만)으로 바뀌었다.
  - v1에서는 약제실 도착이 FMS 이벤트 `robot_at_pharmacy`로 오므로 `/robot/arrived`는 쓰이지 않는다.
- 이 문서에 반영한 점검 문서의 다른 항목:
  - 16번: FMS를 다시 시작하면 `request_id` 표가 비워진다 → 3.2 "다시 맞추기"
  - 7번: `loaded` 직후 잠깐 주문이 아직 `assigned`로 보인다 → 주문 상태는 이벤트로 판단

### 1.2 OpenAPI 명세 확인 + 이벤트 모양 실측 (10-27 오후, 포트 18770, 확인 뒤 내림)

- 사용자가 받은 OpenAPI JSON은 저장소 `fms/openapi_v1.py`(커밋 `4d2dccd`)와 **완전히 같다**(JSON 비교).
- 시뮬레이터 `--no-auto-omx --control-url`로 웹훅을 받는 가짜 서버를 붙였다. EMR처럼 주문 7건(1건 바로 취소, 1건 약제실)을 넣고, `batch_assigned` → `ready`, `robot_at_pharmacy` → `loaded`를 보냈다. 묶음 2개가 끝날 때까지 돌렸다(약 4분, 이벤트 41건, robot-status 249번).

**이벤트 필드는 API.md 표와 10종 모두 같았다**(빠진 칸·더 있는 칸 없음). 그래서 이벤트 처리 코드는 API.md 표대로 만들면 된다. 고칠 것은 아래 정리에만 해당한다.

| 확인한 것 | 결과 | EMR이 할 일 |
|---|---|---|
| 이벤트 순서·`seq` | 순서대로, 빠짐·중복 없음 | `seq`가 비면 `/state`로 다시 맞춤(3.2) |
| 이벤트가 늦게 오는 정도 | 이벤트 `time`부터 받기까지 평균 1.10초, 최대 1.49초 | 화면 표시만 늦음. 처리에는 영향 없음 |
| `robot_departed` | `from`은 문자열 `"T1_20"`, `to`는 객체 `{"node","room"}` | 두 모양을 그대로 읽는다(5장 6번 요청은 유지) |
| `robot_arrived` | `node`·`room`이 평평하게 옴 | 그대로 읽음 |
| 오류 본문 | OpenAPI `Error`는 `{error, message}`인데 `unknown_room`은 `rooms`(쓸 수 있는 방 목록)가 더 있다 | 클라이언트가 `error`를 EMR `code`로 바꿔 읽음. `rooms`는 로그에만 |
| 같은 `request_id` 다시 | 200 + 처음 주문(`o-1`) | 응답을 잃었을 때 다시 보내도 안전 |
| 바로 취소 | `queued`라 200 `canceled`, 이벤트 `order_canceled` | 4장 결정 1 (나) 안 그대로 |
| `ready`·`loaded` 두 번째 | 409 `bad_batch_state` + 지금 상태를 글로 줌 | 위 결정: 오류로 보지 않음 |
| 묶음 섞임 | `b-1` = EMR 신청 2건(101호 A 약품 ×2 + 104호 환자복) | 4장 결정 2 |
| `order_id` 얻기 | `POST /orders` 응답(202·200)에 `order_id`가 바로 옴 | 응답에서 저장하면 `batch_assigned.orders[].order_id`로 찾을 수 있다 → 5장 2번 요청은 급하지 않음 |
| robot-status 한 대 | `robot, name, online, state, task, pose{x,y,heading}, node, next_node, place, destination, path, battery, contamination, load, capacity, batch_id, orders` | OpenAPI `RobotStatus`와 같음. 예전 Pinky `/status`에 없던 배터리·오염도가 있다 |

### 1.3 개별 물품 주문 25건 시험 (10-27 오후, :8770 사용자 시뮬레이터) — 중단

- 신청 1건 = 물품 1개로 25건을 넣었다. 1초 안에 묶음 3개(물품 3개씩, 로봇 1·2·3)로 배차됐고, `ready` 200 뒤 로봇들이 약제실로 출발했다.
- **시험 9초쯤 시뮬레이터가 다시 시작됐다**(화면 '다시 시작'). 이벤트 `seq` 35에서 끊겼고 `/state`는 `last_seq` 0, 주문 0, 묶음 0이 됐다. 넣은 25건이 알림 없이 사라졌고 `control_url`도 비워져 웹훅이 멈췄다. 240초 뒤 묶음 3개가 '멈춤'으로 기록됐다.
  - EMR이었다면 25건이 dispatched로 멈춰 있다 → 3.2 '다시 맞추기'와 5장 8번 요청(FMS가 다시 시작됐음을 알리기)이 실제로 필요함을 확인했다.
  - EMR 쪽 대응 후보: `last_seq`가 줄었거나 `/state`에 진행 중 주문이 없으면 'FMS 초기화'로 보고 관리자 알림.
- 그 밖의 오류(4xx·5xx, `seq` 빠짐, 다른 방 배송, 로봇 오프라인)는 멈추기 전까지 0건. 시뮬레이터가 비워져 나머지는 다시 시험해야 한다.

### 1.4 개별 물품 주문 10건 시험 (10-27 오후, :8770, 5배속, 장소를 방 번호로 바꾼 뒤) — 오류 0

- EMR 장소 `robot_dest`(이제 FMS 방 번호)를 그대로 `room`으로 보냈다. 신청 1건 = 물품 1개, 10건.
- **10건 모두 배송**, 78.4초(시뮬레이터 5배속). 주문부터 도착까지 최소 37.2초 · 중간값 52.2초 · 최대 78.4초.
- 묶음 4개: 1초 안에 3개(물품 3개씩, 로봇 1·2·3) + 남은 1건은 58초에 로봇 1이 다시 받음(`b-4`). 묶음 크기는 로봇 적재 한도 3을 넘지 않았다.
- 한 묶음에 방 2~3곳(예: `b-1` 수술실·108호·107호). 같은 방 2건은 한 번에 도착(105호, 104호).
- 로봇이 스스로 한 일: 오염 처리(decon) 3번, 길 비켜 주기(yield) 1번, 주차(park) 1번 — EMR은 기록만 하면 된다. 배터리 20 이하 없음.
- **오류 0건**: 4xx·5xx 없음, 이벤트 `seq` 빠짐 없음, 다른 방 배송 없음, 로봇 끊김 없음, 멈춘 묶음 없음, FMS 초기화 없음.

## 2. 배송 한 건의 대응표 (FMS v1 ↔ EMR)

| FMS | EMR이 할 일 | EMR 배송 상태 |
|---|---|---|
| (신청 시각이 됨) | 물품 **1개당** `POST /api/v1/orders {request_id, room, item}` | reserved (+ 보냈다는 표시, 4장 결정 1) |
| `batch_assigned` | OMX **적재** 명령 `POST /command` → 적재 완료 신호 → `POST /api/v1/batches/{id}/ready` | **dispatched**, 로봇 = FMS 로봇 번호에 맞는 EMR 로봇. 간호사에게 "곧 로봇이 출발합니다." |
| `robot_called` · `robot_departed` | 기록만 | dispatched |
| `robot_at_pharmacy` | OMX **탑재** 명령 `POST /pinky`. OMX용 `request_id`를 만들고 `batch_id`와 함께 저장 | dispatched |
| OMX → `GET /robot/{request_id}/end-point` | 적재 신호면 `ready`, 탑재 신호면 `POST /api/v1/batches/{id}/loaded` | dispatched |
| `order_delivered` | 그 주문을 끝남으로 표시. **신청의 물품이 모두 delivered면** 다음 칸으로 | **arrived** ("병동에 도착했습니다. 받아 주세요.") |
| (간호사 "받았습니다") | 지금 그대로 `POST /deliveries/{id}/receipt` | **received** |
| `order_failed` · `robot_error` (시뮬레이터에 아직 없음) | 실패 처리, 재고 복구, 실패 알림 | failed |
| `order_canceled` | EMR 취소로 생긴 것인지 확인 | cancelled |

## 3. EMR에 새로 필요한 것 (구현할 때 할 일)

### 3.1 FMS로 보내기 (EMR → FMS)
- 주기 작업을 둔다(예: 5초마다).
  - 대상: 신청 시각이 지난 reserved 배송, 목적지가 FMS 방인 것
  - 물품 단위로 `POST /api/v1/orders`를 보낸다
- `request_id`는 결정적으로 만든다. 예: `emr-d{배송 id}-s{비품 id}-{n번째}`.
  - FMS는 같은 `request_id`에 처음 주문을 200으로 돌려주므로, 응답을 잃어 다시 보내도 안전하다.
- 보낼 때 `room`은 방 번호(`101호`)를 쓴다(3.5). `item`은 비품 이름이다.
- 틀: 보관 브랜치 `fms-order-2026-10-26`의 `app/clients/fms.py`·`app/services/fms_order.py`
  - 주소를 `/delivery-batches` → `/api/v1/orders`로 바꾸고, 본문을 묶음 → 주문 1건 단위로 바꾼다.
- 묶음 조작도 같은 클라이언트에 둔다: `POST /batches/{id}/ready`·`/loaded`, `GET /orders/{id}`, `DELETE /orders/{id}`, `GET /state`.
  - 이 요청들은 FMS·OMX에서 이벤트를 받는 요청 안에서 부르지 않는다(3.2).

### 3.2 FMS에서 받기 (FMS → EMR, 새 엔드포인트 2개)

| 경로 | 언제 | EMR이 할 일 |
|---|---|---|
| `POST /api/v1/fms/robot-status` | 1초마다, 로봇 전부 | 로봇마다 마지막 값을 덮어쓴다: `online`, `state`, `task`, `pose`, `place`, `battery`, `contamination`, `load`, `batch_id` |
| `POST /api/v1/fms/events` | 일이 생길 때 1건씩 | `event_id`로 중복을 거르고 저장한 뒤 2장 표대로 처리 |

- **1초 안에 2xx를 돌려줘야 한다.**
  - FMS는 1초를 넘기면 실패로 보고, 1·2·4초 뒤 다시 보낸 다음 버린다.
  - 그래서 받는 요청 안에서는 저장만 한다. `ready`·`loaded` 보내기, OMX 명령 같은 바깥 HTTP 호출은 그 뒤에 따로 한다(백그라운드 작업이나 주기 작업).
- **순서를 믿지 않는다.**
  - robot-status가 관련 이벤트보다 먼저 올 수 있다(점검 문서 3번: 이벤트가 평균 0.96초 늦음).
  - 주문·묶음 상태는 `seq`와 `status`로 판단한다.
- **다시 맞추기**: `seq`가 비거나 EMR을 다시 켰을 때는 `GET /api/v1/state`로 진행 중인 주문·묶음을 다시 맞춘다.
  - **FMS가 다시 시작된 경우**(점검 문서 16번): 주문·묶음·`request_id` 표가 비워진다.
    - EMR이 저장한 `order_id`를 조회하면 404가 나온다.
    - 같은 `request_id`로 다시 보내면 새 주문이 생긴다.
    - 그래서 `/state`에 없는 진행 중 주문을 그냥 다시 보내지 않는다. 실패로 처리할지, 다시 보낼지는 FMS와 정한다.
- **인증**: FMS는 인증 없이 보낸다. 다른 망에서 이 경로를 막을 방법(공유 키 헤더 등)을 FMS와 함께 정한다.

### 3.3 DB (마이그레이션 0015부터)

| 표·칸 | 내용 |
|---|---|
| `fms_orders` (새 표) | 배송 id, 비품 id, n번째, `request_id`, FMS `order_id`, `batch_id`, 주문 상태, FMS 로봇 번호, 시각들 |
| `fms_events` (새 표) | 받은 `event_id`, `seq`, `type`, 받은 시각 — 중복 거르기와 추적용 |
| 로봇 상태 마지막 값 | 지금 `robot_status_reports`(배터리·오염도)를 넓힌다: `x_cm`·`y_cm`·`heading_deg`·`place`·`online`·`state`·`load` |
| `robots.fms_robot_number` (새 칸) | FMS `robot` 1·2·3 ↔ EMR 로봇 |
| OMX 요청 ↔ 묶음 | OMX `request_id` → `batch_id` (OMX 완료 신호로 `loaded`를 보낼 때 찾음) |

- 보관 브랜치 `fms-order-2026-10-26`도 0015·0016을 쓴다. 이 작업이 그 브랜치를 대신하므로 **그 브랜치는 합치지 않는다**. 필요한 코드만 손으로 옮긴다. 사용자 확인이 필요하다.

### 3.4 로봇 번호
- FMS `robots.yaml`: 1 = `pinky_6364`, 2 = `pinky_2`, 3 = `pinky_3`
- EMR 로봇: 1 배송로봇 1호, **2 적재 매니퓰레이터 1호**, 3 배송로봇 2호, 4 배송로봇 3호
- 번호가 어긋나므로 EMR id를 그대로 쓰지 않고 `robots.fms_robot_number`로 잇는다. 로봇 탭에서 관리자가 넣는다.

### 3.5 장소 (데이터만, 코드 변경 아님)

| EMR 장소 (id) | 지금 `robot_dest` | 바꿀 값 |
|---|---|---|
| 4인실 왼쪽 (8) | ROOM4_L | 101호 |
| 4인실 오른쪽 (10) | ROOM4_R | 102호 |
| 1인실 가운데 위-왼 (11) | ROOM1_CUL | 104호 |
| 1인실 가운데 위-오른 (12) | ROOM1_CUR | 105호 |
| 1인실 가운데 아래-왼 (13) | ROOM1_CLL | 107호 |
| 1인실 가운데 아래-오른 (14) | ROOM1_CLR | 108호 |
| 수술실 (15) | SURGERY | 수술실 |
| **없음** | — | **103호(1인실 왼쪽 위)·106호(1인실 왼쪽 아래)를 새로 추가** |
| 약제실 (9), 대기 포켓 (16), 충전 (17), 출발점 A (18), 301호 (3) | — | 신청 목적지에서 뺀다 (FMS 400). `robot_only` 표시 또는 `robot_dest` 비우기 |

- FMS는 노드 이름(ROOM4_L)과 장소 이름도 받지만, 계약은 방 번호다. 응답과 이벤트도 방 번호로 온다.
- **10-27 오후 적용함(사용자 "EMR에 동일하게 수정")**: 위 7곳의 `robot_dest`를 방 번호로, 이름을 FMS 노드 이름(`101호 4인실 왼쪽` …)으로 바꿨다. 103호(id 20)·106호(id 21)는 Pinky 아레나 지도에 FMS 좌표(cm/100)로 새로 만들었다(방향 3.1416은 가정). FMS `/rooms`의 주문 가능 방 9곳과 EMR 장소 9곳이 같다.
  - 바꾸기 전 값은 세션 임시 폴더에 저장했다. 되돌리려면 이름·`robot_dest`를 위 표의 '지금' 값으로 PATCH하고 id 20·21을 지운다.
  - ⚠️ `scripts/import_pinky_dests.py`를 다시 돌리면 `robot_dest`·이름이 Pinky 값(ROOM4_L …)으로 돌아간다 — 쓰지 않는다(EMR은 Pinky에 직접 붙지 않음).
  - 약제실·대기 포켓·충전·출발점 A·301호는 그대로 두었다(신청 목적지에서 빼는 것은 연동 작업 때).

### 3.6 좌표
- FMS `pose`: 경기장 그림 cm, 왼쪽 아래 원점, heading °
- EMR "Pinky 아레나" 맵(`emr/backend/scripts/import_pinky_dests.py`)은 같은 그림을 cm/100 = m로 옮긴 것이다.
- 그래서 로봇 위치를 EMR 지도에 그대로 그릴 수 있다. 팀원 그래프가 바뀌면 원점이 같은지 다시 확인한다.

### 3.7 OMX 완료 신호와 `ready`·`loaded`
- 지금 `app/services/omx_signal.py`는 로그만 남긴다.
  - 고칠 것: `request_id`로 묶음과 단계(적재·탑재)를 찾아, 적재 완료면 `ready`, 탑재 완료면 `loaded`를 보내게 잇는다. 같은 신호가 두 번 오면 한 번만 보낸다.
  - 순서 전체는 `robot_access_amr_omx_2026-10-27.md` 2.2에 있다.
- OMX 명령(`app/clients/omx.py`)은 문장 형식이다.
  - 적재는 이미지(YOLO)로 한다(10-27 사용자).
  - **10-27 바꿈**: 명령은 색깔별 개수 `{"command": {"blue": n, "green": n}}`. 대응표는 약품 → blue, 비품 → green(`services/omx_items.py`). 팀원 `vision` 서버는 아직 문장을 읽어서 바꿔야 한다.
  - 정할 것: 묶음에 물품이 여럿일 때 OMX가 한 명령으로 집는지(4장 결정 3)
  - 순서와 두 완료 신호를 구분하는 법(OMX `GET /status`의 `pinky`)은 `robot_access_amr_omx_2026-10-27.md` 2.2에 있다.

### 3.8 예전 API를 남겨 둘 때의 위험
- `POST /robot/deliveries/claim`이 그대로 살아 있다.
  - 누가 부르면 같은 배송을 FMS 흐름과 예전 흐름이 둘 다 바꾼다.
- 제안: 설정 하나(예: `DELIVERY_DISPATCH=fms`)를 켜면 claim은 늘 204를 주고, Pinky `/status`도 묻지 않게 한다.
  - 코드는 남기되 실제로는 쓰이지 않게 막는 것이다.

### 3.9 화면
- 진행 칩 `신청 — 출발 — 도착 — 받음`은 2장 표대로 그대로 쓸 수 있다.
- 병원 지도: robot-status로 로봇 위치·배터리·오염도·`place`를 표시한다. 1초 값은 SSE로 화면에 보내거나 화면이 몇 초마다 묻는다.
- 환경 설정 → 로봇 탭: FMS 번호 칸, 온라인 여부
- 프론트 `types.ts`, `errorMessages.ts`(새 오류 코드)

### 3.10 5분 수령 마감
- FMS 로봇은 병실에서 한 바퀴 돈 뒤 **1~5초 쉬고 떠난다.**
- 그래서 "5분 안에 안 받으면 `not_received` 실패"는 더 이상 로봇이 기다리는 시간이 아니다. 마감을 없앨지, 간호사 화면 안내용으로만 남길지 정한다(4장 결정 4).

### 3.11 FMS `/rooms`·`/map` (문서만 — 10-27 사용자 "아직 하지 마")
- FMS `GET /api/v1/rooms` → `{rooms: [{room, name, contamination, orderable}]}`(실측: 101호 "4인실 왼쪽" 오염도 50 …). `GET /api/v1/map` → 벽·노드 좌표·엣지·`room_codes`.
- 지금 EMR 장소·지도는 `scripts/import_pinky_dests.py`가 **Pinky :8080에서 직접** 가져온다. "EMR은 FMS·OMX만 연결" 원칙에 맞추려면 나중에 이 둘로 바꾼다.
  - 신청 목적지를 `orderable`로 거르면 약제실 같은 방의 400을 미리 막을 수 있다.
- 지금은 3.5처럼 장소 `robot_dest`를 방 번호로 손으로 고친다.

## 4. EMR 쪽에서 정할 것 (사용자)

1. **FMS로 보낸 뒤 간호사 취소**
   - FMS는 주문이 `queued`일 때만 `DELETE /orders/{id}`를 받는다(`assigned`부터 409 `order_locked`).
   - (가) 새 배송 상태 `ordered`(마이그레이션, 화면 칩 추가)
   - (나) reserved에 '보냄' 표시만 두고, 취소할 때 DELETE를 시도해서 하나라도 409면 취소를 거절 — **권함, 상태 수가 늘지 않음**
2. **한 신청의 물품이 여러 묶음·로봇으로 나뉠 때**
   - 시뮬레이터에서 확인한 대로, 신청 하나의 물품이 다른 로봇에 실릴 수 있다. EMR 배송의 로봇 칸은 하나뿐이다.
   - (가) 처음 배차된 로봇을 적고, 모두 delivered면 arrived — **권함**
   - (나) 신청 1건 수량 합계 ≤ 3으로 제한(보관 브랜치에 백엔드 있음). 그래도 FMS가 나눌 수 있어 완전한 보장은 아님
3. **OMX 적재(이미지)에 넘길 것**
   - ~~EMR 비품을 어느 색으로 보낼지~~ → **10-27 결정**: 약품 → blue, 비품 → green, 명령 `{"blue": n, "green": n}`
   - 묶음에 물품이 여럿일 때: 물품마다 `/command`를 보낼지, OMX를 바꿀지, FMS 묶음을 1개로 제한할지
4. **5분 수령 마감**을 없앨지, 화면 안내로만 둘지
5. **보관 브랜치 `fms-order-2026-10-26`**를 이 작업으로 대신하고 합치지 않을지

## 5. 팀원(FMS)에게 요청할 것

점검 문서(`docs/fms_api_v1_review_2026-10-27.md`) 가운데 EMR 동작에 직접 영향이 있는 것만 골랐다.

| # | 요청 | 이유 |
|---|---|---|
| 1 | ~~`ready`·`loaded`를 다시 보내면 200(멱등)~~ → **요청 안 함**(10-27 사용자: 현상 유지, EMR이 409를 받아들임) | 지금은 두 번째가 409 `bad_batch_state`이고 본문에 상태가 없다. EMR이 응답을 잃고 다시 보내면 오류로 보인다 |
| 2 | 주문이 들어가는 모든 이벤트에 `request_id` (급하지 않음 — `POST /orders` 응답의 `order_id`로 대신, 1.2) | 지금은 `order_created`에만 있다. EMR이 `order_id` ↔ `request_id` 표를 따로 들고 있어야 한다 |
| 3 | 이벤트를 robot-status와 따로 바로 보내기 | 이벤트가 1~2초 늦고, 실패한 한 건이 뒤 이벤트를 최대 7초 막는다 |
| 4 | 실패·시간 초과 흐름 (시험에서는 무시 — 10-27 사용자) | `order_failed`·`robot_error`가 시뮬레이터에 없다. `ready`·`loaded`가 안 오면 핑키가 계속 기다린다 |
| 5 | 같은 `request_id`에 다른 방·물품이면 409 | 지금은 200으로 처음 주문을 돌려줘서, ID를 잘못 다시 쓰면 주문이 소리 없이 사라진다 |
| 6 | 이벤트 필드 모양 통일 | `robot_departed.from`(문자열)과 `to`(객체), `robot_arrived`의 평평한 `node`·`room`, `robot_called`에 `name` 없음 |
| 7 | 인증, `/api/control` 막기 (인증은 **없이 진행** — 10-27 사용자. `/api/control`은 FMS 쪽 일) | 같은 망 누구나 FMS를 다시 시작하거나 `control_url`을 바꿔 이벤트를 다른 곳으로 보낼 수 있다 |
| 8 | FMS가 다시 시작됐음을 알리기 (예: `/state`에 시작 시각이나 세대 번호) | 다시 시작하면 주문·`request_id` 표가 비워진다. EMR이 이를 알아야 진행 중인 주문을 다시 보낼지 실패 처리할지 정할 수 있다 |
| 9 | 정할 값 | FMS 서버 주소, `--control-url http://192.168.129.135:8000`(EMR), 로봇 2·3번 핑키 |

## 6. 구현 순서 제안 (결정 뒤)

1. **계약 문서**: `docs/api_contract_delivery_2026-10-20.md`에 FMS v1 연동 장을 쓴다. 루트 CLAUDE.md 규칙상 API 계약은 문서부터 고친다.
2. **장소·로봇 데이터**: 3.4·3.5
3. **받기 엔드포인트 2개 + 이벤트 저장**: 시뮬레이터 `--control-url`로 먼저 붙여 본다. 이 단계는 상태를 바꾸지 않고 저장만 한다.
4. **보내기 주기 작업**
5. **`order_delivered` → arrived**, 실패·취소
6. **OMX 적재·탑재 명령과 완료 신호 → `ready`·`loaded`**
7. **화면**: 지도의 로봇 위치, 로봇 탭
8. **예전 claim 막는 설정**
