# 시뮬레이션 시험 로그 — 장면 A 2차 (85~87)

- 일시: 2026-10-30 12:49:52 ~ 12:54:44 (KST)
- 환경: FMS 시뮬레이터(가상 Pinky 3대, 도커 `fms-fms-1`) + 가상 OMX(`FMS_OMX_ENABLED=0`), EMR 간호사 N003
- 결과: NO 85 수령, NO 86 수령, NO 87 수령
- EMR api 경고·오류: 0줄 (`emr_api.log`)

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 85 | 101호 | A 약품 ×1 | 1건 | b-2 | 2 → 배송로봇 2호 | 12:49:56 | 12:50:20 | 12:51:24 | 12:52:34 | 12:52:41 | 158 |
| 86 | 103호 | B 약품 ×1 | 1건 | b-2 | 2 → 배송로봇 2호 | 12:49:56 | 12:50:20 | 12:51:24 | 12:54:36 | 12:54:43 | 280 |
| 87 | 104호 | C 약품 ×1 | 1건 | b-2 | 2 → 배송로봇 2호 | 12:49:56 | 12:50:20 | 12:51:24 | 12:53:33 | 12:53:39 | 217 |

## 진행 흐름 (자막)

```
12:49:52 장면 A — 시작: 가상 로봇 3대 대기 (FMS 시뮬레이터 + 가상 OMX)
12:49:56 ① 간호사가 여러 병동 한 번에 신청 → EMR 신청 3건 (NO 85, 86, 87) | 101호 A 약품 1개 · 103호 B 약품 1개 · 104호 C 약품 1개
12:49:59 ② 보낼 시간 → EMR이 FMS에 주문 3건 (물품 1개 = 주문 1건) | FMS는 잠시 멈춰 두었다가 다시 켠다 → 묶음으로 배차
12:50:03 ③ FMS 배차 중   [묶음 대기] | NO 85 101호 예약 · NO 86 103호 예약 · NO 87 104호 예약
12:50:04 ③ FMS 배차 중   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 예약 · NO 86 103호 예약 · NO 87 104호 예약
12:50:21 ③ 준비: 로봇을 약제실로 부름 · 가상 OMX 적재   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 준비 · NO 86 103호 준비 · NO 87 104호 준비
12:51:24 ③ 정밀 주차 끝 → 출발 (병실로)   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 출발 · NO 86 103호 출발 · NO 87 104호 출발
12:52:35 ④ 병실 도착 → 간호사 '받았습니다'   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 도착 · NO 86 103호 출발 · NO 87 104호 출발
12:52:42 ③ 정밀 주차 끝 → 출발 (병실로)   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 수령 · NO 86 103호 출발 · NO 87 104호 출발
12:53:33 ④ 병실 도착 → 간호사 '받았습니다'   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 수령 · NO 86 103호 출발 · NO 87 104호 도착
12:53:40 ③ 정밀 주차 끝 → 출발 (병실로)   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 수령 · NO 86 103호 출발 · NO 87 104호 수령
12:54:37 ④ 병실 도착 → 간호사 '받았습니다'   [묶음 b-2: 101호, 103호, 104호] | NO 85 101호 수령 · NO 86 103호 도착 · NO 87 104호 수령
12:54:44 ⑤ 모두 수령 — 장면 A 끝 | NO 85 101호 수령 · NO 86 103호 수령 · NO 87 104호 수령
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|
| 24 | 12:49:57 | order_created | `{"order_id": "o-4", "request_id": "emr-d85-s1-1", "room": "101호", "item": "A 약품"}` |
| 25 | 12:49:57 | order_created | `{"order_id": "o-5", "request_id": "emr-d86-s2-1", "room": "103호", "item": "B 약품"}` |
| 26 | 12:49:57 | order_created | `{"order_id": "o-6", "request_id": "emr-d87-s3-1", "room": "104호", "item": "C 약품"}` |
| 27 | 12:50:04 | batch_assigned | `{"batch_id": "b-2", "robot": 2, "name": "pinky_ee3a", "orders": [{"order_id": "o-4", "room": "101호", "item": "A 약품"}, {"order_id": "o-6", "room": "104호", "item": "C 약품"}, {"order_id": "o-5", "room": "103호", "item": "B 약품"}], "count": 3, "rooms": ["101호", "104호", "103호"]}` |
| 28 | 12:50:19 | robot_called | `{"batch_id": "b-2", "robot": 2, "eta_s": 50}` |
| 29 | 12:50:19 | robot_departed | `{"robot": 2, "task": "delivery", "from": "T1_20", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 30 | 12:51:03 | robot_arrived | `{"robot": 2, "node": "PHARMACY", "room": "약제실"}` |
| 31 | 12:51:23 | robot_at_pharmacy | `{"batch_id": "b-2", "robot": 2}` |
| 32 | 12:51:33 | batch_departed | `{"batch_id": "b-2", "robot": 2, "rooms": ["101호", "104호", "103호"]}` |
| 33 | 12:51:33 | robot_departed | `{"robot": 2, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM4_L", "room": "101호"}}` |
| 34 | 12:52:26 | robot_arrived | `{"robot": 2, "node": "ROOM4_L", "room": "101호"}` |
| 35 | 12:52:34 | order_delivered | `{"order_id": "o-4", "room": "101호", "robot": 2, "batch_id": "b-2"}` |
| 36 | 12:52:36 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM4_L", "to": {"node": "ROOM1_CUL", "room": "104호"}}` |
| 37 | 12:53:24 | robot_arrived | `{"robot": 2, "node": "ROOM1_CUL", "room": "104호"}` |
| 38 | 12:53:32 | order_delivered | `{"order_id": "o-6", "room": "104호", "robot": 2, "batch_id": "b-2"}` |
| 39 | 12:53:37 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM1_CUL", "to": {"node": "ROOM1_LU", "room": "103호"}}` |
| 40 | 12:54:27 | robot_arrived | `{"robot": 2, "node": "ROOM1_LU", "room": "103호"}` |
| 41 | 12:54:35 | order_delivered | `{"order_id": "o-5", "room": "103호", "robot": 2, "batch_id": "b-2"}` |
| 42 | 12:54:35 | batch_completed | `{"batch_id": "b-2", "robot": 2}` |

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)
