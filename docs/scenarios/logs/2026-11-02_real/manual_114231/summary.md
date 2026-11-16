# 실물 시험 로그 — manual_114231 (11-02 사용자 직접 신청 2차, 중지)

- 일시: 2026-11-02 11:42:54 ~ 11:52:34 (KST)
- 환경: manual_112001과 같음 — 실물 Pinky 2대(1번·3번, --robots 2) + 실물 OMX(fixed), EMR 간호사 N001이 화면에서 직접 신청(기록만)
- 결과: NO 359 수령, NO 360 수령
- EMR api 경고·오류: 0줄 (`emr_api.log`)

## 결과 — 2건 수령, 2건 지움(사용자 중지)

| 신청 | 묶음 | 결과 |
|---|---|---|
| NO 359 106호 A 약품, NO 360 103호 C 약품 | b-4 (3호) | OMX `emr-b24` 1초 만에 실패(**파랑·초록 둘 다 못 찾음**, 11:42:37 — 1차에서 거즈 3번 집어 테이블이 빔) → 사용자 "풀어줘" → `emr-b24-r2` 성공 → 수령 |
| NO 361 104호 환자복, NO 362 106호 플라스틱 컵 | b-6, b-5 | **11:52 예약 신청**(즉시 아님 — 그래서 11:44에 '예약'에 머문 것이 정상). 1호 약제실 정밀 주차 · OMX `emr-b25` 들고 대기 중에 사용자 "중지" |

## 중지와 정리 (11:52~11:56)

1. FMS `POST /api/control {"paused": true}` — 새 주행 명령만 막는다(이미 보낸 /drive는 끝까지 감). 1호는 정밀 주차를 마치고 섰다.
   OMX는 `emr-b25`를 든 채 대기: EMR은 FMS `robot_at_pharmacy`를 받아야 `/pinky`를 보내는데 그 전에 멈춰 내려놓지 않음을 확인.
2. 사용자 "핑키 위치 리셋하면서 실패기록 삭제" → 선택 "진행 중 2건만" · "FMS 다시 띄워 주차":
   NO 361·362 재고 되돌림(환자복 38→39, 플라스틱 컵 198→199) 후 삭제, EMR 묶음 b-5·b-6 삭제. 백업 `~/emr_backups/emr_before_del361_362_20261102_115540.sql.gz`.
   FMS 다시 띄움(같은 2대 설정) → 3호는 T1_175 주차.
3. **1호가 약제실에서 나오다 `bad_direction`** (11:56:31, 팀원 `driving/tools/lane_drive.py:155`): GT99U → T2_98.9 차선 옮겨 타기에서 새 차선까지 3.5 cm(5 cm 미만이면 방향이 틀렸다고 멈춤), 가로로도 문 가운데에서 9 cm 벗어남(pose (89.9, 156.0) −89.7°). 사람이 T2_98.9에 올린 뒤 위치 확인·`clear_fault`가 필요 — 이 기록을 쓸 때 아직 그대로.
4. OMX는 `emr-b25` 거즈를 든 채 — 따로 정리 필요.

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 359 | 106호 | A 약품 ×1 | 1건 | b-4 | 3 → 배송로봇 3호 | 11:42:31 | 11:46:14 | 11:47:03 | 11:49:12 | 11:49:17 | 401 |
| 360 | 103호 | C 약품 ×1 | 1건 | b-4 | 3 → 배송로봇 3호 | 11:42:31 | 11:46:14 | 11:47:03 | 11:50:04 | 11:50:14 | 453 |

## 진행 흐름 (자막)

