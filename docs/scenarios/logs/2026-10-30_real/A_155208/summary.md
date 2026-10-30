# 실물 시험 로그 — 장면 A 2차 (155208)

- 일시: 2026-10-30 15:52:18 ~ 16:03:05 (KST)
- 환경: **실물** — 실제 Pinky 3대(FMS 도커 `--real-table --no-auto-omx`) + 실제 OMX(10.42.0.147, `FMS_OMX_ENABLED=1`), EMR 간호사 N003
- 결과: NO 135 수령, NO 136 수령, NO 137 수령
- EMR api 경고·오류: 0줄 (`emr_api.log`)

## 이번 시험에서 확인한 것

- **끝까지 성공**: 간호사 화면 '즉시' 신청(병동 3곳) → FMS 묶음 b-1(2번 로봇) → 실제 OMX 집기(`blue:1, green:1` 고정, `OMX_COMMAND_FORMAT=fixed`) → FMS `ready` → 약제실 정밀 주차(`robot_at_pharmacy`) → OMX 내려놓기 → `loaded` → 101·104·103호 → 화면 '받았습니다' 3건. EMR api 경고·오류 0.
- **OMX 안전 기능 대기 2분 18초** (15:52:27 ~ 15:54:45): OMX `/safety`가 `waiting for the first person_exist`(사람 감지 신호 0개)라 두 팔이 집기 자세(`HIGH`)에서 멈춤. 사람 감지 신호가 들어온 뒤 이어서 집음. 그 뒤로도 `person` ↔ `clear`가 여러 번 바뀜(들고 기다리는 동안이라 진행에는 영향 없음).
- **2번 로봇 왼쪽 협로 `L102`에서 `rotate_err`** (16:00:27, 103호로 가는 길, 이유 `why` 없음): FMS가 그 자리를 잡고 멈춤 + EMR에 `robot_error`(EMR은 로그만). 사용자 확인 뒤 FMS `POST /api/control {"clear_fault": "R2"}`(16:02:0x) → 다시 계획해 103호 도착(16:02:58). 그래서 NO 136 신청→도착이 634초.
- 병실 순서는 FMS가 정함: 101호 → 104호 → 103호.
- 1차(`../A_151346/`)는 `blue:3` 집기 실패(파란 거즈 1개뿐) → 사용자 결정으로 OMX 명령을 `blue:1, green:1` 고정으로 바꿈.

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 135 | 101호 | A 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 15:52:24 | 15:55:22 | 15:56:59 | 15:58:39 | 15:58:45 | 375 |
| 136 | 103호 | B 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 15:52:24 | 15:55:22 | 15:56:59 | 16:02:58 | 16:03:04 | 634 |
| 137 | 104호 | C 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 15:52:24 | 15:55:22 | 15:56:59 | 15:59:51 | 15:59:58 | 447 |

## 진행 흐름 (자막)

