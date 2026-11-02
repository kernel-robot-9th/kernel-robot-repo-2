# 실물 시험 로그 — 장면 A 7차, 성공 (181343)

- 일시: 2026-10-30 18:13:54 ~ 18:20:13 (KST)
- 환경: **실물** — 실제 Pinky 3대(FMS 도커 `--real-table --no-auto-omx`) + 실제 OMX(10.42.0.147, `FMS_OMX_ENABLED=1`), EMR 간호사 N003
- 결과: NO 351 수령, NO 352 수령, NO 353 수령
- EMR api 경고·오류: 0줄 (`emr_api.log`)

## 이번 시험에서 확인한 것

- **끝까지 성공**: 간호사 화면 '즉시' 신청 → FMS 묶음 b-1(3번 로봇) → 실제 OMX `blue:1, green:1` 집기(38초) → `ready` → 약제실 정밀 주차 → OMX 내려놓기(EMR `/pinky`) → `loaded` → 101·104·103호 → 수령 3건. 1번 로봇은 꺼져 있었음(`unreachable`), 2·3번으로 진행.
- **수령은 API로 함(간호사 N003과 같은 요청)**: 화면에 도착 창이 뜨지 않았다. EMR 버그 — `GET /deliveries`(`list_by_nurse`)가 보낼 시간이 오래된 순서로 100건만 돌려주는데, 오늘 시험으로 N003 신청이 350건쯤 쌓여 새 신청이 화면에 오지 않음(도착 창 `ReceiptMarkerWatcher`도 못 봄). 아직 안 고침.
- 앞선 3~6차 실패 원인: OMX 안전 기능(사람 감지 신호 없음, 16:13~18:01), OMX가 EMR `/pinky` 없이 내려놓음(18:02), Pinky 망 끊김·재부팅, 녹색 거즈 없음.

## 신청별 단계 시각 (KST)

