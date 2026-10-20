# 저장소 올리기 전 검증 보고서 (2026-10-20)

- 대상: `https://github.com/kernel-robot-9th/kernel-robot-repo-2.git`, `main` 브랜치에 dev_ws를 처음 올린다.
- 목적: 올라가는 코드가 **어디까지 확인됐고 어디부터 확인되지 않았는지** 팀이 알고 쓰게 한다.
- 검증 수준 표기
  - **단위**: pytest 같은 자동 테스트(가짜 객체 사용).
  - **통합**: 실제 프로세스끼리 연결해 확인. ROS는 Claude 시험 도메인 77, 가짜 Nav2·가짜 카메라로 확인했다.
  - **실스택**: 상시 기동 중인 EMR(docker)과 실제 화면에서 확인.
  - **실물**: 실제 Pinky·OMX에서 확인.

## 1. 요약

| 영역 | 단위 | 통합 | 실스택 | 실물 | 판단 |
|---|---|---|---|---|---|
| EMR 백엔드 (배송 배정·진행·일회용 마커·알림) | ✅ 101개 통과 | ✅ 동시 claim | ✅ | — | 올려도 됨 |
| EMR 프론트 | ⚠️ 테스트 없음 | — | ✅ 화면 확인 | — | 올려도 됨 (단위 테스트 없음) |
| 관제 PC 배송 실행기 `delivery_executor` | ✅ 18 | ✅ 도메인 77 + 가짜 Nav2 | ✅ 실제 EMR | ❌ | 실물 시험 전 |
| 간호사 따라가기 `pinky_marker` | ✅ 13 | ✅ 가짜 카메라 | — | ❌ | 실물 시험 전 (옵션 기능) |
| 관제 모니터 `robot_monitor` | ✅ 4 | — | — | ✅ 실제 Pinky 읽음 | 올려도 됨 |
| 시험용 이동 `test_waypoint` | ✅ 12 | — | ✅ | ✅ 비품실 1회 | 올려도 됨 (시험용) |
| OMX-F VLA (`vla_*`) | ✅ 52 | ✅ 시뮬 (이전 작업) | — | ⚠️ 1팔 일부 | 기존 상태 그대로 |
| 로컬 LLM `ollama_ws` | — | ✅ 플래너 형식 호출 | ✅ 이 PC | — | 올려도 됨 |
| 새로 받기 → 전체 빌드 | ✅ 37개 패키지 | | | | conda를 끄면 됨 |

**결론**: 코드는 단위 테스트, 통합 테스트, 실스택에서 확인됐다. **실물 로봇에서 배송을 끝까지 해 보는 시험은 아직 안 했다.** README와 각 문서에 이 상태를 적어 두었으므로 `main`에 올려도 된다고 판단한다. 실제로 올리는 것은 사용자 승인 뒤에 한다.

## 2. 원격 저장소 상태

| 브랜치 | 커밋 | 내용 | 이번 작업 |
|---|---|---|---|
| `main` | `84d9120 Initial commit` | README 2줄 + Python 템플릿 `.gitignore` | 이 위에 커밋 1개를 올린다(fast-forward, 강제 푸시 아님) |
| `jaewoo` | `71cb7e4` | `omx_bimanual_il/` 팀원 모방학습 22개 파일 | **건드리지 않음** |

- 원격 `.gitignore`는 우리 `gitignore.txt` 앞 220줄과 같다. 올릴 때 `gitignore.txt`를 `.gitignore`로 바꿔 덮어쓴다. 원격 파일에 줄이 더해지는 것이므로 기존 규칙은 그대로 남는다.

## 3. 올라가는 파일

| 위치 | 파일 수 |
|---|---|
| `emr/` | 174 |
| `robot/` | 296 |
| `docs/` | 6 (이 보고서 포함) |
| `ollama_ws/` | 3 |
| 루트 (`README.md`, `LICENSE`, `.gitignore`) | 3 |
| **합계** | **482**, 약 41 MB. 가장 큰 파일은 1.5 MB(`robot/docs/test_report_dual.pdf`)이고 5 MB를 넘는 파일은 없다 |

**올리지 않는 것** (`.gitignore`):

- 비밀값: `.env`, `*.key`, `*.pem`, `settings.local.json`, DB 덤프.
- 빌드 산출물: `robot/build`, `robot/install`, `robot/log`. 이 폴더들에는 셸 환경변수가 평문으로 남아 있다.
- `node_modules`, 시험 영상 `*.mp4`.
- `CLAUDE.md`, `.claude/`.
- 외부 패키지 4개. 대신 README 부록 A의 `git clone` + 고정 커밋으로 받는다.

