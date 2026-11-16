# OMX 스킬 인터페이스 설계 — LLM 플래너 + 고전 IK + 모방학습 정책 (2026-10-21)

- 상태: **설계 초안**. 코드는 아직 바꾸지 않았다. 팀이 이 문서를 맞춘 뒤 10장 순서대로 구현한다.
- 대상: `robot/src/vla_planner_robot`(OMX-F 자연어 pick & place)과 팀원의 모방학습 코드(`il` 브랜치, LeRobot).
- 사용자 결정(2026-10-21)
  - 하드웨어는 **번갈아 넘겨준다**. 학습 정책은 학습할 때와 같은 LeRobot 드라이버로 실행한다.
  - 학습 쪽 기준 코드는 **`il` 브랜치**(`eval_bi_api.py`)로 한다.

## 1. 배경과 목표

지금 `vla_planner_robot`은 이름만 VLA다. 학습된 "영상 → 동작" 모델은 들어 있지 않다.

| 역할 | 지금 맡은 것 | 학습 모델 |
|---|---|---|
| 보기 (V) | `vla_perception`: ArUco로 테이블 좌표를 잡고 HSV 색으로 블록을 찾음 (OpenCV) | 없음 |
| 판단 (L) | `vla_planner`: 명령 문장과 **블록 목록**(텍스트)을 Ollama `gemma4:e2b`에 보내 "무엇을 어디로"를 JSON으로 받음. 영상은 보내지 않음 | LLM |
| 동작 (A) | `vla_executor`: 해석적 IK와 MoveIt(Pilz PTP)으로 위에서 집기. 손목 카메라로 잡았는지 확인 | 없음 |

학습된 동작 정책은 팀원 코드에만 있다. `il` 브랜치의 SmolVLA로, 작업은 "pick and place blue gauze"이고 주로 왼팔을 쓴다. 지금은 위 구조와 연결되어 있지 않다.

**목표**
- 플래너가 **같은 규격 하나로** 고전 스킬(IK pick & place, 두 팔 운반)과 학습 스킬(거즈 옮기기)을 골라 부른다.
- 결과는 백엔드와 관계없이 **같은 방식으로 판정**한다(위쪽 카메라).
- 실패는 **오류 코드**로 돌려받아, 다시 시도할지 사람을 부를지를 코드에서 판단할 수 있게 한다.

## 2. 지금 사실 정리

### 2.1 플래너 ↔ 실행기 (`vla_planner_robot`)

- **실행기 규격은 좌표뿐이다.**
  - `vla_interfaces/action/PickPlace.action`이 받는 것: `arm`, pick/place의 x·y·yaw·z_offset, `pick_color`.
  - `CarryTogether.action`이 받는 것: 트레이 중심·yaw·길이와 놓을 곳.
  - 블록 id, 명령 문장, 놓는 방식(영역·위·옆)은 플래너 안(`llm_plan.resolve_plan`)에서 숫자로 바뀐 뒤 사라진다.
- **결과는 `success`와 자유 문장뿐이다.** 오류 코드가 없다.
  - 실행기 `_run_action`(`vla_executor/executor_node.py`)이 만드는 문장: `done`, `canceled`, 잡기 실패(`grasp check failed …`), `out of reach`, `no IK solution`, `move_group failed (error_code=N)`, `trajectory execution failed`, `gripper command failed`, `… action server not available`, `no TF …`, `unknown arm …`.
- **취소가 끝까지 전달되지 않는다.**
  - `ExecuteCommand`는 취소 요청을 받지 않는다(취소 콜백 없음).
  - 플래너 `_call`은 시간이 초과돼도 실행기 goal을 취소하지 않는다.
  - 실행기는 동작과 동작 사이에서만 취소를 확인하고, 진행 중인 MoveIt goal은 취소하지 않는다.
