# VLA 플래너 기술 검증 정리 (2026-10-26)

- 대상: OMX-F 로봇팔 **자연어 pick & place** (`robot/src/vla_planner_robot`)
- 성격: **기술 검증 과제**. 병원 배송 시스템(EMR·Pinky·팀원 OMX 모방학습)과는 연동하지 않고 따로 검증한다.
- 방향 전환(2026-10-26): 물체 인식을 **색(HSV) → AI 비전**으로 바꿔 다음 검증을 한다(5장).

## 1. 검증 목표

| 질문 | 검증 방법 |
|---|---|
| 한국어 명령을 로봇 동작으로 바꿀 수 있나 | 로컬 LLM(Ollama `gemma4:e2b`)이 명령을 단계 계획으로 |
| LLM이 틀린 숫자를 만들지 않게 할 수 있나 | LLM은 **고르기만**(JSON 스키마 enum), 좌표·높이·도달 검사는 코드가 |
| 카메라만으로 물체 위치를 잡을 수 있나 | 탑뷰 RGB(깊이 없음) + 호모그래피로 테이블 좌표 |
| 집기·놓기·쌓기·두 팔 협동이 되나 | 시뮬(1팔·2팔) → 실물 오른팔 |
| 결과를 스스로 확인할 수 있나 | 손목 카메라(집었나), 탑뷰(제자리에 놓였나) |

## 2. 구조

```
탑뷰 카메라 ─▶ 인식 ─────────────────▶ 플래너 ──────────────────────────▶ 실행기 ─────────────▶ 팔
              PerceptionNode             PlannerNode                         PickPlaceExecutor     시뮬: MoveIt(Pilz PTP)
              HSV 색 분할 → 윤곽선         ask_ollama(gemma4:e2b, temp 0)       top_down_ik(해석해)    실물: 관절 궤적 직접
              호모그래피 → x·y·yaw·크기    build_schema(요청마다 enum)          집기 → 손목 확인        (safe_z_min 검사)
              /vla/blocks (BlockArray)    resolve_plan(좌표·검증·팔 배정)       → 놓기 → 관찰
                                          /execute_command, /vla/command
                    ▲                                                               │
                    └──────── 단계마다 탑뷰로 결과 확인(_verify, 3 cm 안) ◀───────────┘
```

| 단계 | 파일 | 하는 일 |
|---|---|---|
| 인식 | `vla_perception/perception_node.py`, `table_geometry.py` | 시뮬은 ArUco `DICT_5X5_100` 0–3으로, 실물은 `calib/top_homography.yaml`로 픽셀→테이블 좌표. HSV 색 분할 → `blob_pose_on_table`(x, y, yaw, 크기, 높이 시차 보정) |
| 계획 | `vla_planner/llm_plan.py`, `planner_node.py`, `cli.py` | LLM이 pick 블록 id, place 기호(영역 9개·`on_top:<id>`·`{left,right,front,back}_of:<id>`), 팔(auto/left/right), `feasible`을 고름. 최대 4단계. `resolve_plan`이 좌표·쌓기 높이·도달·충돌·전달 지점(7.5 mm 격자)·트레이 손잡이를 계산 |
| 실행 | `vla_executor/executor_node.py`, `omx_ik.py`, `grasp_check.py` | 열기 → 접근 → (선택) 손목 정렬 → 집기 → 들기 → 손목 영상으로 집었는지 → 놓기 → 물러남 → 관찰. 두 팔 트레이 운반(`run_carry`) |
| 인터페이스 | `vla_interfaces` | msg `Block`·`BlockArray`, action `PickPlace`·`CarryTogether`·`ExecuteCommand` |
| 실행 묶음 | `vla_bringup` | `sim_vla`(1팔) · `dual_sim_vla`(2팔) · `real_vla`(실물 오른팔) launch, `stop_vla.sh` |
| 실물 도구 | `vla_calibration`, `vla_teleop` | 탑뷰 내부 파라미터·호모그래피, 손목 보정(`wrist_refine`) / 텔레옵(리더-팔로워, 카메라 고정) |