| NO | 지점 | 물품 | FMS 주문 | 묶음 | FMS 로봇 → EMR 로봇 | 신청 | 준비 | 출발 | 도착 | 수령 | 신청→도착(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 351 | 101호 | A 약품 ×1 | 1건 | b-1 | 3 → 배송로봇 3호 | 18:13:59 | 18:14:44 | 18:15:51 | 18:17:32 | 18:19:12 | 213 |
| 352 | 103호 | B 약품 ×1 | 1건 | b-1 | 3 → 배송로봇 3호 | 18:13:59 | 18:14:44 | 18:15:51 | 18:20:05 | 18:20:13 | 366 |
| 353 | 104호 | C 약품 ×1 | 1건 | b-1 | 3 → 배송로봇 3호 | 18:13:59 | 18:14:44 | 18:15:51 | 18:18:45 | 18:19:12 | 286 |

## 진행 흐름 (자막)

```
18:13:54 장면 A (실물) — FMS 잠깐 멈춤: 주문 3건을 한 묶음으로 모은다 | 신청: 101호 A 약품 1개 · 103호 B 약품 1개 · 104호 C 약품 1개
18:14:01 화면 신청 생김 NO [351, 352, 353]
18:14:03 FMS 대기 주문 3건 → 재개
18:14:03 장면 A (실물 Pinky + 실물 OMX)  0:00 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 대기 위 복도 | OMX failed/failed
18:14:04 장면 A (실물 Pinky + 실물 OMX)  0:01 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX failed/failed
18:14:05 장면 A (실물 Pinky + 실물 OMX)  0:02 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:06 장면 A (실물 Pinky + 실물 OMX)  0:03 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:08 장면 A (실물 Pinky + 실물 OMX)  0:04 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:09 장면 A (실물 Pinky + 실물 OMX)  0:05 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:10 장면 A (실물 Pinky + 실물 OMX)  0:06 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:11 장면 A (실물 Pinky + 실물 OMX)  0:07 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:12 장면 A (실물 Pinky + 실물 OMX)  0:08 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:13 장면 A (실물 Pinky + 실물 OMX)  0:10 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:14 장면 A (실물 Pinky + 실물 OMX)  0:11 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:15 장면 A (실물 Pinky + 실물 OMX)  0:12 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:16 장면 A (실물 Pinky + 실물 OMX)  0:13 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:18 장면 A (실물 Pinky + 실물 OMX)  0:14 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:19 장면 A (실물 Pinky + 실물 OMX)  0:15 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:20 장면 A (실물 Pinky + 실물 OMX)  0:16 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:21 장면 A (실물 Pinky + 실물 OMX)  0:17 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:22 장면 A (실물 Pinky + 실물 OMX)  0:19 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:23 장면 A (실물 Pinky + 실물 OMX)  0:20 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:24 장면 A (실물 Pinky + 실물 OMX)  0:21 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:25 장면 A (실물 Pinky + 실물 OMX)  0:22 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:26 장면 A (실물 Pinky + 실물 OMX)  0:23 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:28 장면 A (실물 Pinky + 실물 OMX)  0:24 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:29 장면 A (실물 Pinky + 실물 OMX)  0:25 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:30 장면 A (실물 Pinky + 실물 OMX)  0:26 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:31 장면 A (실물 Pinky + 실물 OMX)  0:27 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:32 장면 A (실물 Pinky + 실물 OMX)  0:28 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:33 장면 A (실물 Pinky + 실물 OMX)  0:29 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:34 장면 A (실물 Pinky + 실물 OMX)  0:30 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:35 장면 A (실물 Pinky + 실물 OMX)  0:31 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:36 장면 A (실물 Pinky + 실물 OMX)  0:33 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:37 장면 A (실물 Pinky + 실물 OMX)  0:34 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:38 장면 A (실물 Pinky + 실물 OMX)  0:35 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:39 장면 A (실물 Pinky + 실물 OMX)  0:36 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:41 장면 A (실물 Pinky + 실물 OMX)  0:37 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:42 장면 A (실물 Pinky + 실물 OMX)  0:38 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX running/running
18:14:43 장면 A (실물 Pinky + 실물 OMX)  0:39 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 배차됨 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:44 장면 A (실물 Pinky + 실물 OMX)  0:40 | NO 351 101호 예약 · NO 352 103호 예약 · NO 353 104호 예약 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:45 장면 A (실물 Pinky + 실물 OMX)  0:41 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:46 장면 A (실물 Pinky + 실물 OMX)  0:43 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:47 장면 A (실물 Pinky + 실물 OMX)  0:44 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:48 장면 A (실물 Pinky + 실물 OMX)  0:45 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:49 장면 A (실물 Pinky + 실물 OMX)  0:46 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:50 장면 A (실물 Pinky + 실물 OMX)  0:47 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:52 장면 A (실물 Pinky + 실물 OMX)  0:48 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:53 장면 A (실물 Pinky + 실물 OMX)  0:49 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:54 장면 A (실물 Pinky + 실물 OMX)  0:50 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:55 장면 A (실물 Pinky + 실물 OMX)  0:51 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 grabbing
18:14:56 장면 A (실물 Pinky + 실물 OMX)  0:52 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:14:57 장면 A (실물 Pinky + 실물 OMX)  0:53 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:14:58 장면 A (실물 Pinky + 실물 OMX)  0:54 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:14:59 장면 A (실물 Pinky + 실물 OMX)  0:56 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:00 장면 A (실물 Pinky + 실물 OMX)  0:57 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:01 장면 A (실물 Pinky + 실물 OMX)  0:58 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:02 장면 A (실물 Pinky + 실물 OMX)  0:59 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:03 장면 A (실물 Pinky + 실물 OMX)  1:00 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:05 장면 A (실물 Pinky + 실물 OMX)  1:01 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:06 장면 A (실물 Pinky + 실물 OMX)  1:02 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:07 장면 A (실물 Pinky + 실물 OMX)  1:03 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:08 장면 A (실물 Pinky + 실물 OMX)  1:04 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:09 장면 A (실물 Pinky + 실물 OMX)  1:05 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:10 장면 A (실물 Pinky + 실물 OMX)  1:06 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:11 장면 A (실물 Pinky + 실물 OMX)  1:08 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:12 장면 A (실물 Pinky + 실물 OMX)  1:09 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:13 장면 A (실물 Pinky + 실물 OMX)  1:10 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:14 장면 A (실물 Pinky + 실물 OMX)  1:11 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:16 장면 A (실물 Pinky + 실물 OMX)  1:12 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:17 장면 A (실물 Pinky + 실물 OMX)  1:13 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:18 장면 A (실물 Pinky + 실물 OMX)  1:14 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:19 장면 A (실물 Pinky + 실물 OMX)  1:15 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:20 장면 A (실물 Pinky + 실물 OMX)  1:16 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:21 장면 A (실물 Pinky + 실물 OMX)  1:17 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:22 장면 A (실물 Pinky + 실물 OMX)  1:19 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:23 장면 A (실물 Pinky + 실물 OMX)  1:20 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:24 장면 A (실물 Pinky + 실물 OMX)  1:21 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:25 장면 A (실물 Pinky + 실물 OMX)  1:22 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:27 장면 A (실물 Pinky + 실물 OMX)  1:23 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:28 장면 A (실물 Pinky + 실물 OMX)  1:24 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:29 장면 A (실물 Pinky + 실물 OMX)  1:25 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:30 장면 A (실물 Pinky + 실물 OMX)  1:26 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:31 장면 A (실물 Pinky + 실물 OMX)  1:27 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:32 장면 A (실물 Pinky + 실물 OMX)  1:28 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:33 장면 A (실물 Pinky + 실물 OMX)  1:30 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:34 장면 A (실물 Pinky + 실물 OMX)  1:31 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 holding
18:15:35 장면 A (실물 Pinky + 실물 OMX)  1:32 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:37 장면 A (실물 Pinky + 실물 OMX)  1:33 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:38 장면 A (실물 Pinky + 실물 OMX)  1:34 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:39 장면 A (실물 Pinky + 실물 OMX)  1:35 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:40 장면 A (실물 Pinky + 실물 OMX)  1:36 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:41 장면 A (실물 Pinky + 실물 OMX)  1:37 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:42 장면 A (실물 Pinky + 실물 OMX)  1:38 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:43 장면 A (실물 Pinky + 실물 OMX)  1:40 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:44 장면 A (실물 Pinky + 실물 OMX)  1:41 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:46 장면 A (실물 Pinky + 실물 OMX)  1:42 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:47 장면 A (실물 Pinky + 실물 OMX)  1:43 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:48 장면 A (실물 Pinky + 실물 OMX)  1:44 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:49 장면 A (실물 Pinky + 실물 OMX)  1:45 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:50 장면 A (실물 Pinky + 실물 OMX)  1:46 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:51 장면 A (실물 Pinky + 실물 OMX)  1:47 | NO 351 101호 준비 · NO 352 103호 준비 · NO 353 104호 준비 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 정밀 주차 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:52 장면 A (실물 Pinky + 실물 OMX)  1:48 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:53 장면 A (실물 Pinky + 실물 OMX)  1:50 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 holding
18:15:54 장면 A (실물 Pinky + 실물 OMX)  1:51 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:15:56 장면 A (실물 Pinky + 실물 OMX)  1:52 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:15:57 장면 A (실물 Pinky + 실물 OMX)  1:53 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:15:58 장면 A (실물 Pinky + 실물 OMX)  1:54 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:15:59 장면 A (실물 Pinky + 실물 OMX)  1:55 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:16:00 장면 A (실물 Pinky + 실물 OMX)  1:56 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:16:01 장면 A (실물 Pinky + 실물 OMX)  1:58 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 releasing
18:16:02 장면 A (실물 Pinky + 실물 OMX)  1:59 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 returning
18:16:03 장면 A (실물 Pinky + 실물 OMX)  2:00 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 returning
18:16:04 장면 A (실물 Pinky + 실물 OMX)  2:01 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 returning
18:16:05 장면 A (실물 Pinky + 실물 OMX)  2:02 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 returning
18:16:06 장면 A (실물 Pinky + 실물 OMX)  2:03 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 적재 대기 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:08 장면 A (실물 Pinky + 실물 OMX)  2:04 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:09 장면 A (실물 Pinky + 실물 OMX)  2:05 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:10 장면 A (실물 Pinky + 실물 OMX)  2:06 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:11 장면 A (실물 Pinky + 실물 OMX)  2:07 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:12 장면 A (실물 Pinky + 실물 OMX)  2:08 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:13 장면 A (실물 Pinky + 실물 OMX)  2:09 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:14 장면 A (실물 Pinky + 실물 OMX)  2:11 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:15 장면 A (실물 Pinky + 실물 OMX)  2:12 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:16 장면 A (실물 Pinky + 실물 OMX)  2:13 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:17 장면 A (실물 Pinky + 실물 OMX)  2:14 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:19 장면 A (실물 Pinky + 실물 OMX)  2:15 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:20 장면 A (실물 Pinky + 실물 OMX)  2:16 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:21 장면 A (실물 Pinky + 실물 OMX)  2:17 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:22 장면 A (실물 Pinky + 실물 OMX)  2:18 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:23 장면 A (실물 Pinky + 실물 OMX)  2:20 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:24 장면 A (실물 Pinky + 실물 OMX)  2:21 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:25 장면 A (실물 Pinky + 실물 OMX)  2:22 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:26 장면 A (실물 Pinky + 실물 OMX)  2:23 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:27 장면 A (실물 Pinky + 실물 OMX)  2:24 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:29 장면 A (실물 Pinky + 실물 OMX)  2:25 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:30 장면 A (실물 Pinky + 실물 OMX)  2:26 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:31 장면 A (실물 Pinky + 실물 OMX)  2:27 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:32 장면 A (실물 Pinky + 실물 OMX)  2:28 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:33 장면 A (실물 Pinky + 실물 OMX)  2:29 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:34 장면 A (실물 Pinky + 실물 OMX)  2:31 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:35 장면 A (실물 Pinky + 실물 OMX)  2:32 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 약제실(b-1) | OMX completed/done 내려놓기 completed
18:16:36 장면 A (실물 Pinky + 실물 OMX)  2:33 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:37 장면 A (실물 Pinky + 실물 OMX)  2:34 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:38 장면 A (실물 Pinky + 실물 OMX)  2:35 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:40 장면 A (실물 Pinky + 실물 OMX)  2:36 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:41 장면 A (실물 Pinky + 실물 OMX)  2:37 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:42 장면 A (실물 Pinky + 실물 OMX)  2:38 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:43 장면 A (실물 Pinky + 실물 OMX)  2:39 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:44 장면 A (실물 Pinky + 실물 OMX)  2:41 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:45 장면 A (실물 Pinky + 실물 OMX)  2:42 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:46 장면 A (실물 Pinky + 실물 OMX)  2:43 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:48 장면 A (실물 Pinky + 실물 OMX)  2:44 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:49 장면 A (실물 Pinky + 실물 OMX)  2:45 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:50 장면 A (실물 Pinky + 실물 OMX)  2:46 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:51 장면 A (실물 Pinky + 실물 OMX)  2:47 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:52 장면 A (실물 Pinky + 실물 OMX)  2:48 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:53 장면 A (실물 Pinky + 실물 OMX)  2:49 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:54 장면 A (실물 Pinky + 실물 OMX)  2:51 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:55 장면 A (실물 Pinky + 실물 OMX)  2:52 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:56 장면 A (실물 Pinky + 실물 OMX)  2:53 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:57 장면 A (실물 Pinky + 실물 OMX)  2:54 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:58 장면 A (실물 Pinky + 실물 OMX)  2:55 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:16:59 장면 A (실물 Pinky + 실물 OMX)  2:56 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:01 장면 A (실물 Pinky + 실물 OMX)  2:57 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:02 장면 A (실물 Pinky + 실물 OMX)  2:58 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:03 장면 A (실물 Pinky + 실물 OMX)  2:59 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:04 장면 A (실물 Pinky + 실물 OMX)  3:00 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:05 장면 A (실물 Pinky + 실물 OMX)  3:01 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:06 장면 A (실물 Pinky + 실물 OMX)  3:02 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:07 장면 A (실물 Pinky + 실물 OMX)  3:03 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:08 장면 A (실물 Pinky + 실물 OMX)  3:04 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:09 장면 A (실물 Pinky + 실물 OMX)  3:06 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:10 장면 A (실물 Pinky + 실물 OMX)  3:07 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:11 장면 A (실물 Pinky + 실물 OMX)  3:08 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:12 장면 A (실물 Pinky + 실물 OMX)  3:09 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:13 장면 A (실물 Pinky + 실물 OMX)  3:10 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:14 장면 A (실물 Pinky + 실물 OMX)  3:11 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:16 장면 A (실물 Pinky + 실물 OMX)  3:12 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:17 장면 A (실물 Pinky + 실물 OMX)  3:13 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:18 장면 A (실물 Pinky + 실물 OMX)  3:14 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:19 장면 A (실물 Pinky + 실물 OMX)  3:15 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:20 장면 A (실물 Pinky + 실물 OMX)  3:16 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:21 장면 A (실물 Pinky + 실물 OMX)  3:17 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:22 장면 A (실물 Pinky + 실물 OMX)  3:18 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:23 장면 A (실물 Pinky + 실물 OMX)  3:20 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:24 장면 A (실물 Pinky + 실물 OMX)  3:21 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:25 장면 A (실물 Pinky + 실물 OMX)  3:22 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:26 장면 A (실물 Pinky + 실물 OMX)  3:23 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:27 장면 A (실물 Pinky + 실물 OMX)  3:24 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:28 장면 A (실물 Pinky + 실물 OMX)  3:25 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:30 장면 A (실물 Pinky + 실물 OMX)  3:26 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:31 장면 A (실물 Pinky + 실물 OMX)  3:27 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:32 장면 A (실물 Pinky + 실물 OMX)  3:28 | NO 351 101호 출발 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:33 장면 A (실물 Pinky + 실물 OMX)  3:29 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:34 장면 A (실물 Pinky + 실물 OMX)  3:30 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:35 장면 A (실물 Pinky + 실물 OMX)  3:31 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:36 장면 A (실물 Pinky + 실물 OMX)  3:33 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:37 장면 A (실물 Pinky + 실물 OMX)  3:34 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:38 장면 A (실물 Pinky + 실물 OMX)  3:35 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:39 장면 A (실물 Pinky + 실물 OMX)  3:36 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:41 장면 A (실물 Pinky + 실물 OMX)  3:37 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:42 장면 A (실물 Pinky + 실물 OMX)  3:38 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:43 장면 A (실물 Pinky + 실물 OMX)  3:39 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:44 장면 A (실물 Pinky + 실물 OMX)  3:40 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:45 장면 A (실물 Pinky + 실물 OMX)  3:41 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:46 장면 A (실물 Pinky + 실물 OMX)  3:42 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:47 장면 A (실물 Pinky + 실물 OMX)  3:43 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:48 장면 A (실물 Pinky + 실물 OMX)  3:44 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:49 장면 A (실물 Pinky + 실물 OMX)  3:46 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:50 장면 A (실물 Pinky + 실물 OMX)  3:47 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:51 장면 A (실물 Pinky + 실물 OMX)  3:48 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:52 장면 A (실물 Pinky + 실물 OMX)  3:49 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:54 장면 A (실물 Pinky + 실물 OMX)  3:50 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:55 장면 A (실물 Pinky + 실물 OMX)  3:51 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 101호(b-1) | OMX completed/done 내려놓기 completed
18:17:56 장면 A (실물 Pinky + 실물 OMX)  3:52 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:57 장면 A (실물 Pinky + 실물 OMX)  3:53 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:58 장면 A (실물 Pinky + 실물 OMX)  3:54 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:17:59 장면 A (실물 Pinky + 실물 OMX)  3:55 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:00 장면 A (실물 Pinky + 실물 OMX)  3:56 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:01 장면 A (실물 Pinky + 실물 OMX)  3:58 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:02 장면 A (실물 Pinky + 실물 OMX)  3:59 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:03 장면 A (실물 Pinky + 실물 OMX)  4:00 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:05 장면 A (실물 Pinky + 실물 OMX)  4:01 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:06 장면 A (실물 Pinky + 실물 OMX)  4:02 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:07 장면 A (실물 Pinky + 실물 OMX)  4:03 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:08 장면 A (실물 Pinky + 실물 OMX)  4:04 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:09 장면 A (실물 Pinky + 실물 OMX)  4:05 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:10 장면 A (실물 Pinky + 실물 OMX)  4:07 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:11 장면 A (실물 Pinky + 실물 OMX)  4:08 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:12 장면 A (실물 Pinky + 실물 OMX)  4:09 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:13 장면 A (실물 Pinky + 실물 OMX)  4:10 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:15 장면 A (실물 Pinky + 실물 OMX)  4:11 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:16 장면 A (실물 Pinky + 실물 OMX)  4:12 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:17 장면 A (실물 Pinky + 실물 OMX)  4:13 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 위 복도(b-1) | OMX completed/done 내려놓기 completed
18:18:18 장면 A (실물 Pinky + 실물 OMX)  4:14 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:19 장면 A (실물 Pinky + 실물 OMX)  4:15 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:20 장면 A (실물 Pinky + 실물 OMX)  4:16 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:21 장면 A (실물 Pinky + 실물 OMX)  4:18 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:22 장면 A (실물 Pinky + 실물 OMX)  4:19 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:23 장면 A (실물 Pinky + 실물 OMX)  4:20 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:24 장면 A (실물 Pinky + 실물 OMX)  4:21 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:26 장면 A (실물 Pinky + 실물 OMX)  4:22 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:27 장면 A (실물 Pinky + 실물 OMX)  4:23 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:28 장면 A (실물 Pinky + 실물 OMX)  4:24 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:18:29 장면 A (실물 Pinky + 실물 OMX)  4:25 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:30 장면 A (실물 Pinky + 실물 OMX)  4:26 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:31 장면 A (실물 Pinky + 실물 OMX)  4:27 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:32 장면 A (실물 Pinky + 실물 OMX)  4:28 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:33 장면 A (실물 Pinky + 실물 OMX)  4:30 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:34 장면 A (실물 Pinky + 실물 OMX)  4:31 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:35 장면 A (실물 Pinky + 실물 OMX)  4:32 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:36 장면 A (실물 Pinky + 실물 OMX)  4:33 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:38 장면 A (실물 Pinky + 실물 OMX)  4:34 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:39 장면 A (실물 Pinky + 실물 OMX)  4:35 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:40 장면 A (실물 Pinky + 실물 OMX)  4:36 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:41 장면 A (실물 Pinky + 실물 OMX)  4:37 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:42 장면 A (실물 Pinky + 실물 OMX)  4:38 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:43 장면 A (실물 Pinky + 실물 OMX)  4:40 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:44 장면 A (실물 Pinky + 실물 OMX)  4:41 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:45 장면 A (실물 Pinky + 실물 OMX)  4:42 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 출발 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:46 장면 A (실물 Pinky + 실물 OMX)  4:43 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:47 장면 A (실물 Pinky + 실물 OMX)  4:44 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:49 장면 A (실물 Pinky + 실물 OMX)  4:45 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:50 장면 A (실물 Pinky + 실물 OMX)  4:46 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:51 장면 A (실물 Pinky + 실물 OMX)  4:47 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:52 장면 A (실물 Pinky + 실물 OMX)  4:48 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:53 장면 A (실물 Pinky + 실물 OMX)  4:49 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:54 장면 A (실물 Pinky + 실물 OMX)  4:50 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:55 장면 A (실물 Pinky + 실물 OMX)  4:52 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:56 장면 A (실물 Pinky + 실물 OMX)  4:53 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:57 장면 A (실물 Pinky + 실물 OMX)  4:54 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:18:59 장면 A (실물 Pinky + 실물 OMX)  4:55 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:00 장면 A (실물 Pinky + 실물 OMX)  4:56 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:01 장면 A (실물 Pinky + 실물 OMX)  4:57 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:02 장면 A (실물 Pinky + 실물 OMX)  4:58 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:03 장면 A (실물 Pinky + 실물 OMX)  4:59 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:04 장면 A (실물 Pinky + 실물 OMX)  5:01 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:05 장면 A (실물 Pinky + 실물 OMX)  5:02 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:06 장면 A (실물 Pinky + 실물 OMX)  5:03 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:07 장면 A (실물 Pinky + 실물 OMX)  5:04 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:08 장면 A (실물 Pinky + 실물 OMX)  5:05 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:10 장면 A (실물 Pinky + 실물 OMX)  5:06 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 104호(b-1) | OMX completed/done 내려놓기 completed
18:19:11 장면 A (실물 Pinky + 실물 OMX)  5:07 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:12 장면 A (실물 Pinky + 실물 OMX)  5:08 | NO 351 101호 도착 · NO 352 103호 출발 · NO 353 104호 도착 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:13 장면 A (실물 Pinky + 실물 OMX)  5:09 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:14 장면 A (실물 Pinky + 실물 OMX)  5:10 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:15 장면 A (실물 Pinky + 실물 OMX)  5:12 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:16 장면 A (실물 Pinky + 실물 OMX)  5:13 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:17 장면 A (실물 Pinky + 실물 OMX)  5:14 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:18 장면 A (실물 Pinky + 실물 OMX)  5:15 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:20 장면 A (실물 Pinky + 실물 OMX)  5:16 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:21 장면 A (실물 Pinky + 실물 OMX)  5:17 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:22 장면 A (실물 Pinky + 실물 OMX)  5:18 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:23 장면 A (실물 Pinky + 실물 OMX)  5:19 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:24 장면 A (실물 Pinky + 실물 OMX)  5:20 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:25 장면 A (실물 Pinky + 실물 OMX)  5:21 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:26 장면 A (실물 Pinky + 실물 OMX)  5:22 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:27 장면 A (실물 Pinky + 실물 OMX)  5:23 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:28 장면 A (실물 Pinky + 실물 OMX)  5:25 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:29 장면 A (실물 Pinky + 실물 OMX)  5:26 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:30 장면 A (실물 Pinky + 실물 OMX)  5:27 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:32 장면 A (실물 Pinky + 실물 OMX)  5:28 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:33 장면 A (실물 Pinky + 실물 OMX)  5:29 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 왼쪽 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:34 장면 A (실물 Pinky + 실물 OMX)  5:30 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:35 장면 A (실물 Pinky + 실물 OMX)  5:31 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:36 장면 A (실물 Pinky + 실물 OMX)  5:32 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:37 장면 A (실물 Pinky + 실물 OMX)  5:33 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:38 장면 A (실물 Pinky + 실물 OMX)  5:35 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:39 장면 A (실물 Pinky + 실물 OMX)  5:36 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:40 장면 A (실물 Pinky + 실물 OMX)  5:37 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:41 장면 A (실물 Pinky + 실물 OMX)  5:38 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:42 장면 A (실물 Pinky + 실물 OMX)  5:39 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:43 장면 A (실물 Pinky + 실물 OMX)  5:40 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:45 장면 A (실물 Pinky + 실물 OMX)  5:41 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:46 장면 A (실물 Pinky + 실물 OMX)  5:42 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 단일차선 협로(b-1) | OMX completed/done 내려놓기 completed
18:19:47 장면 A (실물 Pinky + 실물 OMX)  5:43 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:48 장면 A (실물 Pinky + 실물 OMX)  5:44 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:49 장면 A (실물 Pinky + 실물 OMX)  5:45 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:50 장면 A (실물 Pinky + 실물 OMX)  5:47 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:51 장면 A (실물 Pinky + 실물 OMX)  5:48 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:52 장면 A (실물 Pinky + 실물 OMX)  5:49 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:53 장면 A (실물 Pinky + 실물 OMX)  5:50 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:55 장면 A (실물 Pinky + 실물 OMX)  5:51 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:56 장면 A (실물 Pinky + 실물 OMX)  5:52 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:57 장면 A (실물 Pinky + 실물 OMX)  5:53 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:58 장면 A (실물 Pinky + 실물 OMX)  5:54 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:19:59 장면 A (실물 Pinky + 실물 OMX)  5:55 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:00 장면 A (실물 Pinky + 실물 OMX)  5:57 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:01 장면 A (실물 Pinky + 실물 OMX)  5:58 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:02 장면 A (실물 Pinky + 실물 OMX)  5:59 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:03 장면 A (실물 Pinky + 실물 OMX)  6:00 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:04 장면 A (실물 Pinky + 실물 OMX)  6:01 | NO 351 101호 수령 · NO 352 103호 출발 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 병실 도착 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:06 장면 A (실물 Pinky + 실물 OMX)  6:02 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:07 장면 A (실물 Pinky + 실물 OMX)  6:03 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 잠시 멈춤 103호(b-1) | OMX completed/done 내려놓기 completed
18:20:08 장면 A (실물 Pinky + 실물 OMX)  6:04 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 대기 103호 | OMX completed/done 내려놓기 completed
18:20:09 장면 A (실물 Pinky + 실물 OMX)  6:05 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 103호 | OMX completed/done 내려놓기 completed
18:20:10 장면 A (실물 Pinky + 실물 OMX)  6:06 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 103호 | OMX completed/done 내려놓기 completed
18:20:11 장면 A (실물 Pinky + 실물 OMX)  6:07 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 103호 | OMX completed/done 내려놓기 completed
18:20:12 장면 A (실물 Pinky + 실물 OMX)  6:09 | NO 351 101호 수령 · NO 352 103호 도착 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 103호 | OMX completed/done 내려놓기 completed
18:20:13 장면 A (실물 Pinky + 실물 OMX)  6:10 | NO 351 101호 수령 · NO 352 103호 수령 · NO 353 104호 수령 | 로봇: 1번 멈춤 아래 복도 ⚠unreachable · 2번 대기 아래 복도 · 3번 이동 103호 | OMX completed/done 내려놓기 completed
18:20:13 장면 A (실물) 끝 — NO 351 수령 · NO 352 수령 · NO 353 수령
```

## FMS 이벤트 (이 주문·묶음·로봇)

| seq | 시각 | 종류 | 내용 |
|---|---|---|---|
| 1 | 18:14:03 | order_created | `{"order_id": "o-1", "request_id": "emr-d351-s1-1", "room": "101호", "item": "A 약품"}` |
| 2 | 18:14:03 | order_created | `{"order_id": "o-2", "request_id": "emr-d352-s2-1", "room": "103호", "item": "B 약품"}` |
| 3 | 18:14:03 | order_created | `{"order_id": "o-3", "request_id": "emr-d353-s3-1", "room": "104호", "item": "C 약품"}` |
| 4 | 18:14:03 | batch_assigned | `{"batch_id": "b-1", "robot": 3, "name": "pinky_62f4", "orders": [{"order_id": "o-1", "room": "101호", "item": "A 약품"}, {"order_id": "o-3", "room": "104호", "item": "C 약품"}, {"order_id": "o-2", "room": "103호", "item": "B 약품"}], "count": 3, "rooms": ["101호", "104호", "103호"]}` |
| 5 | 18:14:44 | robot_called | `{"batch_id": "b-1", "robot": 3, "eta_s": 50}` |
| 6 | 18:14:44 | robot_departed | `{"robot": 3, "task": "delivery", "from": "T1_20", "to": {"node": "PHARMACY", "room": "약제실"}}` |
| 7 | 18:15:34 | robot_arrived | `{"robot": 3, "node": "PHARMACY", "room": "약제실"}` |
| 8 | 18:15:51 | robot_at_pharmacy | `{"batch_id": "b-1", "robot": 3}` |
| 9 | 18:16:07 | batch_departed | `{"batch_id": "b-1", "robot": 3, "rooms": ["101호", "104호", "103호"]}` |
| 10 | 18:16:07 | robot_departed | `{"robot": 3, "task": "delivery", "from": "PHARMACY", "to": {"node": "ROOM4_L", "room": "101호"}}` |
| 11 | 18:17:15 | robot_arrived | `{"robot": 3, "node": "ROOM4_L", "room": "101호"}` |
| 12 | 18:17:32 | order_delivered | `{"order_id": "o-1", "room": "101호", "robot": 3, "batch_id": "b-1"}` |
| 13 | 18:17:35 | robot_departed | `{"robot": 3, "task": "delivery", "from": "ROOM4_L", "to": {"node": "ROOM1_CUL", "room": "104호"}}` |
| 14 | 18:18:28 | robot_arrived | `{"robot": 3, "node": "ROOM1_CUL", "room": "104호"}` |
| 15 | 18:18:45 | order_delivered | `{"order_id": "o-3", "room": "104호", "robot": 3, "batch_id": "b-1"}` |
| 16 | 18:18:49 | robot_departed | `{"robot": 3, "task": "delivery", "from": "ROOM1_CUL", "to": {"node": "ROOM1_LU", "room": "103호"}}` |
| 17 | 18:19:46 | robot_arrived | `{"robot": 3, "node": "ROOM1_LU", "room": "103호"}` |
| 18 | 18:20:05 | order_delivered | `{"order_id": "o-2", "room": "103호", "robot": 3, "batch_id": "b-1"}` |
| 19 | 18:20:05 | batch_completed | `{"batch_id": "b-1", "robot": 3}` |

## 파일

- `scene_timeline.log` 자막 흐름 · `emr_delivery_events.tsv` EMR 배송 기록 · `emr_fms_orders.tsv` EMR → FMS 주문
- `fms_events.jsonl` FMS 이벤트 · `emr_api.log` EMR api 로그(이 시험 줄과 경고·오류)
