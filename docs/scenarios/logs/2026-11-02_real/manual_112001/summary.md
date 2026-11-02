# 실물 시험 로그 — manual_112001 (11-02 사용자 직접 신청)

- 일시: 2026-11-02 11:20:20 ~ 11:41:50 (KST)
- 환경: 실물 Pinky 2대(1번 pinky_6364·3번 pinky_62f4, FMS --real-table --robots 2, 2번 pinky_ee3a 문제로 뺌) + 실물 OMX(10.42.0.147, fixed = blue 1·green 1), EMR 간호사 N001이 화면에서 직접 신청(기록만, 조작 없음)
- 결과: NO 354 수령, NO 355 수령, NO 356 수령, NO 357 수령, NO 358 수령
- EMR api 경고·오류: 10줄 (`emr_api.log`)

- 기록 방법: `watch_manual.py` — 1초마다 EMR 신청(DB 읽기)·FMS 로봇·OMX `/status`를 바뀔 때만 적음. 받기·오류 풀기·OMX 명령은 사람이 함

## 결과 — 성공 (신청 5건, 묶음 3개 모두 수령)

| 묶음 | 로봇 | 병실 | OMX | 비고 |
|---|---|---|---|---|
| b-1 | 1호 `pinky_6364` | 105호 → 103호 | `emr-b21` 성공 | 103호는 도착 뒤 2분 37초 만에 받음(로봇은 그 사이 POCKET으로 감) |
| b-2 | 3호 `pinky_62f4` | 105호 → 107호 | `emr-b22` 성공 | 3호 출발 거부 1번(아래 1) — 6분 지연 |
| b-3 | 1호 `pinky_6364` | 105호 | `emr-b23` 실패 → `emr-b23-r2` 성공 | 초록 못 찾음(아래 2), 사람이 재시도 |

## 찾은 점

1. **3호 출발 거부 `not_at_start`** (11:23:24): 주차 노드 B1_130에서 5.3 cm(로봇 `driving/api/drive_ctl.py` 허용 `AT_NODE_CM = 5.0`). 주차 뒤 AMCL 위치가 조금 밀린 것.
   - 움직이지 않는 `POST :8080/set_pose {"find": true}`로 다시 잡아 4.7 cm → 사용자 승인 뒤 `clear_fault`로 이어감(11:29).
   - **함정**: `--robots 2`로 띄우면 FMS 안 이름이 1번 = `R1`, 3번 = `R2`. 처음에 `{"clear_fault": "R3"}`를 보냈는데 맞는 로봇이 없어도 `{"ok": true}`라 아무것도 안 됨. 로봇 이름(`pinky_62f4`)으로 보내야 함.
   - 허용 5 cm는 정밀 주차·주차 뒤 흔들림에 비해 빡빡하다 — 팀원(driving)에게 알릴 거리.
2. **OMX 집기 실패 `green #1 not found`** (11:33:13, `emr-b23`): 왼팔 카메라에 초록 거즈가 없었음(`/detection` left `null`). 10-30 장면 A 5·6차와 같은 원인.
   - 사용자 "재시도" → 묶음을 `pick`으로 되돌림(DB) → **새 request_id `emr-b23-r2`**로 다시 보내 성공(11:39:45).
   - EMR 고침(이번 작업, `app/services/fms_omx.py` `_pick_request_id`): 다시 보낼 때 `emr-b{id}-r2`, `-r3` … — 같은 번호면 OMX `/status`의 지난 `failed`를 읽고 바로 다시 실패했다(10-30). 시험 `test_retry_after_failure_uses_new_request_id`, 전체 249개 통과.
   - EMR에 재시도 버튼은 아직 없다 — 지금은 사람이 DB에서 `fms_batches.step = 'pick'`으로 되돌린다.
