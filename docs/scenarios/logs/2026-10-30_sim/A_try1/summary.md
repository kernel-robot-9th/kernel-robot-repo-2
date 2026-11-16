# 시뮬레이션 시험 로그 — 장면 A 1차 (82~84)

- 일시: 2026-10-30 12:41:57 ~ 12:46:36 (KST)
- 환경: FMS 시뮬레이터(가상 Pinky 3대, 도커 `fms-fms-1`) + 가상 OMX(`FMS_OMX_ENABLED=0`), EMR 간호사 N003
- 결과: NO 82 수령, NO 83 수령, NO 84 수령
- EMR api 경고·오류: 0줄 (`emr_api.log`)

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 82 | 101호 | A 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 12:42:01 | 12:42:24 | 12:43:20 | 12:44:30 | 12:44:37 | 149 |
| 83 | 103호 | B 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 12:42:01 | 12:42:24 | 12:43:20 | 12:46:29 | 12:46:35 | 268 |
| 84 | 104호 | C 약품 ×1 | 1건 | b-1 | 2 → 배송로봇 2호 | 12:42:01 | 12:42:24 | 12:43:20 | 12:45:29 | 12:45:35 | 208 |

## 진행 흐름 (자막)

```
12:41:57 장면 A 1차 — 시작 (자막 기록은 2차 녹화가 같은 폴더를 써서 없어짐 — 단계 시각은 아래 배송 기록 표)
12:42:01 ① 여러 병동 신청 → EMR 신청 3건 (NO 82, 83, 84) | 101호 A 약품 1개 · 103호 B 약품 1개 · 104호 C 약품 1개
12:42:09 ③ FMS 묶음 b-1: 101호, 103호, 104호 → FMS 로봇 2
12:46:36 ⑤ 모두 수령 — 장면 A 1차 끝 (지도 화면은 숨은 탭이라 녹화에서 멈춰 보임 → 2차로 다시 녹화)
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|
| 1 | 12:42:01 | order_created | `{"order_id": "o-1", "request_id": "emr-d82-s1-1", "room": "101호", "item": "A 약품"}` |
| 2 | 12:42:01 | order_created | `{"order_id": "o-2", "request_id": "emr-d83-s2-1", "room": "103호", "item": "B 약품"}` |
| 3 | 12:42:01 | order_created | `{"order_id": "o-3", "request_id": "emr-d84-s3-1", "room": "104호", "item": "C 약품"}` |
| 4 | 12:42:08 | batch_assigned | `{"batch_id": "b-1", "robot": 2, "name": "pinky_ee3a", "orders": [{"order_id": "o-1", "room": "101호", "item": "A 약품"}, {"order_id": "o-3", "room": "104호", "item": "C 약품"}, {"order_id": "o-2", "room": "103호", "item": "B 약품"}], "count": 3, "rooms": ["101호", "104호", "103호"]}` |
| 5 | 12:42:23 | robot_called | `{"batch_id": "b-1", "robot": 2, "eta_s": 50}` |
| 6 | 12:42:23 | robot_departed | `{"robot": 2, "task": "delivery", "from": "T1_20", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 7 | 12:43:00 | robot_arrived | `{"robot": 2, "node": "PHARMACY", "room": "약제실"}` |
| 8 | 12:43:20 | robot_at_pharmacy | `{"batch_id": "b-1", "robot": 2}` |
| 9 | 12:43:30 | batch_departed | `{"batch_id": "b-1", "robot": 2, "rooms": ["101호", "104호", "103호"]}` |
| 10 | 12:43:30 | robot_departed | `{"robot": 2, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM4_L", "room": "101호"}}` |
| 11 | 12:44:22 | robot_arrived | `{"robot": 2, "node": "ROOM4_L", "room": "101호"}` |
| 12 | 12:44:30 | order_delivered | `{"order_id": "o-1", "room": "101호", "robot": 2, "batch_id": "b-1"}` |
| 13 | 12:44:32 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM4_L", "to": {"node": "ROOM1_CUL", "room": "104호"}}` |
| 14 | 12:45:20 | robot_arrived | `{"robot": 2, "node": "ROOM1_CUL", "room": "104호"}` |
| 15 | 12:45:28 | order_delivered | `{"order_id": "o-3", "room": "104호", "robot": 2, "batch_id": "b-1"}` |
| 16 | 12:45:29 | robot_departed | `{"robot": 2, "task": "delivery", "from": "ROOM1_CUL", "to": {"node": "ROOM1_LU", "room": "103호"}}` |
| 17 | 12:46:20 | robot_arrived | `{"robot": 2, "node": "ROOM1_LU", "room": "103호"}` |
| 18 | 12:46:28 | order_delivered | `{"order_id": "o-2", "room": "103호", "robot": 2, "batch_id": "b-1"}` |
| 19 | 12:46:28 | batch_completed | `{"batch_id": "b-1", "robot": 2}` |

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)