### 3.1 비밀값 검사

| 검사 | 결과 |
|---|---|
| Google API 키(`AIza…`), 실제 로봇 키(`emr_rk_…`), 개인 키, 토큰 | 없음 |
| `JWT_SECRET` | `.env.example`의 자리표시자만 있음 |
| 개발용 비밀번호 `nurse1234` | 9개 파일(시드·문서). **개발용**이다. 운영 전에 바꾼다(`emr/README.md` 운영 배포 전 체크) |
| 사설 IP `192.168.x` | 5개 파일(문서·설정). 내부망 주소라 그대로 둔다 |
| 개인 경로 `/home/fastcamp1` | 1개 파일(`docs/server_report_2026-10-19.md`). 서버 현황 기록이라 그대로 둔다 |

### 3.2 라이선스

- `LICENSE`: All rights reserved(커널아카데미 로보틱스 심화 캠프 9기 2팀).
- 우리 패키지 `package.xml` 13개와 `setup.py` 8개를 Proprietary로 바꿨다.
- `vla_dual_moveit_config`는 ROBOTIS 원본과 같은 설정 파일 3개가 들어 있어 Proprietary와 Apache-2.0을 함께 적었다.
- 외부 패키지(Apache-2.0)는 저장소에 넣지 않는다.

## 4. 영역별 검증 내용

### 4.1 EMR 웹 (`emr/`)

- **백엔드**
  - `pytest -q`: 101개 통과.
  - 마이그레이션은 `0008_delivery_dispatch`(head)이고 `alembic check` 결과 차이가 없다.
  - 빈 임시 DB에서 0001 → 0008 upgrade, 0007로 downgrade, 다시 upgrade를 확인했다. 결과는 head이고 `alembic check`에서 차이가 없다. 임시 DB는 지웠다.
  - 새 상태의 행이 있으면 downgrade를 멈추는 코드가 있다. 이 경우는 시험하지 않았다.
- **실스택** (상시 기동 중인 docker)
  - `simulate_robot.py`로 예약 → 출발 → 도착(일회용 마커 창) → 수령 / 미수령 실패(재고 복구)를 확인했다.
  - 흉내 로봇 2개가 동시에 claim하면 한 배송이 한 로봇에만 간다(`FOR UPDATE SKIP LOCKED`).
  - 알림: 출발·도착·수령은 예약한 간호사에게, 실패는 예약한 간호사와 관리자에게 간다.
  - 화면에 띄운 마커를 OpenCV로 읽어 131번이 나왔고, 이는 배정된 번호와 같다.
- **프론트**
  - `typecheck`, `lint`(경고 0), `build`가 모두 통과한다.
  - **프론트 단위 테스트는 없다.** 화면 확인은 수동으로 했다(스크린샷).
- **알려진 제한**
  - 출발한 배송은 간호사가 취소할 수 없다.
  - 관리자가 배송을 강제로 실패시키는 기능이 없다.
  - 로봇 상태 화면(로드맵 3단계)이 없다.
  - 자세한 내용은 `docs/api_contract_delivery_2026-10-20.md` 7장에 있다.

### 4.2 로봇 — Pinky AMR·관제 (`robot/src/fms`, `robot/src/pinky_onboard`)

| 패키지 | 확인한 것 | 확인 안 된 것 |
|---|---|---|
| `delivery_executor` | 단위 18개. 실제 EMR + 도메인 77 + 가짜 Nav2에서 다음 세 경우를 확인했다: 수령 성공, 금지 장소면 바로 실패, 주행 중에 멈추면 `dispatched`로 남았다가 다시 켜면 이어서 진행 | **실물 Pinky 배송 종단 시험**. 비품실 모방학습이 끝난 뒤에 한다. 지금은 설정에 `blocked_location_ids: [1]`(비품실)이 들어 있다 |
| 수령 마커 읽기 | 실행기가 `receipt_marker`(Int32) 토픽을 받는 부분 | **카메라로 마커를 읽어 토픽에 발행하는 노드가 아직 없다.** 지금은 사람이 `ros2 topic pub`로 대신한다 |
| `pinky_marker` (간호사 따라가기, 옵션) | 단위 13개. 가짜 카메라로 따라가기 → 놓침 → Nav2 주행 중 멈춤 → 끄기·켜기 → SIGINT 종료까지 확인. 끈 상태에서는 `cmd_vel`이 0개다 | Pi 카메라 노드를 실물에서 확인하지 않았다. 실물 주행도 하지 않았다 |
| `robot_monitor` | 단위 4개. 실제 Pinky(도메인 0)를 읽었다(배터리 45%) | 관제 화면이 없다 |
| `test_waypoint` | 단위 12개. 실물 Pinky가 EMR 장소 좌표로 비품실까지 1회 주행에 성공했다 | 시험용이다. 배송 상태와는 무관하다 |