되는 명령 예: "빨간 블록을 가운데로 옮겨", "파란 블록을 노란 블록 위에 쌓아줘", "왼팔로 노란 블록을 왼쪽 앞으로", "빨간 블록을 오른쪽으로"(한 팔로 안 되면 두 팔 전달 자동), "그릇을 두 팔로 들어서 뒤로", "노란 블록을 그릇에 넣어". 없는 블록·범위 밖·충돌·이미 위에 블록 있음은 거부한다.

## 3. 검증 결과

| 환경 | 결과 | 근거 |
|---|---|---|
| 시뮬 1팔 | 옮기기·쌓기 동작, 쌓기 8/9, 놓기 편향 약 (−4, −3) mm | `docs/report_technical.md` §9 |
| 시뮬 2팔 | 전달·협동 운반 동작. 운반 5번 중 1번 원인 모를 실패, 3번 기울기 5° 초과 | `robot/CLAUDE.md` Open items |
| 실물 — 인식·계획만 (10-19) | 탑뷰 한 장 → 색·마커 검출 → LLM 대상 선택 → 픽셀 좌표 성공(어두운 영상 포함). 팔은 안 움직임 | `docs/real_tests/2026-10-19_topview_llm` |
| 실물 — 텔레옵 집기 (10-20) | 집기 2회 성공, 쌓기 실패(약 2 cm 어긋남) | `docs/real_tests/2026-10-20_floor_markers` |
| **실물 — 명령 쌓기 (10-22)** | "파랑 블록을 초록 블록에 쌓아" **12번 시도, 성공 0번**. LLM 계획은 매번 맞음(`blue_0 → on_top:green_0`), 실패는 **전부 집기 단계** | `docs/real_tests/2026-10-22_command/failures.md` |

10-22 실패 원인:

| # | 원인 | 성격 |
|---|---|---|
| ① | 손목 기준 픽셀을 잘못된 높이(8 cm, 실제 5 cm)에서 읽음 | 캘리브레이션 |
| ② | 손목 카메라에 탑뷰용 HSV(파랑 V≥180) → 블록이 조각으로 잡혀 중심 6–9 cm 틀림 | **색 인식** |
| ③ | 블록이 팔 끝 거리(0.25–0.26 m) — IK 범위 끝, 0.24 m에서 관절2 2.8° 처짐(끝 13 mm 낮음) | 배치·기구 |
| ④ | 탑뷰가 x≈0.22에서 실제보다 약 3 cm 짧게 봄 | 캘리브레이션 |
| ⑤ | 런치 직후 `no recent /vla/blocks` | 원인 모름 |

검증된 것과 안 된 것:
- **검증됨**: LLM은 고르기만 하고 숫자는 코드가 — 실물에서도 계획은 한 번도 틀리지 않았다. 시뮬에서 계획 → 실행 → 확인 고리 전체.
- **안 됨**: 실물 집기. 원인은 계획이 아니라 **인식(색)과 캘리브레이션·팔 범위**.

## 4. 한계 (지금 구조)

- **색(HSV) 인식**: 조명·반사·카메라마다 기준을 다시 맞춰야 하고(탑뷰·손목 따로), 색이 없는 물체나 같은 색 여러 개(id가 바뀜)에 약하다.
- **깊이 없음**: 탑뷰 RGB라 쌓은 높이는 플래너 기억에만 의존한다.
- **캘리브레이션**: 탑뷰 호모그래피 검증 평균 4.5 mm(최대 5.5)이지만 x≈0.22에서 3 cm 차이. 손목 보정 측정점 0개(`calib/wrist_points.csv` 비어 있음, `wrist_refine fit` 안 함).
- **팔 범위**: 수직 하향 IK라 0.12–0.27 m, 끝 쪽은 처짐이 커진다.
- **설정 불일치**: `failures.md`에 17:20 바꿨다는 값(`surface_plane` a=−0.0054, `safe_z_min` −0.01, `grasp_z` 0.015)과 지금 `config/executor_real.yaml`(−0.0354, −0.04, 0.0113)이 다르다 — 다음 실물 시험 전에 맞출 것.

## 5. 방향 전환 — AI 비전

**바꿀 곳은 인식 한 군데**다. 좌표 변환·자세 계산·LLM 계획·IK·확인 고리는 그대로 쓴다.