```
15:52:18 장면 A (실물) — FMS 잠깐 멈춤: 주문 3건을 한 묶음으로 모은다 | 신청: 101호 A 약품 1개 · 103호 B 약품 1개 · 104호 C 약품 1개
15:52:25 화면 신청 생김 NO [135, 136, 137]
15:52:26 FMS 대기 주문 3건 → 재개
15:52:26 장면 A (실물 Pinky + 실물 OMX)  0:00 | NO 135 101호 예약 · NO 136 103호 예약 · NO 137 104호 예약 | 로봇: 1번 대기 아래 복도 · 2번 대기 위 복도 · 3번 대기 아래 복도 | OMX idle/- ⚠사람 감지로 멈춤
15:52:27 장면 A (실물 Pinky + 실물 OMX)  0:01 | NO 135 101호 예약 · NO 136 103호 예약 · NO 137 104호 예약 | 로봇: 1번 대기 아래 복도 · 2번 배차됨 위 복도(b-1) · 3번 대기 아래 복도 | OMX running/running
15:54:44 장면 A (실물 Pinky + 실물 OMX)  2:17 | NO 135 101호 예약 · NO 136 103호 예약 · NO 137 104호 예약 | 로봇: 1번 대기 아래 복도 · 2번 배차됨 위 복도(b-1) · 3번 대기 아래 복도 | OMX running/running ⚠사람 감지로 멈춤
15:54:45 장면 A (실물 Pinky + 실물 OMX)  2:18 | NO 135 101호 예약 · NO 136 103호 예약 · NO 137 104호 예약 | 로봇: 1번 대기 아래 복도 · 2번 배차됨 위 복도(b-1) · 3번 대기 아래 복도 | OMX running/running
15:55:20 장면 A (실물 Pinky + 실물 OMX)  2:53 | NO 135 101호 예약 · NO 136 103호 예약 · NO 137 104호 예약 | 로봇: 1번 대기 아래 복도 · 2번 배차됨 위 복도(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 grabbing
15:55:22 장면 A (실물 Pinky + 실물 OMX)  2:55 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 이동 위 복도(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 grabbing
15:55:32 장면 A (실물 Pinky + 실물 OMX)  3:06 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 이동 위 복도(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding
15:56:01 장면 A (실물 Pinky + 실물 OMX)  3:35 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 이동 위 복도(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding ⚠사람 감지로 멈춤
15:56:07 장면 A (실물 Pinky + 실물 OMX)  3:40 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 이동 위 복도(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding
15:56:13 장면 A (실물 Pinky + 실물 OMX)  3:46 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 정밀 주차 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding ⚠사람 감지로 멈춤
15:56:40 장면 A (실물 Pinky + 실물 OMX)  4:13 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 정밀 주차 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding
15:56:52 장면 A (실물 Pinky + 실물 OMX)  4:25 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 정밀 주차 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding ⚠사람 감지로 멈춤
15:56:55 장면 A (실물 Pinky + 실물 OMX)  4:29 | NO 135 101호 준비 · NO 136 103호 준비 · NO 137 104호 준비 | 로봇: 1번 대기 아래 복도 · 2번 정밀 주차 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding
15:57:00 장면 A (실물 Pinky + 실물 OMX)  4:33 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 적재 대기 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 holding
15:57:02 장면 A (실물 Pinky + 실물 OMX)  4:35 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 적재 대기 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 releasing
15:57:04 장면 A (실물 Pinky + 실물 OMX)  4:37 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 적재 대기 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 returning
15:57:12 장면 A (실물 Pinky + 실물 OMX)  4:45 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 적재 대기 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:57:13 장면 A (실물 Pinky + 실물 OMX)  4:46 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 적재 대기 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed ⚠사람 감지로 멈춤
15:57:14 장면 A (실물 Pinky + 실물 OMX)  4:47 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed ⚠사람 감지로 멈춤
15:57:17 장면 A (실물 Pinky + 실물 OMX)  4:50 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:57:26 장면 A (실물 Pinky + 실물 OMX)  4:59 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed ⚠사람 감지로 멈춤
15:57:27 장면 A (실물 Pinky + 실물 OMX)  5:00 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 약제실(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:23 장면 A (실물 Pinky + 실물 OMX)  5:56 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 병실 도착 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:38 장면 A (실물 Pinky + 실물 OMX)  6:11 | NO 135 101호 출발 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 잠시 멈춤 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:39 장면 A (실물 Pinky + 실물 OMX)  6:12 | NO 135 101호 도착 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 잠시 멈춤 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:42 장면 A (실물 Pinky + 실물 OMX)  6:15 | NO 135 101호 도착 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:45 장면 A (실물 Pinky + 실물 OMX)  6:18 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:58:56 장면 A (실물 Pinky + 실물 OMX)  6:29 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed ⚠사람 감지로 멈춤
15:58:57 장면 A (실물 Pinky + 실물 OMX)  6:30 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 이동 101호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:59:35 장면 A (실물 Pinky + 실물 OMX)  7:08 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 출발 | 로봇: 1번 대기 아래 복도 · 2번 병실 도착 104호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:59:52 장면 A (실물 Pinky + 실물 OMX)  7:25 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 도착 | 로봇: 1번 대기 아래 복도 · 2번 잠시 멈춤 104호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:59:56 장면 A (실물 Pinky + 실물 OMX)  7:29 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 도착 | 로봇: 1번 대기 아래 복도 · 2번 이동 104호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
15:59:59 장면 A (실물 Pinky + 실물 OMX)  7:32 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 이동 104호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:00:28 장면 A (실물 Pinky + 실물 OMX)  8:01 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 멈춤 왼쪽 협로(b-1) ⚠rotate_err · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:02:05 장면 A (실물 Pinky + 실물 OMX)  9:38 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 이동 왼쪽 협로(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:02:41 장면 A (실물 Pinky + 실물 OMX)  10:15 | NO 135 101호 수령 · NO 136 103호 출발 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 병실 도착 103호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:02:58 장면 A (실물 Pinky + 실물 OMX)  10:31 | NO 135 101호 수령 · NO 136 103호 도착 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 잠시 멈춤 103호(b-1) · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:03:02 장면 A (실물 Pinky + 실물 OMX)  10:35 | NO 135 101호 수령 · NO 136 103호 도착 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 이동 103호 · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:03:05 장면 A (실물 Pinky + 실물 OMX)  10:38 | NO 135 101호 수령 · NO 136 103호 수령 · NO 137 104호 수령 | 로봇: 1번 대기 아래 복도 · 2번 이동 103호 · 3번 대기 아래 복도 | OMX completed/done 내려놓기 completed
16:03:05 장면 A (실물) 끝 — NO 135 수령 · NO 136 수령 · NO 137 수령
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|
| 5 | 15:52:26 | order_created | `{"order_id": "o-1", "request_id": "emr-d135-s1-1", "room": "101호", "item": "A 약품"}` |
| 6 | 15:52:26 | order_created | `{"order_id": "o-2", "request_id": "emr-d136-s2-1", "room": "103호", "item": "B 약품"}` |
| 7 | 15:52:26 | order_created | `{"order_id": "o-3", "request_id": "emr-d137-s3-1", "room": "104호", "item": "C 약품"}` |
| 8 | 15:52:26 | batch_assigned | `{"batch_id": "b-1", "robot": 2, "name": "pinky_ee3a", "orders": [{"order_id": "o-1", "room": "101호", "item": "A 약품"}, {"order_id": "o-3", "room": "104호", "item": "C 약품"}, {"order_id": "o-2", "room": "103호", "item": "B 약품"}], "count": 3, "rooms": ["101호", "104호", "103호"]}` |
| 9 | 15:55:21 | robot_called | `{"batch_id": "b-1", "robot": 2, "eta_s": 50}` |
| 10 | 15:55:21 | robot_departed | `{"robot": 2, "task": "delivery", "from": "T1_20", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 11 | 15:56:12 | robot_arrived | `{"robot": 2, "node": "PHARMACY", "room": "약제실"}` |
| 12 | 15:56:59 | robot_at_pharmacy | `{"batch_id": "b-1", "robot": 2}` |
| 13 | 15:57:14 | batch_departed | `{"batch_id": "b-1", "robot": 2, "rooms": ["101호", "104호", "103호"]}` |
| 14 | 15:57:14 | robot_departed | `{"robot": 2, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM4_L", "room": "101호"}}` |
| 15 | 15:58:22 | robot_arrived | `{"robot": 2, "node": "ROOM4_L", "room": "101호"}` |
| 16 | 15:58:38 | order_delivered | `{"order_id": "o-1", "room": "101호", "robot": 2, "batch_id": "b-1"}` |
| 17 | 15:58:42 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM4_L", "to": {"node": "ROOM1_CUL", "room": "104호"}}` |
| 18 | 15:59:34 | robot_arrived | `{"robot": 2, "node": "ROOM1_CUL", "room": "104호"}` |
| 19 | 15:59:51 | order_delivered | `{"order_id": "o-3", "room": "104호", "robot": 2, "batch_id": "b-1"}` |
| 20 | 15:59:55 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM1_CUL", "to": {"node": "ROOM1_LU", "room": "103호"}}` |
| 21 | 16:00:27 | robot_error | `{"robot": 2, "name": "pinky_ee3a", "code": "rotate_err", "why": null, "node": "L102", "edge": null, "task": "delivery", "batch_id": "b-1"}` |
| 22 | 16:02:41 | robot_arrived | `{"robot": 2, "node": "ROOM1_LU", "room": "103호"}` |
| 23 | 16:02:58 | order_delivered | `{"order_id": "o-2", "room": "103호", "robot": 2, "batch_id": "b-1"}` |
| 24 | 16:02:58 | batch_completed | `{"batch_id": "b-1", "robot": 2}` |

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)