### 4.3 OMX 로봇팔 (`robot/src/vla_planner_robot`)

- 단위 테스트: `vla_planner` 26, `vla_perception` 4, `vla_executor` 5, `vla_calibration` 8, `vla_teleop` 9.
- `vla_calibration`은 `install/setup.bash`를 source해야 테스트가 통과한다. `robot/CLAUDE.md`의 명령 순서를 따르면 된다.
- 이번 작업에서는 OMX 코드를 바꾸지 않았다(라이선스 표기만 바꿈).
- 실물 상태는 이전 문서(`robot/docs/`)와 같다. 1팔 실물은 일부만 시험했고, 2팔 실물은 시험하지 않았다. 캘리브레이션 결과(`calib/`)는 아직 없다.

### 4.4 로컬 LLM (`ollama_ws/`)

- `./setup_ollama.sh`가 이 PC에서 통과했다(exit 0).
  - Ollama 0.40.1, `ollama.service` active, `gemma4:e2b` 있음.
  - 확인 방식: `check_ollama.py`가 플래너와 같은 형식으로 요청한다(`/api/chat`, `stream:false`, enum JSON 스키마, temperature 0).
- 결과
  - 한국어 명령은 20.7초 걸렸다. 첫 요청이라 모델을 올리는 시간이 들어 있다.
  - 영어 명령은 1.2초 걸렸다.
  - 둘 다 스키마에 맞는 답을 돌려줬다.
- 다른 PC에서 Ollama를 설치하는 부분(`--install`)은 시험하지 않았다. 이 PC에는 이미 설치되어 있다.

### 4.5 새로 받은 사람처럼 전체 빌드

다른 사람이 저장소를 새로 받는 경우를 흉내 냈다.

- **방법**: 올라갈 파일만 빈 폴더에 복사했다. README 부록 A의 명령으로 외부 패키지 4개를 받은 뒤 다음을 했다.
  - `rosdep check`: 빠진 의존성이 없다.
  - `colcon build`: **37개 패키지 모두 빌드, 134초.**
  - 우리 패키지 테스트: 모두 통과.
- **주의 1**: conda(anaconda)가 PATH에 있으면 `pinky_gz_sim`이 protobuf 버전 충돌로 실패한다. conda를 끄면 된다. README "시작하기"에 이 내용과 `-DPython3_EXECUTABLE=/usr/bin/python3`를 적어 두었다.
- **주의 2**: 메모리가 15 GB이면 `--parallel-workers 2`를 지켜야 한다.

## 5. 아직 확인되지 않은 것 (올린 뒤 할 일)

1. **실물 Pinky 배송 종단 시험**: 비품실 모방학습이 끝난 뒤에 한다. 순서는 다음과 같다.
   - 로봇 1번에 키를 발급하고, 복귀 장소를 간호사스테이션으로 정한다.
   - 301호 배송을 보내 수령까지 확인한다.
   - 미수령(5분) 배송을 보내 실패와 재고 복구, 복귀까지 확인한다.
2. **수령 마커 카메라 노드**: `DICT_4X4_250`을 검출해 `receipt_marker`로 발행하는 노드를 만든다.
3. 간호사 따라가기를 실물 카메라와 실제 주행으로 시험한다.
4. 로봇 상태 화면(EMR 로드맵 3단계)을 만든다.
5. 프론트 단위 테스트를 만든다(지금은 없음).
6. OMX 실물 캘리브레이션을 하고 2팔을 시험한다.

## 6. 올리는 절차 (승인 뒤)

1. 원격 `main`을 임시 폴더에 clone한다.
2. 위 482개 파일을 복사한다. `gitignore.txt`는 `.gitignore`로 이름을 바꿔 덮어쓴다.
3. `git status`로 다음을 다시 확인한다.
   - 비밀값 파일, `build/`, `install/`, `log/`, `CLAUDE.md`, `.claude/`가 없는지.
   - 외부 패키지 4개 폴더가 없는지.
4. 커밋을 1개 만들고 `git push origin main`으로 올린다. fast-forward로 올라가며 강제 푸시는 하지 않는다. `jaewoo` 브랜치는 건드리지 않는다.
5. 올린 뒤 GitHub에서 README 렌더링(mermaid 그림)과 파일 수를 확인한다.