3. **OMX 안전 정지(사람 감지)가 자주 켜졌다 꺼짐**: 내려놓기 중(`releasing`)에도 몇 초씩 멈췄다가 이어감. 배송 실패로 이어지진 않음.
4. **EMR 로그의 OMX 개수**: `fixed`인데 `fms_omx_pick_sent`에 신청에서 센 값(`blue 2, green 0` 등)이 찍힘 — OMX에 실제로 간 것은 늘 `blue:1, green:1`(OMX `/status` `command`). 기록을 읽을 때 헷갈림.
5. **준비 전 일**(같은 날 아침): Pinky 3대 재부팅 → `set_pose find`로 위치 확인. 11:10 로봇 망 전체가 끊겼다가 1·3번만 돌아옴(다시 재부팅 → 다시 위치 확인 → FMS가 주차로 움직임), 2번 `pinky_ee3a`는 돌아오지 않아 FMS에서 뺌(`~/fms_override/robots_2units.yaml`). OMX PC는 11:17쯤 같은 주소로 돌아옴. 신청 기록은 11-02 아침에 지움(백업 `~/emr_backups/emr_before_clear_20261102_105616.sql.gz`).

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 354 | 103호 | C 약품 ×1 | 1건 | b-1 | 1 → 배송로봇 1호 | 11:19:00 | 11:19:41 | 11:20:32 | 11:24:02 | 11:26:40 | 302 |
| 355 | 105호 | C 약품 ×1 | 1건 | b-1 | 1 → 배송로봇 1호 | 11:19:00 | 11:19:41 | 11:20:32 | 11:22:11 | 11:22:13 | 191 |
| 356 | 105호 | 이불 ×1, 매트리스 패드 ×1 | 2건 | b-2 | 3 → 배송로봇 3호 | 11:22:27 | 11:23:15 | 11:29:39 | 11:30:59 | 11:31:08 | 512 |
| 357 | 107호 | B 약품 ×1 | 1건 | b-2 | 3 → 배송로봇 3호 | 11:22:27 | 11:23:15 | 11:29:39 | 11:33:06 | 11:33:15 | 639 |
| 358 | 105호 | A 약품 ×1, C 약품 ×1 | 2건 | b-3 | 1 → 배송로봇 1호 | 11:31:57 | 11:39:08 | 11:40:12 | 11:41:30 | 11:41:49 | 573 |

## 진행 흐름 (자막)