- **판정은 플래너가 한다.** 단계가 끝날 때마다 위쪽 카메라 `/vla/blocks`로 블록이 목표 근처에 있는지 확인하고(`_verify`, 허용 `verify_tolerance` 3 cm), 쌓기면 아래 블록이 밀리지 않았는지도 본다.
- **한 번에 goal 하나만 받는다.** 플래너와 실행기 모두 바쁘면 거절한다. 실행기는 잠금 하나로 두 팔을 함께 막는다.
- 두 팔 구성: ROS 네임스페이스는 없다. 로봇 모델 하나(`omx_dual`) 안에서 `left_`/`right_` 접두사로 구분하고, `move_group`도 하나다.
- `robot/docs/report_technical.md` §2.3의 인터페이스 표는 낡았다. `arm`, `pick_color`, `CarryTogether`, Block의 `kind/length/width`가 빠져 있다. 이 문서가 최신이다.

### 2.2 팀원 모방학습 (`il` 브랜치)

| 항목 | 내용 |
|---|---|
| 구동 | **ROS를 쓰지 않는다.** LeRobot `DynamixelMotorsBus`로 OpenRB 보드를 직접 연다(1 Mbps). 팔마다 버스가 따로 있고, 두 팔 모두 Dynamixel ID 11–16을 쓴다 |
| 정책 | SmolVLA(`SmolVLM2-500M`), chunk 50. 체크포인트 `~/main_project/outputs/train/smolvla_bi_gauze_*` |
| 입력 | 관절 12개(왼팔 6 + 오른팔 6) + 카메라 3대(`top`, `wrist_left`, `wrist_right`, 640×480) + 작업 문장 |
| 출력 | 관절 12개의 절대 목표. 단위는 라디안이 아니라 **−100..100**(그리퍼 0..100), 30 Hz |
| 작업 문장 | 데이터셋 전체에 **`"pick and place blue gauze"` 하나뿐**이다. 다른 문장은 학습 분포 밖이므로 사실상 스킬 id로 써야 한다 |
| 움직이는 팔 | `il`은 **왼팔만** 움직인다. 그래도 오른팔 버스(상태 읽기)와 카메라 3대가 모두 필요하다 |
| 끝 판단 | 시간 제한(episode_time), 외부 복귀 신호, 시작 자세 도착 중 하나. **성공인지 판정하는 기능은 없다** |
| HTTP API (`eval_bi_api.py`) | `POST /command {"command","request_id"}`(202) · `POST /return {"gripper_open","request_id"}`(202) · `GET /status` · `GET /end-point` → `{"end_point": bool}` · 끝나면 콜백 URL로 `{"end_point": …}`을 POST |
| API 규칙 | 진행 중에 다른 요청이 오면 409. 같은 `request_id`는 다시 실행하지 않는다(멱등). `--policy-path` 없이 띄우면 503. 시작 전에 `fuser`로 포트가 비었는지 확인한다 |
| `end_point` 뜻 | "시작 자세로 돌아온 것을 확인했다"는 뜻이다. **작업 성공이 아니다**(팀원 README에도 그렇게 적혀 있음) |
| 안전 | `clear_motor_errors.py`(모터 응답·전압 확인, 오류 래치 해제), `test_left_return_once.py`(설정 불일치·운전 모드·범위·하드웨어 오류가 있으면 **움직이지 않고 멈춤**, 추종 오차가 15를 넘으면 중단) |
| 실행 환경 | conda env `main_project`(torch). ROS Jazzy의 시스템 Python과 다르다 |

## 3. 설계 원칙

1. **LLM은 숫자를 내지 않는다.** 지금 규칙을 유지한다. LLM은 스킬·대상·놓을 곳·팔을 고르기만 한다.
2. **판정은 플래너 한 곳에서 한다.** 백엔드가 성공이라고 보고해도 플래너가 위쪽 카메라로 다시 확인한다.
3. **하드웨어 주인은 한 번에 하나다.** 팔 버스 2개와 카메라 3대를 ROS와 LeRobot이 동시에 열지 않는다.
4. **학습 정책은 학습할 때와 같게 실행한다.** 드라이버, 게인, 운전 모드, 카메라 노출이 같아야 한다. 그래서 ROS를 거치지 않는다.
5. **지금 동작을 깨지 않는다.** 단일 팔의 메시지·동작과 기존 테스트(`vla_planner` 26개 등)는 그대로 통과해야 한다.

