# 문서 목차

`docs/`에는 **시스템 전체**에 관한 문서(구조, 기술, 아키텍처, 모듈 사이 계약, 통합 시험)만 둡니다.
모듈 하나에 관한 문서는 그 모듈 폴더에 있습니다. 최종 구조는 [아키텍처](architecture/README.md)를 먼저 보세요.

## 설계 · 아키텍처

| 문서 | 내용 |
|---|---|
| [SW 아키텍처 (최종판)](architecture/README.md) | 전체 구성도, 계층, 모듈 사이 인터페이스, 모듈별 파일, 설계 결정, 한계 |
| [기술 스택 그림](tech_stack/tech_stack_2026-11-02.png) | 모듈별 사용 기술 한 장 |
| [Pinky 여러 대 운영 구조](pinky_multi_robot_2026-10-20.md) | 다중 로봇 운영 제안(초기) |
| [OMX 스킬 인터페이스](history/omx_skill_interface_2026-10-21.md) | LLM 플래너 + IK + 모방학습 설계 초안(구현 전) |

## 모듈 사이 계약

| 문서 | 내용 |
|---|---|
| [배송 API 계약](api_contract_delivery_2026-10-20.md) | EMR ↔ 로봇 쪽 상태·엔드포인트·오류 코드, 병상 단말(8장), **FMS API v1·OMX(10장)** |
| [노션용 계약 사본](notion/api_contract_delivery_2026-10-20.notion.md) | 노션 붙여 넣기용 |
| [FMS API v1](../fms/API.md) · [Pinky REST API](../driving/api/API.md) | FMS와 Pinky 원본 명세 |

## 통합 시험

| 문서 | 내용 |
|---|---|
| [실물 Pinky 3대 동시 배송 (11-02)](scenarios/logs/2026-11-02_real/demo3_163314/summary.md) | 5회, 30건 중 29건 수령 |
| [시나리오 ① 여러 병동 묶음](scenarios/scenario_01_multiward_batch_2026-10-30.md) · [시나리오 ② 1분 5건 부하](scenarios/scenario_02_load_5per_min_2026-10-30.md) | 10-30 시뮬레이션·실물 시험 |
| [시험 로그 폴더](scenarios/logs/) | 10-30 시뮬·실물, 11-02 실물 원본 기록 |
| [모방학습 데이터셋 점검](history/il_dataset_review/README.md) | OMX를 IL 대신 YOLO + 클릭 픽으로 바꾼 근거 |
| [올리기 전 검증 보고서](verification_report_2026-10-20.md) | 첫 업로드 점검 |

## 운영

| 문서 | 내용 |
|---|---|
| [서버 안내](server_guide.md) | 서버 한 대 전체 구성: 포트, 실행 순서, 문제 해결 |
| [서버 현황 보고서](server_report_2026-10-19.md) | 초기 서버 상태 |
| [개발 경과](history/README.md) | 날짜별 흐름, 예전 아키텍처 판 |

## 모듈별 문서

| 모듈 | 문서 |
|---|---|
| EMR 웹 | [emr/docs/](../emr/docs/README.md): 개발 이슈, FMS·OMX 연동, 음성, 화면, 데이터 형식 |
| FMS | [fms/README.md](../fms/README.md) · [FMS 설계](../fms/docs/pinky_fms_design_2026-10-26.md) |
| Pinky 주행 | [driving/README.md](../driving/README.md) |
| OMX 로봇팔 | [omx/README.md](../omx/README.md) |
| 탑뷰 감시 | [topview/README.md](../topview/README.md) |
| 안내 로봇 | [guide_robot/README.md](../guide_robot/README.md) |
| VLA 플래너 | [robot/README.md](../robot/README.md) · [기술 검증](../robot/docs/vla_planner_tech_validation_2026-10-26.md) |