```
11:20:20 기록 시작 — 사용자가 화면에서 직접 신청, 기존 신청 0건은 제외
11:20:21 새 신청 NO 354 N001 103호 — C 약품 1개
11:20:21 NO 354 준비 · 로봇 배송로봇 1호
11:20:21 새 신청 NO 355 N001 105호 — C 약품 1개
11:20:21 NO 355 준비 · 로봇 배송로봇 1호
11:20:21 로봇 1(pinky_6364) docking · 약제실 · 묶음 b-1
11:20:21 로봇 3(pinky_62f4) idle · 아래 복도
11:20:21 OMX emr-b21 completed 전달 sent pinky holding 오류 None · 안전 통과
11:20:33 NO 354 출발 · 로봇 배송로봇 1호
11:20:33 NO 355 출발 · 로봇 배송로봇 1호
11:20:33 로봇 1(pinky_6364) loading · 약제실 · 묶음 b-1
11:20:34 OMX emr-b21 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:20:38 OMX emr-b21 completed 전달 sent pinky releasing 오류 None · 안전 멈춤 person
11:20:40 OMX emr-b21 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:20:45 OMX emr-b21 completed 전달 sent pinky releasing 오류 None · 안전 멈춤 person
11:21:02 OMX emr-b21 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:21:03 OMX emr-b21 completed 전달 sent pinky returning 오류 None · 안전 통과
11:21:06 OMX emr-b21 completed 전달 sent pinky completed 오류 None · 안전 통과
11:21:08 로봇 1(pinky_6364) moving · 약제실 · 묶음 b-1
11:21:28 OMX emr-b21 completed 전달 sent pinky completed 오류 None · 안전 멈춤 person
11:21:31 OMX emr-b21 completed 전달 sent pinky completed 오류 None · 안전 통과
11:21:38 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-1
11:21:54 로봇 1(pinky_6364) spinning · 105호 · 묶음 b-1
11:22:10 로봇 1(pinky_6364) pausing · 105호 · 묶음 b-1
11:22:11 NO 355 도착 · 로봇 배송로봇 1호
11:22:14 NO 355 수령 · 로봇 배송로봇 1호
11:22:16 로봇 1(pinky_6364) moving · 105호 · 묶음 b-1
11:22:28 새 신청 NO 356 N001 105호 — 이불 1개, 매트리스 패드 1개
11:22:28 NO 356 예약
11:22:28 새 신청 NO 357 N001 107호 — B 약품 1개
11:22:28 NO 357 예약
11:22:31 로봇 3(pinky_62f4) reserved · 아래 복도 · 묶음 b-2
11:22:33 OMX emr-b22 running 전달 pending pinky None 오류 None · 안전 통과
11:22:36 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-1
11:22:52 OMX emr-b22 running 전달 pending pinky None 오류 None · 안전 멈춤 person
11:22:54 OMX emr-b22 running 전달 pending pinky None 오류 None · 안전 통과
11:23:14 OMX emr-b22 completed 전달 sent pinky grabbing 오류 None · 안전 통과
11:23:16 NO 356 준비 · 로봇 배송로봇 3호
11:23:16 NO 357 준비 · 로봇 배송로봇 3호
11:23:16 로봇 1(pinky_6364) moving · 왼쪽 협로 · 묶음 b-1
11:23:16 로봇 3(pinky_62f4) moving · 아래 복도 · 묶음 b-2
11:23:24 로봇 3(pinky_62f4) error · 아래 복도 · 묶음 b-2 · ⚠ 오류 not_at_start: B1_130 에서 5.3 cm
11:23:27 OMX emr-b22 completed 전달 sent pinky holding 오류 None · 안전 통과
11:23:33 로봇 1(pinky_6364) moving · 단일차선 협로 · 묶음 b-1
11:23:45 로봇 1(pinky_6364) spinning · 103호 · 묶음 b-1
11:24:03 NO 354 도착 · 로봇 배송로봇 1호
11:24:03 로봇 1(pinky_6364) pausing · 103호 · 묶음 b-1
11:24:07 로봇 1(pinky_6364) idle · 103호
11:24:08 로봇 1(pinky_6364) moving · 103호
11:24:33 로봇 1(pinky_6364) moving · 단일차선 협로
11:24:46 로봇 1(pinky_6364) moving · 왼쪽 협로
11:25:03 로봇 1(pinky_6364) moving · 위 복도
11:26:05 로봇 1(pinky_6364) decon · POCKET(대기)
11:26:11 로봇 1(pinky_6364) moving · POCKET(대기)
11:26:16 OMX emr-b22 completed 전달 sent pinky holding 오류 None · 안전 멈춤 person
11:26:18 OMX emr-b22 completed 전달 sent pinky holding 오류 None · 안전 통과
11:26:30 로봇 1(pinky_6364) moving · 위 복도
11:26:41 NO 354 수령 · 로봇 배송로봇 1호
11:26:47 로봇 1(pinky_6364) idle · 위 복도
11:27:56 로봇 3(pinky_62f4) moving · 아래 복도 · 묶음 b-2
11:28:19 로봇 3(pinky_62f4) moving · 오른쪽 협로 · 묶음 b-2
11:28:34 로봇 3(pinky_62f4) moving · 위 복도 · 묶음 b-2
11:29:10 OMX emr-b22 completed 전달 sent pinky holding 오류 None · 안전 멈춤 person
11:29:13 로봇 3(pinky_62f4) docking · 약제실 · 묶음 b-2
11:29:15 OMX emr-b22 completed 전달 sent pinky holding 오류 None · 안전 통과
11:29:39 NO 356 출발 · 로봇 배송로봇 3호
11:29:39 NO 357 출발 · 로봇 배송로봇 3호
11:29:39 로봇 3(pinky_62f4) loading · 약제실 · 묶음 b-2
11:29:41 OMX emr-b22 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:29:49 OMX emr-b22 completed 전달 sent pinky returning 오류 None · 안전 통과
11:29:54 OMX emr-b22 completed 전달 sent pinky completed 오류 None · 안전 통과
11:29:56 로봇 3(pinky_62f4) moving · 약제실 · 묶음 b-2
11:30:24 로봇 3(pinky_62f4) moving · 위 복도 · 묶음 b-2
11:30:43 로봇 3(pinky_62f4) spinning · 105호 · 묶음 b-2
11:31:00 NO 356 도착 · 로봇 배송로봇 3호
11:31:00 로봇 3(pinky_62f4) pausing · 105호 · 묶음 b-2
11:31:03 로봇 3(pinky_62f4) moving · 105호 · 묶음 b-2
11:31:09 NO 356 수령 · 로봇 배송로봇 3호
11:31:24 로봇 3(pinky_62f4) moving · 위 복도 · 묶음 b-2
11:31:58 새 신청 NO 358 N001 105호 — A 약품 1개, C 약품 1개
11:31:58 NO 358 예약
11:32:00 로봇 3(pinky_62f4) moving · 오른쪽 협로 · 묶음 b-2
11:32:12 로봇 3(pinky_62f4) moving · 아래 복도 · 묶음 b-2
11:32:22 OMX emr-b22 completed 전달 sent pinky completed 오류 None · 안전 멈춤 person
11:32:27 OMX emr-b22 completed 전달 sent pinky completed 오류 None · 안전 통과
11:32:43 로봇 1(pinky_6364) reserved · 위 복도 · 묶음 b-3
11:32:43 OMX emr-b23 running 전달 pending pinky None 오류 None · 안전 통과
11:32:52 로봇 3(pinky_62f4) spinning · 107호 · 묶음 b-2
11:33:07 NO 357 도착 · 로봇 배송로봇 3호
11:33:07 로봇 3(pinky_62f4) pausing · 107호 · 묶음 b-2
11:33:10 로봇 3(pinky_62f4) idle · 107호
11:33:11 로봇 3(pinky_62f4) moving · 107호
11:33:13 OMX emr-b23 failed 전달 sent pinky None 오류 not every try was done: green #1 not found · 안전 통과
11:33:15 NO 357 수령 · 로봇 배송로봇 3호
11:33:31 OMX emr-b23 failed 전달 sent pinky None 오류 not every try was done: green #1 not found · 안전 멈춤 person
11:33:32 로봇 3(pinky_62f4) moving · 아래 복도
11:33:34 OMX emr-b23 failed 전달 sent pinky None 오류 not every try was done: green #1 not found · 안전 통과
11:34:10 로봇 3(pinky_62f4) moving · 오른쪽 협로
11:34:25 로봇 3(pinky_62f4) moving · 위 복도
11:35:02 로봇 3(pinky_62f4) decon · POCKET(대기)
11:35:07 로봇 3(pinky_62f4) moving · POCKET(대기)
11:35:27 로봇 3(pinky_62f4) moving · 위 복도
11:35:43 로봇 3(pinky_62f4) idle · 위 복도
11:35:56 OMX emr-b23 failed 전달 sent pinky None 오류 not every try was done: green #1 not found · 안전 멈춤 person
11:35:57 OMX emr-b23 failed 전달 sent pinky None 오류 not every try was done: green #1 not found · 안전 통과
11:38:29 OMX emr-b23-r2 running 전달 pending pinky None 오류 None · 안전 통과
11:39:07 OMX emr-b23-r2 completed 전달 sent pinky grabbing 오류 None · 안전 통과
11:39:08 NO 358 준비 · 로봇 배송로봇 1호
11:39:08 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-3
11:39:20 OMX emr-b23-r2 completed 전달 sent pinky holding 오류 None · 안전 통과
11:39:45 OMX emr-b23-r2 completed 전달 sent pinky holding 오류 None · 안전 멈춤 person
11:39:57 로봇 1(pinky_6364) docking · 약제실 · 묶음 b-3
11:40:10 OMX emr-b23-r2 completed 전달 sent pinky holding 오류 None · 안전 통과
11:40:12 로봇 1(pinky_6364) loading · 약제실 · 묶음 b-3
11:40:13 NO 358 출발 · 로봇 배송로봇 1호
11:40:14 OMX emr-b23-r2 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:40:22 OMX emr-b23-r2 completed 전달 sent pinky returning 오류 None · 안전 통과
11:40:27 OMX emr-b23-r2 completed 전달 sent pinky completed 오류 None · 안전 통과
11:40:28 로봇 1(pinky_6364) moving · 약제실 · 묶음 b-3
11:40:54 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-3
11:41:09 OMX emr-b23-r2 completed 전달 sent pinky completed 오류 None · 안전 멈춤 person
11:41:11 로봇 1(pinky_6364) spinning · 105호 · 묶음 b-3
11:41:12 OMX emr-b23-r2 completed 전달 sent pinky completed 오류 None · 안전 통과
11:41:29 로봇 1(pinky_6364) pausing · 105호 · 묶음 b-3
11:41:31 NO 358 도착 · 로봇 배송로봇 1호
11:41:34 로봇 1(pinky_6364) moving · 105호
11:41:50 NO 358 수령 · 로봇 배송로봇 1호
11:41:50 신청 모두 끝 (수령·실패)
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|
| 5 | 11:19:01 | order_created | `{"order_id": "o-1", "request_id": "emr-d354-s3-1", "room": "103호", "item": "C 약품"}` |
| 6 | 11:19:01 | order_created | `{"order_id": "o-2", "request_id": "emr-d355-s3-1", "room": "105호", "item": "C 약품"}` |
| 7 | 11:19:01 | batch_assigned | `{"batch_id": "b-1", "robot": 1, "name": "pinky_6364", "orders": [{"order_id": "o-1", "room": "103호", "item": "C 약품"}, {"order_id": "o-2", "room": "105호", "item": "C 약품"}], "count": 2, "rooms": ["105호", "103호"]}` |
| 8 | 11:19:41 | robot_called | `{"batch_id": "b-1", "robot": 1, "eta_s": 36}` |
| 9 | 11:19:41 | robot_departed | `{"robot": 1, "task": "delivery", "from": "T2_130", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 10 | 11:20:12 | robot_arrived | `{"robot": 1, "node": "PHARMACY", "room": "약제실"}` |
| 11 | 11:20:32 | robot_at_pharmacy | `{"batch_id": "b-1", "robot": 1}` |
| 12 | 11:21:08 | batch_departed | `{"batch_id": "b-1", "robot": 1, "rooms": ["105호", "103호"]}` |
| 13 | 11:21:08 | robot_departed | `{"robot": 1, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM1_CUR", "room": "105호"}}` |
| 14 | 11:21:54 | robot_arrived | `{"robot": 1, "node": "ROOM1_CUR", "room": "105호"}` |
| 15 | 11:22:10 | order_delivered | `{"order_id": "o-2", "room": "105호", "robot": 1, "batch_id": "b-1"}` |
| 16 | 11:22:15 | robot_departed | `{"robot": 1, "task": "delivery", "from": "ROOM1_CUR", "to": {"node": "ROOM1_LU", "room": "103호"}}` |
| 17 | 11:22:31 | order_created | `{"order_id": "o-3", "request_id": "emr-d356-s5-1", "room": "105호", "item": "이불"}` |
| 18 | 11:22:31 | order_created | `{"order_id": "o-4", "request_id": "emr-d356-s6-1", "room": "105호", "item": "매트리스 패드"}` |
| 19 | 11:22:31 | order_created | `{"order_id": "o-5", "request_id": "emr-d357-s2-1", "room": "107호", "item": "B 약품"}` |
| 20 | 11:22:31 | batch_assigned | `{"batch_id": "b-2", "robot": 3, "name": "pinky_62f4", "orders": [{"order_id": "o-3", "room": "105호", "item": "이불"}, {"order_id": "o-4", "room": "105호", "item": "매트리스 패드"}, {"order_id": "o-5", "room": "107호", "item": "B 약품"}], "count": 3, "rooms": ["105호", "107호"]}` |
| 21 | 11:23:15 | robot_called | `{"batch_id": "b-2", "robot": 3, "eta_s": 74}` |
| 22 | 11:23:15 | robot_departed | `{"robot": 3, "task": "delivery", "from": "B1_130", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 23 | 11:23:23 | robot_error | `{"robot": 3, "name": "pinky_62f4", "code": "not_at_start", "why": "B1_130 에서 5.3 cm", "node": "B1_130", "edge": null, "task": "delivery", "batch_id": "b-2"}` |
| 24 | 11:23:45 | robot_arrived | `{"robot": 1, "node": "ROOM1_LU", "room": "103호"}` |
| 25 | 11:24:02 | order_delivered | `{"order_id": "o-1", "room": "103호", "robot": 1, "batch_id": "b-1"}` |
| 26 | 11:24:02 | batch_completed | `{"batch_id": "b-1", "robot": 1}` |
| 27 | 11:24:07 | robot_departed | `{"robot": 1, "task": "decon", "from": "ROOM1_LU", "to": {"node": "POCKET", "room": null}}` |
| 28 | 11:26:05 | robot_arrived | `{"robot": 1, "node": "POCKET", "room": null}` |
| 29 | 11:26:11 | robot_departed | `{"robot": 1, "task": "park", "from": "POCKET", "to": {"node": "T1_175", "room": null}}` |
| 30 | 11:26:46 | robot_arrived | `{"robot": 1, "node": "T1_175", "room": null}` |
| 31 | 11:29:12 | robot_arrived | `{"robot": 3, "node": "PHARMACY", "room": "약제실"}` |
| 32 | 11:29:38 | robot_at_pharmacy | `{"batch_id": "b-2", "robot": 3}` |
| 33 | 11:29:55 | batch_departed | `{"batch_id": "b-2", "robot": 3, "rooms": ["105호", "107호"]}` |
| 34 | 11:29:55 | robot_departed | `{"robot": 3, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM1_CUR", "room": "105호"}}` |
| 35 | 11:30:42 | robot_arrived | `{"robot": 3, "node": "ROOM1_CUR", "room": "105호"}` |
| 36 | 11:30:59 | order_delivered | `{"order_id": "o-3", "room": "105호", "robot": 3, "batch_id": "b-2"}` |
| 37 | 11:30:59 | order_delivered | `{"order_id": "o-4", "room": "105호", "robot": 3, "batch_id": "b-2"}` |
| 38 | 11:31:03 | robot_departed | `{"robot": 3, "task": "delivery", "from": "ROOM1_CUR", "to": {"node": "ROOM1_CLL", "room": "107호"}}` |
| 39 | 11:32:42 | order_created | `{"order_id": "o-6", "request_id": "emr-d358-s1-1", "room": "105호", "item": "A 약품"}` |
| 40 | 11:32:42 | order_created | `{"order_id": "o-7", "request_id": "emr-d358-s3-1", "room": "105호", "item": "C 약품"}` |
| 41 | 11:32:42 | batch_assigned | `{"batch_id": "b-3", "robot": 1, "name": "pinky_6364", "orders": [{"order_id": "o-6", "room": "105호", "item": "A 약품"}, {"order_id": "o-7", "room": "105호", "item": "C 약품"}], "count": 2, "rooms": ["105호"]}` |
| 42 | 11:32:51 | robot_arrived | `{"robot": 3, "node": "ROOM1_CLL", "room": "107호"}` |
| 43 | 11:33:06 | order_delivered | `{"order_id": "o-5", "room": "107호", "robot": 3, "batch_id": "b-2"}` |
| 44 | 11:33:06 | batch_completed | `{"batch_id": "b-2", "robot": 3}` |
| 45 | 11:33:11 | robot_departed | `{"robot": 3, "task": "decon", "from": "ROOM1_CLL", "to": {"node": "POCKET", "room": null}}` |
| 46 | 11:35:01 | robot_arrived | `{"robot": 3, "node": "POCKET", "room": null}` |
| 47 | 11:35:06 | robot_departed | `{"robot": 3, "task": "park", "from": "POCKET", "to": {"node": "T2_130", "room": null}}` |
| 48 | 11:35:43 | robot_arrived | `{"robot": 3, "node": "T2_130", "room": null}` |
| 49 | 11:39:07 | robot_called | `{"batch_id": "b-3", "robot": 1, "eta_s": 51}` |
| 50 | 11:39:08 | robot_departed | `{"robot": 1, "task": "delivery", "from": "T1_175", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 51 | 11:39:56 | robot_arrived | `{"robot": 1, "node": "PHARMACY", "room": "약제실"}` |
| 52 | 11:40:12 | robot_at_pharmacy | `{"batch_id": "b-3", "robot": 1}` |
| 53 | 11:40:28 | batch_departed | `{"batch_id": "b-3", "robot": 1, "rooms": ["105호"]}` |
| 54 | 11:40:28 | robot_departed | `{"robot": 1, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM1_CUR", "room": "105호"}}` |
| 55 | 11:41:11 | robot_arrived | `{"robot": 1, "node": "ROOM1_CUR", "room": "105호"}` |
| 56 | 11:41:29 | order_delivered | `{"order_id": "o-6", "room": "105호", "robot": 1, "batch_id": "b-3"}` |
| 57 | 11:41:29 | order_delivered | `{"order_id": "o-7", "room": "105호", "robot": 1, "batch_id": "b-3"}` |
| 58 | 11:41:29 | batch_completed | `{"batch_id": "b-3", "robot": 1}` |

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)

## EMR 경고·오류

```
{"batch_id": "b-3", "step": "picking", "request_id": "emr-b23", "reason": "pick failed: not every try was done: green #1 not found", "event": "fms_omx_failed", "level": "error", "timestamp": "2026-11-02T02:33:13.139451Z"}
{"omx_base_url": "http://172.18.0.1:18000", "detail": "FMS batches are loaded by the real OMX arm \u2014 the arm moves (FMS_OMX_ENABLED=1)", "event": "fms_omx_enabled", "level": "warning", "timestamp": "2026-11-02T02:34:59.373201Z"}
{"acting_as": "N001", "detail": "JWT login is OFF \u2014 anyone on the network acts as this admin (AUTH_DISABLED=1)", "event": "auth_disabled", "level": "warning", "timestamp": "2026-11-02T02:34:59.373222Z"}
{"acting_as_robot_id": 1, "detail": "robot API key check is OFF \u2014 calls without a key act as this robot (ROBOT_KEY_DISABLED=1)", "event": "robot_key_disabled", "level": "warning", "timestamp": "2026-11-02T02:34:59.373238Z"}
{"omx_base_url": "http://172.18.0.1:18000", "detail": "FMS batches are loaded by the real OMX arm \u2014 the arm moves (FMS_OMX_ENABLED=1)", "event": "fms_omx_enabled", "level": "warning", "timestamp": "2026-11-02T02:35:01.079160Z"}
{"acting_as": "N001", "detail": "JWT login is OFF \u2014 anyone on the network acts as this admin (AUTH_DISABLED=1)", "event": "auth_disabled", "level": "warning", "timestamp": "2026-11-02T02:35:01.079181Z"}
{"acting_as_robot_id": 1, "detail": "robot API key check is OFF \u2014 calls without a key act as this robot (ROBOT_KEY_DISABLED=1)", "event": "robot_key_disabled", "level": "warning", "timestamp": "2026-11-02T02:35:01.079199Z"}
{"omx_base_url": "http://172.18.0.1:18000", "detail": "FMS batches are loaded by the real OMX arm \u2014 the arm moves (FMS_OMX_ENABLED=1)", "event": "fms_omx_enabled", "level": "warning", "timestamp": "2026-11-02T02:35:14.808523Z"}
{"acting_as": "N001", "detail": "JWT login is OFF \u2014 anyone on the network acts as this admin (AUTH_DISABLED=1)", "event": "auth_disabled", "level": "warning", "timestamp": "2026-11-02T02:35:14.808543Z"}
{"acting_as_robot_id": 1, "detail": "robot API key check is OFF \u2014 calls without a key act as this robot (ROBOT_KEY_DISABLED=1)", "event": "robot_key_disabled", "level": "warning", "timestamp": "2026-11-02T02:35:14.808561Z"}
```
