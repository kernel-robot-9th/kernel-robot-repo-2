# 개발 경과

대문(README)과 아키텍처 문서는 최종 결과만 보여 줍니다. 개발하면서 바뀐 결정, 그 시점의 상태표, 예전 그림은 이 폴더에 보관합니다.

## 날짜별 흐름

| 날짜 | 일 | 자료 |
|---|---|---|
| 10-08 | 저장소 시작 | |
| 10-20 | 첫 업로드: EMR 웹, 관제 PC 배송 실행기, OMX-F VLA, 로컬 LLM 준비. 배송 API 계약 초안 | [API 계약](../api_contract_delivery_2026-10-20.md) · [올리기 전 검증](../verification_report_2026-10-20.md) |
| 10-21 | SW 아키텍처 초안(Lv.1 블록도 기준). 모방학습(IL) 데이터셋 점검 | [10-21판 PDF](architecture_2026-10-21.pdf) · [IL 점검](../il_dataset_review/README.md) |
| 10-22 | "받았습니다" 버튼 수령, 병상 단말 환자 요청 | [이슈 정리](../emr_issues_receipt_and_schedule_2026-11-03.md) |
| 10-23 | 관제 PC 배송 실행기 삭제, 팀원 Pinky API를 직접 쓰는 쪽으로 | [EMR 개발 이슈](../emr_dev_issues_2026-10-23.md) |
| 10-26 | OMX를 YOLO + 클릭 픽으로 바꿈(IL 대신). EMR 음성 신청 | [음성 정리](../voice_emr_2026-10-26.md) · [OMX 완료 신호](../omx_end_point_spec_2026-10-26.md) |
| 10-27 | **FMS API v1 확정**: EMR = 상위 관제, 배차는 FMS. FMS 묶음마다 OMX 적재 | [연동 정리](../emr_fms_omx_integration_2026-10-27.md) |
| 10-29 | 팀원 `fms`·`driving` 브랜치 병합. 실제 Pinky 연결, 실측 엣지 시간 | [10-29판 아키텍처](architecture_2026-10-29.md) |
| 10-30 | 결정: 수령은 버튼으로 확정, 응급 상황 감지 뺌(RealSense → 일반 카메라), 시연 중 인증 끔. 여러 병동 신청, 부하 시험 | [시나리오 ①](../scenarios/scenario_01_multiward_batch_2026-10-30.md) · [시나리오 ②](../scenarios/scenario_02_load_5per_min_2026-10-30.md) |
| 11-02 | **실물 Pinky 3대 동시 배송 5회, 30건 중 29건 수령**(OMX 가상). FMS 경로 계획 고도화(ECBS, 약제실 앞 대기열). 탑뷰 사람 감지, OMX 양팔 v2, 안내 로봇 | [시험 로그](../scenarios/logs/2026-11-02_real/demo3_163314/summary.md) |
| 11-04 | FMS 이상 동작 감지기, v5(비키기·차례 충돌 수정), 발표 화면 | [fms/README](../../fms/README.md) |
| 11-16 | **모든 브랜치를 main으로 통합**: `vision` → `omx/`, `gstream` → `topview/`, `guide_robot` → `guide_robot/`. 커밋 이력 보존 | |

## 보관한 자료

| 파일 | 내용 |
|---|---|
| [architecture_2026-10-29.md](architecture_2026-10-29.md) | 10-29 아키텍처 문서 원본. 10-21·10-26·10-27판에서 바뀐 것, 블록별 구현 상태 집계, 예전 방식(로봇이 배송을 가져가는 claim, EMR이 Pinky 상태를 직접 묻기) 설명이 들어 있음 |
| [sw_3layer_2026-10-29.png](sw_3layer_2026-10-29.png) · [.mmd](sw_3layer_2026-10-29.mmd) | 10-29 3계층 그림(구현 / 일부 / 없음 / 팀원 담당 색 구분) |
| [architecture_2026-10-21.pdf](architecture_2026-10-21.pdf) | 10-21 초안(관제 PC 배송 실행기 기준) |

## README에서 옮긴 상태표 (2026-10-29 기준)

| 기능 | 상태 |
|---|---|
| EMR 물품·신청·지도·장소·로봇·알림·배송 기록·음성 신청 | 완료 |
| 병상 단말 환자 요청·"받았습니다" 수령 | 완료 |
| EMR ⇄ 팀원 FMS (API v1) | 완료 — 주문 보내기, 이벤트로 준비·출발·도착·실패(10-29 '준비' 단계 추가). FMS 시뮬레이터로 신청 → 도착 확인(10-27) |
| 병원 지도 위 로봇 위치 | 완료(10-29) — FMS가 1초마다 보내는 위치를 아레나 평면도 위에 표시 |
| EMR ⇄ 팀원 OMX | 완료 — FMS 묶음마다 집기 → `ready` → 정밀 주차 뒤 내려놓기 → `loaded`. **시뮬레이터 Pinky + 실물 OMX로 신청 → 도착 확인**(10-27, 임시 문장 형식) |
| FMS ↔ 실제 Pinky | 팀원 코드 병합(10-29) — FMS가 Pinky API `/drive`·`/action`으로 실제 로봇을 움직이고, 경로 계획에 실측 엣지 시간을 씀. 관제 PC 도커로 기동 |
| 남은 연동 | 팀원 OMX가 개수 형식 `{"blue": N, "green": N}` 받기, FMS 다시 시작 대응, 취소 연동, FMS `robot_error`·`order_failed` 처리, `ready`·`loaded` 시간 초과 |
| 시험용 설정 | 로그인·로봇 키 검사를 잠시 꺼 둠 — 운영 전에 켜기 ([EMR 이슈 정리](../emr_dev_issues_2026-10-23.md) 3장) |

이후 바뀐 것: OMX 개수 형식은 `omx/eval_bi_api_yolo_botharm_v2.py`가 받습니다. FMS `order_failed`는 EMR이 처리합니다(`fms_events.py`). FMS 재시작 대응, 취소 연동, 시간 초과는 남은 한계로 [아키텍처 6장](../architecture/README.md#6-알려진-한계)에 적었습니다.