| 부분 | 지금 | AI 비전 |
|---|---|---|
| 탑뷰 물체 찾기 | `table_geometry.color_blobs()` HSV | 분할 모델(YOLO-seg 등) 또는 글자로 찾는 모델(YOLO-World + SAM) → 마스크 → 윤곽선 |
| 자세·좌표 | `blob_pose_on_table()` + 호모그래피 | **그대로** (마스크 윤곽선을 넣으면 x·y·yaw·크기) |
| `Block` 메시지 | `color`로 이름 | 클래스 이름을 `color`/`kind`에 대응(필요하면 `label` 칸) |
| LLM 계획 | id·이름 중에서 고름 | **그대로** (프롬프트의 물체 이름만 맞춤) |
| 손목 확인·정렬 | `grasp_check` HSV 비율 | 같은 모델로 손목 영상 검출(①② 원인 해소) |
| 시뮬 | 색 블록 HSV | HSV 유지(실물만 AI 비전) — `detector: hsv \| yolo` 설정 |

환경: 이 PC `/usr/bin/python3`에 ultralytics 8.4.159, CUDA torch(RTX 5080)가 있다.

검증 순서(제안):
1. **오프라인**: 저장된 실물 탑뷰·손목 사진(`docs/real_tests/`)으로 검출률·중심 오차를 HSV와 비교 — 팔 안 움직임
2. 모델 선택: 학습 없이(YOLO-World + SAM) 먼저 보고, 부족하면 실물 사진 100–300장 라벨링 → YOLO-seg 학습
3. `perception_node`에 AI 비전 검출기 추가(설정으로 HSV와 교체), `/vla/blocks`가 같은 형식으로 나오는지
4. 캘리브레이션 마무리(손목 5–6점 `wrist_refine fit`, 탑뷰 x≈0.22 차이), 블록은 0.22 m 안쪽
5. 실물 집기 → 쌓기 재시험(10-22와 같은 명령으로 비교)

AI 비전이 풀어 주는 것은 ②와 같은 **인식 문제**다. ①③④(캘리브레이션·팔 범위)는 따로 풀어야 실물 집기가 된다.

## 6. 남은 문제

| # | 문제 | 비고 |
|---|---|---|
| 1 | 실물 집기 성공 없음 | 5장 순서로 재검증 |
| 2 | 손목 보정 측정 0점, 탑뷰 x≈0.22 3 cm | 캘리브레이션 |
| 3 | 실물 설정값과 실패 기록 불일치 | 4장 |
| 4 | 런치 직후 `/vla/blocks` 안 옴 | 원인 조사 |
| 5 | 실물 2팔: U2D2 2개 필요(두 팔 모두 ID 11–16), ROBOTIS 서비스 이름 충돌 | 하드웨어 |
| 6 | 실측 필요: 두 팔 간격(0.33 가정), 보드 앞 모서리(0.06), 실제 그릇 | |
| 7 | 2팔 운반 불안정(1/5 실패, 3/5 기울기 >5°), 전달 구역 좁음(y≈0, x 0.10–0.17 m) | 시뮬 |
| 8 | 문서: `report_technical.md` §1.3 테스트 수(43, 지금 51)·§2.3 인터페이스 표가 예전 것, `report_visual.pdf`에 2팔 없음 | |

## 7. 실행·테스트

```bash
deactivate 2>/dev/null; conda deactivate 2>/dev/null
source /opt/ros/jazzy/setup.bash && cd ~/dev_ws/robot && source install/setup.bash
ros2 run vla_bringup stop_vla.sh                                    # 항상 먼저
ros2 launch vla_bringup sim_vla.launch.py                           # 시뮬 1팔 (2팔: dual_sim_vla, 실물 오른팔: real_vla)
ros2 run vla_planner cli                                            # 한국어 명령
```

테스트 51개(`src/vla_planner_robot/`에서): planner 26 · perception 4 · executor 7 · calibration 8(`install/setup.bash` 필요) · teleop 6. 명령은 `robot/CLAUDE.md` Commands.

## 8. 관련 문서

- `robot/README.md` 9장(실물), `robot/docs/report_technical.md`(기술 보고서), `robot/docs/calibration/README.md`
- `robot/docs/real_tests/`(10-19 · 10-20 · 10-22 실물 시험 기록)
- 참고(별도 과제): `docs/omx_skill_interface_2026-10-21.md`(고전 IK와 모방학습 정책을 같은 규격으로 — 설계 초안), `docs/il_dataset_review/`(팀원 모방학습 데이터 점검)