```
11:42:54 기록 시작 — 사용자가 화면에서 직접 신청, 기존 신청 358건은 제외
11:42:54 새 신청 NO 359 N001 106호 — A 약품 1개
11:42:54 NO 359 예약
11:42:54 새 신청 NO 360 N001 103호 — C 약품 1개
11:42:54 NO 360 예약
11:42:54 새 신청 NO 361 N001 104호 — 환자복 1개
11:42:54 NO 361 예약
11:42:54 새 신청 NO 362 N001 106호 — 플라스틱 컵 1개
11:42:54 NO 362 예약
11:42:54 로봇 1(pinky_6364) moving · POCKET(대기)
11:42:54 로봇 3(pinky_62f4) reserved · 위 복도 · 묶음 b-4
11:42:54 OMX emr-b24 failed 전달 sent pinky None 오류 not every try was done: blue #1 not found, green #1 not found · 안전 통과
11:43:05 OMX emr-b24 failed 전달 sent pinky None 오류 not every try was done: blue #1 not found, green #1 not found · 안전 멈춤 person
11:43:07 OMX emr-b24 failed 전달 sent pinky None 오류 not every try was done: blue #1 not found, green #1 not found · 안전 통과
11:43:13 로봇 1(pinky_6364) moving · 위 복도
11:43:33 로봇 1(pinky_6364) idle · 위 복도
11:45:02 OMX emr-b24 failed 전달 sent pinky None 오류 not every try was done: blue #1 not found, green #1 not found · 안전 멈춤 person
11:45:17 OMX emr-b24 failed 전달 sent pinky None 오류 not every try was done: blue #1 not found, green #1 not found · 안전 통과
11:45:36 OMX emr-b24-r2 running 전달 pending pinky None 오류 None · 안전 통과
11:46:14 OMX emr-b24-r2 completed 전달 sent pinky grabbing 오류 None · 안전 통과
11:46:15 NO 359 준비 · 로봇 배송로봇 3호
11:46:15 NO 360 준비 · 로봇 배송로봇 3호
11:46:15 로봇 3(pinky_62f4) moving · 위 복도 · 묶음 b-4
11:46:26 OMX emr-b24-r2 completed 전달 sent pinky holding 오류 None · 안전 통과
11:46:41 로봇 3(pinky_62f4) docking · 약제실 · 묶음 b-4
11:47:03 NO 359 출발 · 로봇 배송로봇 3호
11:47:03 NO 360 출발 · 로봇 배송로봇 3호
11:47:03 로봇 3(pinky_62f4) loading · 약제실 · 묶음 b-4
11:47:05 OMX emr-b24-r2 completed 전달 sent pinky releasing 오류 None · 안전 통과
11:47:13 OMX emr-b24-r2 completed 전달 sent pinky returning 오류 None · 안전 통과
11:47:18 OMX emr-b24-r2 completed 전달 sent pinky completed 오류 None · 안전 통과
11:47:20 로봇 3(pinky_62f4) moving · 약제실 · 묶음 b-4
11:47:24 OMX emr-b24-r2 completed 전달 sent pinky completed 오류 None · 안전 멈춤 person
11:47:28 OMX emr-b24-r2 completed 전달 sent pinky completed 오류 None · 안전 통과
11:47:45 로봇 3(pinky_62f4) moving · 위 복도 · 묶음 b-4
11:47:49 OMX emr-b24-r2 completed 전달 sent pinky completed 오류 None · 안전 멈춤 person
11:47:58 OMX emr-b24-r2 completed 전달 sent pinky completed 오류 None · 안전 통과
11:48:22 로봇 3(pinky_62f4) moving · 왼쪽 협로 · 묶음 b-4
11:48:39 로봇 3(pinky_62f4) moving · 단일차선 협로 · 묶음 b-4
11:48:51 로봇 3(pinky_62f4) spinning · 106호 · 묶음 b-4
11:49:12 NO 359 도착 · 로봇 배송로봇 3호
11:49:12 로봇 3(pinky_62f4) pausing · 106호 · 묶음 b-4
11:49:16 로봇 3(pinky_62f4) moving · 106호 · 묶음 b-4
11:49:18 NO 359 수령 · 로봇 배송로봇 3호
11:49:40 로봇 3(pinky_62f4) moving · 단일차선 협로 · 묶음 b-4
11:49:50 로봇 3(pinky_62f4) spinning · 103호 · 묶음 b-4
11:50:05 NO 360 도착 · 로봇 배송로봇 3호
11:50:05 로봇 3(pinky_62f4) pausing · 103호 · 묶음 b-4
11:50:08 로봇 3(pinky_62f4) moving · 103호
11:50:15 NO 360 수령 · 로봇 배송로봇 3호
11:50:31 로봇 1(pinky_6364) reserved · 위 복도 · 묶음 b-5
11:50:32 OMX emr-b25 running 전달 pending pinky None 오류 None · 안전 통과
11:50:33 로봇 3(pinky_62f4) moving · 단일차선 협로
11:50:45 로봇 3(pinky_62f4) moving · 왼쪽 협로
11:51:10 OMX emr-b25 completed 전달 pending pinky None 오류 None · 안전 통과
11:51:11 OMX emr-b25 completed 전달 sent pinky grabbing 오류 None · 안전 통과
11:51:12 NO 362 준비 · 로봇 배송로봇 1호
11:51:12 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-5
11:51:16 로봇 3(pinky_62f4) moving · 오른쪽 협로
11:51:23 OMX emr-b25 completed 전달 sent pinky holding 오류 None · 안전 통과
11:51:30 로봇 3(pinky_62f4) moving · 위 복도
11:51:35 로봇 1(pinky_6364) waiting · 위 복도 · 묶음 b-5
11:51:41 로봇 1(pinky_6364) moving · 위 복도 · 묶음 b-5
11:51:59 OMX emr-b25 completed 전달 sent pinky holding 오류 None · 안전 멈춤 person
11:52:04 OMX emr-b25 completed 전달 sent pinky holding 오류 None · 안전 통과
11:52:13 로봇 3(pinky_62f4) decon · POCKET(대기)
11:52:19 로봇 3(pinky_62f4) reserved · POCKET(대기) · 묶음 b-6
11:52:29 OMX emr-b25 completed 전달 sent pinky holding 오류 None · 안전 멈춤 person
11:52:30 로봇 1(pinky_6364) docking · 약제실 · 묶음 b-5
11:52:34 OMX emr-b25 completed 전달 sent pinky holding 오류 None · 안전 통과
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)
