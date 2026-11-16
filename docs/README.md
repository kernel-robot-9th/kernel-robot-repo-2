# 문서 목차

문서 이름의 날짜는 작성한 날입니다. 최종 구조는 [아키텍처](architecture/README.md)를 먼저 보세요.

## 설계

| 문서 | 내용 |
|---|---|
| [SW 아키텍처 (최종판)](architecture/README.md) | 전체 구성도, 계층, 모듈 사이 인터페이스, 모듈별 파일, 계획과 다르게 만든 것, 한계 |
| [기술 스택 그림](tech_stack/tech_stack_2026-11-02.png) | 모듈별 사용 기술 한 장 |
| [Pinky 여러 대 운영 구조](pinky_multi_robot_2026-10-20.md) | 다중 로봇 운영 제안(초기) |
| [OMX 스킬 인터페이스](omx_skill_interface_2026-10-21.md) | LLM 플래너 + IK + 모방학습 설계 초안(구현 전) |
| [VLA 플래너 기술 검증](../robot/docs/vla_planner_tech_validation_2026-10-26.md) | 별도 과제 정리 |

## API · 인터페이스

| 문서 | 내용 |
|---|---|
| [배송 API 계약](api_contract_delivery_2026-10-20.md) | EMR ↔ 로봇 쪽 상태·엔드포인트·오류 코드, 병상 단말(8장), **FMS API v1·OMX(10장)** |
| [FMS API v1](../fms/API.md) · [Pinky REST API](../driving/api/API.md) | FMS와 Pinky 원본 명세 |
| [EMR ↔ FMS 인터페이스 분석](fms_emr_interface_2026-10-27.md) · [FMS가 쓰는 EMR API](fms_emr_api_2026-10-27.md) | FMS API v1 연동 분석 |
| [AMR / OMX 연동 인터페이스](robot_access_amr_omx_2026-10-27.md) · [OMX 완료 신호](omx_end_point_spec_2026-10-26.md) | 로봇 쪽 인터페이스 |
| [EMR ↔ 로봇 데이터 양식과 화면](emr_robot_data_format/README.md) | 실측 요청·응답과 기능별 화면 |
| [FMS v1 뒤 필요 없어진 API](emr_unused_apis_fms_v1_2026-10-27.md) · [예전 팀원 연동 안내](emr_robot_api_for_teammate_2026-10-22.md) | 예전 claim 방식(쓰지 않음) |

## 시험 · 검증

| 문서 | 내용 |
|---|---|
| [실물 Pinky 3대 동시 배송 (11-02)](scenarios/logs/2026-11-02_real/demo3_163314/summary.md) | 5회, 30건 중 29건 수령 |
| [시나리오 ① 여러 병동 묶음](scenarios/scenario_01_multiward_batch_2026-10-30.md) · [시나리오 ② 1분 5건 부하](scenarios/scenario_02_load_5per_min_2026-10-30.md) | 10-30 시뮬레이션·실물 시험 |
| [시험 로그 폴더](scenarios/logs/) | 10-30 시뮬·실물, 11-02 실물 원본 기록 |
| [모방학습 데이터셋 점검](il_dataset_review/README.md) | IL 대신 YOLO + 클릭 픽으로 바꾼 근거 |
| [음성 성능 비교 근거](voice_performance_basis_2026-10-26.md) | 음성 인식·합성 비교 방법 |
| [올리기 전 검증 보고서](verification_report_2026-10-20.md) | 첫 업로드 점검 |

## 화면 · 발표

| 문서 | 내용 |
|---|---|
| [EMR 대표 화면 5장 + 영상](emr_screens/README.md) | 배송 목록, 수령, 지도, 병상 단말, 배송 기록 |
| [아레나 평면도](arena_floorplan/) | 병원 지도 배경 |

## 운영

| 문서 | 내용 |
|---|---|
| [서버 안내](server_guide.md) | 서버 한 대 전체 구성: 포트, 실행 순서, 문제 해결 |
| [서버 현황 보고서](server_report_2026-10-19.md) | 초기 서버 상태 |

## 개발 기록

| 문서 | 내용 |
|---|---|
| [개발 경과](history/README.md) | 날짜별 흐름, 예전 아키텍처 판, 옮긴 상태표 |
| [EMR 개발 이슈·문제 해결](emr_dev_issues_2026-10-23.md) | 진행도, 해결한 문제, 남은 문제 |
| [EMR 트러블 이슈 2건](emr_issues_receipt_and_schedule_2026-11-03.md) | 수령 방법, 예약 시각 여유 |
| [FMS·OMX 연동 작업 정리](emr_fms_omx_integration_2026-10-27.md) | 10-27 결정·API·시험·남은 일 |
| [EMR 진행 현황 (10-21)](emr_status_2026-10-21.md) · [EMR 음성 기능](voice_emr_2026-10-26.md) | 당시 상태 |
| [Pinky 분석](pinky_analysis_2026-10-20.md) · [팀원 Pinky API 분석](pinky_fms_api_review_2026-10-22.md) | 로봇 쪽 실측과 연동 제안 |
| [노션용 계약 사본](notion/api_contract_delivery_2026-10-20.notion.md) | 노션 붙여 넣기용 |