## 4. 구성

```
명령 문장 ─▶ vla_planner ──run_skill (action)──▶ vla_skills 스킬 서버
              │  LLM: 스킬·대상·놓을 곳·팔 고르기        │
              │  resolve_plan: 숫자 계산                  ├─ 고전 백엔드 ──▶ vla_executor  pick_place / carry_together (지금 그대로)
              │                                          │
              │                                          ├─ 학습 백엔드 ──HTTP──▶ eval_bi_api (conda, 별도 프로세스) ──▶ 팔·카메라 직접
              │                                          │
              │                                          └─ 하드웨어 관리자: 모드 ROS ⇄ LEARNED 전환
              │                                               (ros2_control·카메라·인식 내리기/올리기, 포트 비었는지 확인)
              └──◀── 결과(오류 코드) ──┘   판정: /vla/blocks (위쪽 카메라)
```

- **새 패키지 `vla_skills`**(ament_python)를 둔다. 스킬 목록, 백엔드 선택, 하드웨어 전환, 오류 코드 변환을 맡는다.
- **`vla_executor`는 고치지 않고 감싼다.** 스킬 서버가 지금의 `pick_place`·`carry_together` action을 부른다.
- **학습 백엔드는 팀원 `eval_bi_api`를 그대로 HTTP로 부른다.** 우리 쪽 프로세스에서 torch를 쓰지 않으므로 conda와 ROS가 섞이지 않는다.

## 5. 인터페이스 규격 (초안)

### 5.1 `vla_interfaces/action/RunSkill.action`

```
# 스킬 하나 실행. 고전 스킬은 geometry를, 학습 스킬은 task를 쓴다.
string request_id        # 단계마다 새 값. 재시도할 때는 같은 값 (멱등, eval_bi_api와 같은 규칙)
string skill             # skills.yaml의 id: pick_place | carry | gauze_to_box ...
string arm               # left | right | "" (고전: 지금 PickPlace.arm과 같음)
string target_id         # 대상 물체 id (기록·판정용, 예: red_0). 학습 스킬은 ""
string task              # 학습 스킬에 보낼 문장. 플래너가 skills.yaml의 고정 문장을 넣는다
float64 timeout_s        # 0 = skills.yaml 기본값
SkillGeometry geometry   # 고전 스킬용 숫자 (학습 스킬은 비워 둠)
---
bool success
string error_code        # 5.3 표. 성공이면 ""
string message           # 사람이 읽는 설명 (지금 문장 유지)
string backend           # classical | learned
float64 duration_s
---
string stage             # 지금 PickPlace 피드백과 같은 단계 문장
float32 progress         # 0..1, 모르면 -1
```

### 5.2 `vla_interfaces/msg/SkillGeometry.msg`와 `srv/ListSkills.srv`

- `SkillGeometry.msg`
  - 지금 `PickPlace.action` goal의 필드를 그대로 옮긴다: `pick_x/y/yaw/z_offset`, `pick_color`, `place_x/y/yaw/z_offset`.
  - 두 팔 운반을 위해 `tray_x/y/yaw/length`를 더한다.
  - 고전 백엔드는 이 값으로 지금 goal을 그대로 만든다.
- `ListSkills.srv`
  - 요청은 비어 있다.
  - 응답은 스킬마다 `id`, `backend`, `description`(LLM 프롬프트용 한 줄), `arms`, `needs_target`(bool)를 준다.
  - 플래너가 시작할 때 불러 LLM 스키마의 `skill` enum과 프롬프트 설명을 만든다.

### 5.3 오류 코드

