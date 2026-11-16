# EMR 문서

EMR 웹(`emr/`)의 개발 기록, 연동 분석, 화면 자료입니다. 시스템 전체 구조와 모듈 사이 계약은 [docs/](../../docs/README.md)에 있습니다.

## 연동 (EMR ↔ FMS · OMX · Pinky)

| 문서 | 내용 |
|---|---|
| [FMS·OMX 연동 작업 정리](emr_fms_omx_integration_2026-10-27.md) | 10-27 결정·API·시험·남은 일 |
| [EMR ↔ FMS 인터페이스 분석](fms_emr_interface_2026-10-27.md) · [FMS가 쓰는 EMR API](fms_emr_api_2026-10-27.md) | FMS API v1 연동 분석 |
| [AMR / OMX 연동 인터페이스](robot_access_amr_omx_2026-10-27.md) · [OMX 완료 신호](omx_end_point_spec_2026-10-26.md) | 로봇 쪽 인터페이스 |
| [EMR ↔ 로봇 데이터 양식과 화면](emr_robot_data_format/README.md) | 실측 요청·응답과 기능별 화면 |
| [Pinky 분석](pinky_analysis_2026-10-20.md) · [팀원 Pinky API 분석](pinky_fms_api_review_2026-10-22.md) | 로봇 쪽 실측과 연동 제안 |
| [FMS v1 뒤 필요 없어진 API](emr_unused_apis_fms_v1_2026-10-27.md) · [예전 팀원 연동 안내](emr_robot_api_for_teammate_2026-10-22.md) | 예전 claim 방식(쓰지 않음) |

## 개발 기록

| 문서 | 내용 |
|---|---|
| [EMR 개발 이슈·문제 해결](emr_dev_issues_2026-10-23.md) | 진행도, 해결한 문제, 남은 문제 |
| [EMR 트러블 이슈 2건](emr_issues_receipt_and_schedule_2026-11-03.md) | 수령 방법, 예약 시각 여유 |
| [EMR 진행 현황 (10-21)](emr_status_2026-10-21.md) ([PDF](emr_status_2026-10-21.pdf)) | 당시 상태 |

## 음성

| 문서 | 내용 |
|---|---|
| [EMR 음성 기능](voice_emr_2026-10-26.md) | 말로 신청, 안내 음성 |
| [음성 성능 비교 근거](voice_performance_basis_2026-10-26.md) | 음성 인식·합성 비교 방법 |

## 화면 · 자료

| 자료 | 내용 |
|---|---|
| [EMR 대표 화면 5장 + 영상](emr_screens/README.md) | 배송 목록, 수령, 지도, 병상 단말, 배송 기록 |
| [아레나 평면도](arena_floorplan/) | 병원 지도 배경 (`backend/scripts/make_arena_floorplan.py`로 만듦) |