| 코드 | 뜻 | 지금 실행기 문장 / 출처 | 플래너 처리(제안) |
|---|---|---|---|
| `CANCELED` | 취소됨 | `canceled` | 멈춤 |
| `TIMEOUT` | 시간 초과 | 플래너 `_call` → None | 하위 goal 취소 후 멈춤 |
| `BUSY` | 다른 goal 진행 중 | goal 거절, API 409 | 잠시 뒤 1회 재시도 |
| `INVALID_GOAL` | 모르는 스킬·팔, 필드 누락 | `unknown arm …`, `two-arm carry needs two arms` | 멈춤(버그) |
| `OUT_OF_REACH` | 닿지 않음 | `out of reach (r=…)`, `no arm reaches both …` | 멈춤 |
| `NO_IK` | IK 해 없음 | `no IK solution for …` | 멈춤 |
| `MOTION_FAILED` | MoveIt 계획·실행 실패 | `move_group failed`, `trajectory execution failed` | 1회 재시도 |
| `GRASP_FAILED` | 손목 카메라 잡기 확인 실패 | `… grasp check failed …` (복구 동작 후) | 장면을 다시 보고 1회 재시도 |
| `HW_ERROR` | 모터 오류·전압·그리퍼 | `gripper command failed`, 학습 쪽 `Motor hardware errors` | 멈춤 + 사람 확인 |
| `HW_HANDOVER_FAILED` | ROS ⇄ LeRobot 전환 실패(포트·카메라가 안 풀림, 재기동 실패) | 새로 생김 | 멈춤 + 사람 확인 (**자동 재시도 안 함**) |
| `BACKEND_UNAVAILABLE` | action 서버나 `eval_bi_api`에 연결 안 됨, 503 | `… action server not available`, `no TF …` | 멈춤 |
| `PRECONDITION_FAILED` | 설정 불일치, 시작 자세 아님 | 학습 쪽 `Calibration mismatch`, `Unexpected operating mode` | 멈춤 + 사람 확인 |
| `VERIFY_FAILED` | 백엔드는 성공이라 했는데 카메라로 보니 아님 | 플래너 `_verify` | 멈춤 (플래너가 붙이는 코드) |

- 처음에는 고전 백엔드가 지금 문장을 위 표대로 코드로 바꾼다(문장 앞부분으로 구분).
- 그다음 단계에서 `PickPlace` 결과에 `error_code`를 직접 넣는다. 이때 기존 필드는 그대로 두고 필드를 더하기만 한다.

### 5.4 스킬 목록 `vla_skills/config/skills.yaml` (예)

```yaml
skills:
  pick_place:
    backend: classical
    description: "블록 하나를 집어 다른 곳(영역·블록 위·옆)에 놓는다"
    arms: [left, right, ""]
    needs_target: true
    timeout_s: 180
  carry:
    backend: classical
    description: "트레이를 두 팔로 함께 들어 옮긴다"
    arms: [""]
    needs_target: true
    timeout_s: 300
  gauze_to_box:
    backend: learned
    description: "왼쪽 더미의 파란 거즈 하나를 가운데 검은 상자에 넣는다"
    arms: [left]
    needs_target: false
    task: "pick and place blue gauze"       # 학습 데이터의 문장 그대로. 바꾸면 분포 밖
    api_url: http://127.0.0.1:8100          # eval_bi_api 주소 (포트는 정할 것)
    timeout_s: 60                           # 정책 episode_time + 복귀
    verify: region                          # 8장
```

## 6. LLM 계획 형식 변경

- `llm_plan.build_schema`의 step에 `skill`을 더한다. enum은 `ListSkills`에서 받은 id이고 기본값은 `pick_place`다.
- 학습 스킬은 `pick`·`place`를 `none`으로 둔다. `resolve_plan`은 학습 스킬 단계를 숫자로 바꾸지 않고 그대로 넘긴다.
- **사용자 문장을 정책에 보내지 않는다.** 정책에는 `skills.yaml`의 `task` 문장을 보낸다. 학습 데이터에 문장이 하나뿐이어서, 다른 문장은 동작을 예측할 수 없다.
- 프롬프트에 스킬 설명 한 줄씩과 예시 하나를 넣는다.
  - 예: "거즈 상자에 넣어줘" → `{"skill":"gauze_to_box","pick":"none","place":"none"}`
- 학습 스킬과 고전 스킬을 한 명령 안에서 섞을 수 있다. 다만 섞으면 단계마다 하드웨어 전환(7장)이 생기므로 시간이 늘어난다.

## 7. 하드웨어 넘겨주기 (ROS ⇄ LEARNED)

### 7.1 왜 전환이 필요한가

- **팔 시리얼은 동시에 못 연다.** ROBOTIS `dynamixel_hardware_interface`는 ros2_control이 살아 있는 동안 버스를 계속 연다. LeRobot도 같은 OpenRB 보드를 연다. 한 버스에 마스터가 둘이면 서로 패킷을 깨뜨린다.
- **비활성화로는 포트가 안 풀린다.** `dynamixel_hardware_interface.cpp`를 보면 포트는 `on_init`(`InitDxlComm`)에서 열린다. `on_deactivate`는 `stop()`만 부르고 포트를 닫지 않는다. 그래서 **ros2_control을 띄운 프로세스 자체를 끝내야** 한다.
- **카메라도 하나의 프로세스만 연다.** 위쪽 카메라(SNAP U2)와 손목 카메라를 우리 카메라 노드와 LeRobot이 같이 쓴다.

### 7.2 순서

```
ROS 모드 (MoveIt·카메라·인식 켜짐)
 1. 고전 goal이 없는지 확인 (실행기 idle)
 2. 팔을 관측 자세로 → 정책 시작 자세와 가까운지 확인 (il 시작 자세 ≈ ROBOTIS 접힌 자세)
 3. 내리기: ros2_control·로봇 bringup 프로세스, 카메라 노드 (인식 노드는 입력만 끊김)
 4. 확인: fuser로 팔 포트 2개 + 카메라 3대가 비었는지 확인 (안 비면 HW_HANDOVER_FAILED)
LEARNED 모드
 5. POST /command {command: <skills.yaml task>, request_id}
 6. GET /status를 1초마다 확인 (콜백도 받을 수 있음) → state: completed | failed
    취소·시간 초과 → POST /return {gripper_open: true} → 시작 자세로 복귀
 7. 정책 쪽이 시작 자세로 돌아온 뒤 토크를 끄고 연결을 닫는다 (il 동작)
ROS 모드로 돌아가기
 8. ros2_control·bringup 다시 띄움 (init_position:=false → 지금 자세에서 시작)
 9. 카메라·인식 다시 띄움 → table_calibrated == true, /vla/blocks가 새로 들어올 때까지 대기
10. 판정 (8장) → RunSkill 결과
```

- 스킬 서버는 3·8·9단계의 launch 프로세스를 자식 프로세스로 관리한다. 지금 `vla_bringup`의 "이전 실행이 남아 있으면 시작 거부" 규칙(`VLA_ALLOW_RUNNING`)과 맞춰야 한다.
- 전환에 걸리는 시간은 아직 모른다. 0단계 실측에서 잰다.

### 7.3 위험과 대책

| 위험 | 내용 | 대책 |
|---|---|---|
| **모터 설정 덮어쓰기** | LeRobot `OmxFollower.connect()`는 기본값이 `calibrate=True`다. 모터 설정이 저장된 calibration JSON(오프셋 0, 범위 0..4095, Drive Mode 0)과 다르면 **물어보지 않고** 운전 모드·Drive Mode 0·범위 0..4095를 모터에 다시 쓴다. ROBOTIS는 Drive Mode 4와 위치 제한(예: ID12 830–3129)을 쓰므로, ROS를 쓴 다음에는 항상 불일치가 나고 **관절 제한이 지워진다** | 학습 백엔드는 다시 쓰지 말고 **거부**해야 한다. `test_left_return_once.py`처럼 불일치면 `PRECONDITION_FAILED`로 멈춘다. 그러려면 둘 중 하나가 필요하다: ① 정책 서버가 `connect(calibrate=False)`로 연결하고 직접 검사, ② ROBOTIS 값과 맞는 calibration JSON. 팀원과 정한다 |
| 운전 모드·게인 차이 | LeRobot은 몸 관절 모드 4, 팔꿈치 P1500/D600, 프로파일 없음. ROBOTIS는 ID11 모드 4, 나머지 모드 3, P1000/D1000, 시간 프로파일(속도 50/가속 25), 그리퍼 전류 제한 600. 마지막에 연결한 쪽 설정으로 움직인다 | 양쪽 모두 연결할 때마다 자기 설정을 다시 쓰는지 0단계에서 확인한다. 확인될 때까지는 전환 직후 첫 동작을 느리게 한다 |
| 토크 해제 | 정책이 끝나면 토크를 꺼서 팔이 처진다 | il처럼 시작 자세로 돌아온 다음 끈다. ROS는 `init_position:=false`로 지금 자세에서 시작한다 |
| 장치 이름 | 팀원 udev(`99-omx.rules`)는 `/dev/omx_follower_left` 등 고정 이름을 쓴다. 이 PC의 `/etc/udev/rules.d/99-omx.rules`는 다른 한 쌍에 대한 규칙이고, 리더 시리얼이 `vla_teleop/config/arms.yaml`과 뒤바뀌어 있다 | 규칙 하나로 통일하고, ROS(`left_port`/`right_port`)와 LeRobot이 같은 이름을 쓰게 한다 |
| 단위 | LeRobot −100..100 ↔ ROS 라디안. 오프셋 0, 영점 raw 2048이라면 `rad ≈ n·π/100`(추정) | 판정에는 쓰지 않지만 자세 비교(2단계)에 필요하다. 실물에서 부호와 값을 잰다 |

## 8. 판정

- **고전 스킬**: 지금 `_verify`(블록이 목표 근처에 있는지, 쌓기면 아래 블록이 밀리지 않았는지)를 그대로 쓴다.
- **학습 스킬(거즈)**: 지금 인식은 블록 색만 찾아서 거즈를 판정할 수 없다.
  - 제안: `vla_perception`에 **영역 판정**을 더한다. `skills.yaml`에 상자 영역을 table 좌표로 적고, 스킬 전후의 거즈 색 픽셀 비율 변화로 판단한다.
  - 영역 판정이 생기기 전에는 플래너가 "정책은 끝났고 시작 자세로 돌아왔으나 성공 여부는 모름(미확인)"으로 `ExecuteCommand` 결과에 적는다. 이 경우 다음 단계로 넘어가지 않고 멈춘다.
- 판정은 스킬 서버가 아니라 플래너가 한다. 그래서 `RunSkill` 결과에는 판정 필드를 두지 않고, 실패는 플래너가 `VERIFY_FAILED`로 붙인다.

## 9. 취소와 안전

- `ExecuteCommand`에 취소를 받게 한다. 취소는 **진행 중인 `RunSkill` 하나에** 전달된다.
- `RunSkill`이 취소되면 백엔드별로 이렇게 멈춘다.
  - 고전: 진행 중인 MoveIt goal까지 취소한다. 지금은 동작 사이에서만 멈춘다.
  - 학습: `POST /return`으로 시작 자세 복귀를 시킨다. 정책 루프는 다음 추론 전에 멈춘다(il의 `should_return`).
- 플래너는 시간이 초과되면 하위 goal을 **반드시 취소**한다. 지금은 취소하지 않는다.
- 전환(7장) 중의 실패는 `HW_HANDOVER_FAILED`로 처리한다. 자동으로 다시 시도하지 않고 사람이 확인한다. 팔이 처진 채 ROS가 다시 붙는 일을 막기 위해서다.
- 모터 오류와 전압 확인(`clear_motor_errors.py`)은 학습 스킬을 시작하기 전마다 돌린다. il의 preflight가 이 일을 한다.

## 10. 단계 계획

| 단계 | 내용 | 확인 방법 |
|---|---|---|
| 0. 실측 (실물, 팀원과) | ① ros2_control 프로세스를 끝내면 포트가 풀리는지(`fuser`) ② ROS → LeRobot → ROS로 번갈아 쓴 뒤 모터 설정(Drive Mode·제한·모드·게인)이 어떻게 바뀌는지 ③ 단위·부호 ④ 전환에 걸리는 시간 | 결과를 이 문서에 적는다 |
| 1. 인터페이스 + 고전 백엔드 | `RunSkill`·`SkillGeometry`·`ListSkills`, `vla_skills` 스킬 서버(고전만), 문장 → 오류 코드 변환 | 단위 테스트, 시뮬에서 지금과 같은 결과 |
| 2. 플래너가 `run_skill` 사용 | 오류 코드에 따른 처리, 취소 전달, 시간 초과 때 하위 goal 취소 | 기존 테스트 26개 + 새 테스트, 시뮬 |
| 3. 학습 백엔드 + 하드웨어 관리자 | HTTP 클라이언트, 전환 절차(7.2). 가짜 **`eval_bi_api`** 서버와 가짜 launch로 시험 | 단위·통합 테스트(도메인 77) |
| 4. LLM 스키마 `skill` | `build_schema`·프롬프트·`resolve_plan` 처리 | 플래너 테스트, Ollama 실제 호출 |
| 5. 실물 시험 | 거즈 스킬 1회 → 고전 pick & place 1회를 번갈아 | 영상 + 모터 설정 기록 |

## 11. 열린 질문

1. **모터 설정 덮어쓰기**를 어떻게 막을지 팀원과 정한다(7.3 표 첫 줄, ①과 ② 중 선택).
2. **실물 두 팔**: U2D2(또는 OpenRB) 두 개가 필요하다. 두 팔 모두 ID 11–16이다. ROBOTIS `omx_f_system` 하드웨어 이름 충돌은 `robot/CLAUDE.md` open items에 있다.
3. 정책은 왼팔만 움직이지만 **오른팔 버스와 카메라 3대가 모두 필요**하다. 그동안 오른팔 고전 스킬은 쓸 수 없다.
4. **거즈 판정** 방법: 영역 판정이면 되는지, 상자 모양과 위치를 고정할 수 있는지.
5. **GPU 16 GB**에 Ollama(gemma4:e2b, 약 4.6 GB)와 SmolVLA를 같이 올려도 되는지. 정책 서버를 이 PC에서 돌릴지.
6. 학습 데이터에서 정책이 출발·멈추는 조건: [모방학습 데이터셋 점검](il_dataset_review/README.md). 가져오는 곳이 적으면 "가만히"를 배웠을 수 있어서, 시작 조건 검사와 진행 감시(몇 초 안에 움직임이 없으면 `/return`)가 필요하다.
7. `eval_bi_api`의 포트 번호와 콜백 주소, 그리고 정책 서버를 늘 띄워 둘지 스킬을 쓸 때만 띄울지.

## 근거 (코드 위치)

- `robot/src/vla_planner_robot/vla_interfaces/action/{PickPlace,CarryTogether,ExecuteCommand}.action`, `msg/Block*.msg`
- `robot/src/vla_planner_robot/vla_planner/vla_planner/planner_node.py`: `run_command`, `_call`, `_verify`
- `robot/src/vla_planner_robot/vla_planner/vla_planner/llm_plan.py`: `build_schema`, `ask_ollama`, `resolve_plan`
- `robot/src/vla_planner_robot/vla_executor/vla_executor/executor_node.py`: `_run_action`, `run_pick_place`, `run_carry`
- `robot/src/dynamixel_hardware_interface/src/dynamixel_hardware_interface.cpp`: `on_init`(`InitDxlComm`), `on_deactivate` → `stop()`
- `robot/src/open_manipulator/open_manipulator_description/ros2_control/omx_f.ros2_control.xacro`: Drive Mode 4, 위치 제한, 게인, 프로파일
- `il` 브랜치: `eval_bi_api.py`, `eval_bi.py`, `test_left_return_once.py`, `check_start_pose.py`, `lerobot_robot_bi_omx/…/bi_omx.py`
- LeRobot v0.4.4 `robots/omx_follower/omx_follower.py`: `connect(calibrate=True)`, `calibrate()`
