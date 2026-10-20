# kernel-robot-repo-2 — OMX 모방학습 (`il` 브랜치)

커널아카데미 로보틱스 심화 캠프 9기 2팀, 지능형 의료서비스로봇 헬퍼 시스템.

OMX 양팔 데이터(관절 12개 + 카메라 3대)를 수집하고 ACT/SmolVLA를 학습하는 코드입니다.
현재 Python 평가·API는 **왼쪽 follower만 제어**합니다. 오른쪽 관절은 양팔 모델의 입력을 유지하기 위해 읽기만 합니다.

[기존 jaewoo 문서](https://github.com/kernel-robot-9th/kernel-robot-repo-2/tree/jaewoo/omx_bimanual_il)를 바탕으로,
`il` 브랜치의 실제 코드를 확인해 노출, 마스킹, 카메라 이름 변환, 복귀 및 API 사용법을 정리했습니다.

## 실행 환경과 설치 전 확인

- conda 환경: `main_project`
- 작업 경로: `~/main_project`
- LeRobot 소스: `~/il_ws/src/lerobot` (현재 코드가 대상으로 하는 버전: v0.4.4, OMX 지원 포함)
- 플러그인: `lerobot_robot_bi_omx` (`bi_omx_follower`, `bi_omx_leader`)
- 장치 확인 도구: `v4l2-ctl`, `fuser`
- 체크포인트와 녹화 데이터는 이 저장소에 포함되지 않습니다.

이 브랜치는 Python·shell 파일만 업로드한 구성입니다. **`pyproject.toml`, `99-omx.rules`, `omx-cam-side`는 포함되지 않았습니다.**
새 PC에서는 기존 환경 또는 [jaewoo의 설치 파일](https://github.com/kernel-robot-9th/kernel-robot-repo-2/tree/jaewoo/omx_bimanual_il)을 준비해야 합니다.
플러그인 폴더에 해당 `pyproject.toml`을 배치한 뒤 설치하세요. 장치 규칙의 시리얼 번호는 실제 보드/카메라에 맞춰야 합니다.
이미 설치된 작업 PC라면 이 과정을 다시 수행할 필요가 없습니다.

```bash
conda activate main_project
# OMX 지원이 들어 있는 기존 LeRobot 소스에서 실행
cd ~/il_ws/src/lerobot
pip install -e '.[dynamixel,smolvla]'

cd ~/main_project
# pyproject.toml을 준비한 뒤 실행
pip install -e ./lerobot_robot_bi_omx
pip install fastapi uvicorn httpx
```

스크립트에는 위 경로가 직접 들어 있습니다. 다른 위치에서 사용할 때는 경로를 수정해야 합니다.

## 카메라 매핑 — 녹화 이름과 SmolVLA 이름

| 물리 카메라 | 장치 경로 | 녹화/ACT 이름 | SmolVLA 학습·추론 이름 |
|---|---|---|---|
| 위쪽 top | `/dev/cam_top` | `top` | **`camera1`** |
| 왼쪽 손목 | `/dev/cam_wrist_left` | `wrist_left` | **`camera2`** |
| 오른쪽 손목 | `/dev/cam_wrist` | `wrist_right` | **`camera3`** |

기본 영상 설정은 640×480, 30 FPS, MJPG입니다. `camera1`은 USB 장치 번호가 아니라 **모델 입력 키**입니다.
오른쪽 손목의 장치 경로는 `/dev/cam_wrist_right`가 아니라 `/dev/cam_wrist`입니다.

[train_bi.sh](train_bi.sh)의 SmolVLA `--rename_map`은 다음과 같습니다.

```json
{
  "observation.images.top": "observation.images.camera1",
  "observation.images.wrist_left": "observation.images.camera2",
  "observation.images.wrist_right": "observation.images.camera3"
}
```

- 녹화 파일은 `top`, `wrist_left`, `wrist_right` 이름으로 저장합니다.
- `POLICY=smolvla` 학습에서만 위 매핑을 전달합니다. 원본 데이터셋 파일 이름을 직접 바꾸는 작업은 아닙니다.
- [eval_bi.sh](eval_bi.sh)는 `POLICY=smolvla`이면 카메라를 처음부터 `camera1/2/3` 키로 구성합니다.
- [eval_bi.py](eval_bi.py)는 체크포인트 종류와 `--cam-keys auto`를 사용해 같은 매핑을 적용합니다. API도 이를 재사용합니다.
- 사용자 지정 `--cam-keys`는 **top, 왼쪽 wrist, 오른쪽 wrist** 순서의 쉼표 구분 문자열입니다.
- 왼쪽만 움직이더라도 현재 모델 입력에는 오른쪽 관절 및 카메라 3대가 필요합니다.

## 주요 파일과 제어 범위

| 파일 | 기능 / 대상 |
|---|---|
| [teleop_bi.sh](teleop_bi.sh) | 양팔 leader/follower 텔레옵 + 카메라 3대 |
| [record_bi.sh](record_bi.sh) | 양팔 데이터 수집, HF 로그인 시 private 데이터셋 업로드 |
| [train_bi.sh](train_bi.sh) | ACT 또는 SmolVLA 학습 |
| [train_group.sh](train_group.sh) | 사전 정의한 마스킹/증강 실험 6개를 순차 실행 |
| [eval_bi.sh](eval_bi.sh) | **양팔 제어**, 평가 데이터셋 저장, 이번에 추가한 두 단계 복귀 기능 없음 |
| [eval_bi.py](eval_bi.py) | **왼쪽만 제어**, 평가 데이터 저장 없음, 경유 자세 → 시작 자세 복귀 |
| [eval_bi_api.py](eval_bi_api.py) | HTTP command 수신 → Python 평가 → 복귀 → 완료 결과 전송 |
| [test_left_return_once.py](test_left_return_once.py) | 모델 없이 왼쪽 복귀 1회, 각 구간 6초, 완료 후 토크 OFF |
| [set_top_exposure.sh](set_top_exposure.sh) | top 카메라 스트리밍 시작 후 수동 노출 적용 |
| [clear_motor_errors.py](clear_motor_errors.py) | 모터 오류 점검/해제. 읽기 전용 측정 도구가 아님 |
| [masking/](masking/) | 학습 영상 마스킹·통계 재계산 등 전처리 |

## 노출과 마스킹 옵션

| 기능 | Shell 실행 | Python / API 실행 | 기본 동작 |
|---|---|---|---|
| top 수동 노출 | `TOP_EXPOSURE=90` | `--top-exposure 90` | 생략하면 자동 노출 |
| top 마스킹 | `TOP_MASK=1` (`eval_bi.sh`) | `--top-mask` | 생략하면 원본 영상 |
| 마스크 유지 영역 | shell 평가에는 고정 | `--top-mask-roi 0 200 400 480` | `[0, 200, 400, 480]` |
| 증강 모델 경로 | `OUT_SUFFIX=_aug` | `--policy-path`로 직접 선택 | suffix 없음 |
| 이미지 증강 학습 | `AUGMENT=1` (`train_bi.sh`) | 해당 없음 | 기본 비활성 |

Python 옵션은 `--top_mask`가 아니라 **`--top-mask`**입니다. ROI 옵션만 지정해도 마스킹이 켜지는 것은 아니므로 `--top-mask`를 함께 사용하세요.
Shell의 `TOP_MASK`와 `AUGMENT`는 값이 비어 있지 않으면 활성화됩니다. 따라서 `TOP_MASK=0`도 활성화되며, 끄려면 변수를 unset해야 합니다.

### 노출

`TOP_EXPOSURE`는 `record_bi.sh`, `teleop_bi.sh`, `eval_bi.sh`에서 사용합니다.
Python/API에서는 환경변수 대신 `--top-exposure`를 전달합니다.
`set_top_exposure.sh`는 카메라가 열릴 때까지 기다린 뒤 `auto_exposure=1`, `exposure_time_absolute=90`을 적용합니다.
스트림 시작 시 카메라 설정이 초기화되는 문제 때문에 시작 이후에 적용하는 방식입니다.
`90`은 이 카메라 드라이버에 전달하는 설정값이며 임의의 밀리초 값으로 해석하지 않습니다.

**녹화 당시 노출과 평가 노출을 맞추세요.** 학습 스크립트는 저장된 영상을 읽으므로 `train_bi.sh`에 `TOP_EXPOSURE=90`을 붙여도 기존 영상의 노출이 바뀌지 않습니다.

### 마스킹

[플러그인의 mask_rois](lerobot_robot_bi_omx/lerobot_robot_bi_omx/bi_omx.py)는 top 영상에서 다음 영역만 남기고 밖을 검게 만듭니다.

```text
x: 0 <= x < 400
y: 200 <= y < 480
```

영상을 crop/resize하지 않고 원래 크기를 유지합니다. 손목 영상 두 개에는 이 top 마스크가 적용되지 않습니다.
SmolVLA에서는 `camera1`, ACT 기본 이름에서는 `top` 키에 적용됩니다.

학습 데이터에 같은 마스크를 적용하려면 원본과 별도 목적지 경로를 지정합니다.

```bash
conda activate main_project
cd ~/main_project
python masking/mask_dataset_stream.py \
  ~/.cache/huggingface/lerobot/OWNER/DATASET \
  ~/.cache/huggingface/lerobot/OWNER/DATASET_masked \
  top 0 200 400 480
```

`OWNER`, `DATASET`은 실제 값으로 바꾸세요. `SRC`와 `DST`는 서로 다른 경로여야 합니다.
이 도구는 영상을 순차 처리하고 통계를 재계산하며, 목적지의 `.masked_files`로 처리 기록을 관리합니다.
위 예시는 녹화 원본 키가 `top`인 데이터 기준입니다. 이미 이름을 바꾼 데이터는 실제 영상 키를 확인하세요.
`train_bi.sh` 자체가 마스킹을 수행하지는 않습니다. 전처리한 데이터셋으로 학습하고 추론에서 `--top-mask`/`TOP_MASK=1`을 켜야 합니다.
`record_bi.sh`에는 top 마스킹 옵션이 연결되어 있지 않습니다.

## 데이터 수집과 학습

```bash
cd ~/main_project
TOP_EXPOSURE=90 EPISODE_TIME=30 RESET_TIME=15 \
  bash record_bi.sh bi_gauze_one_exposure 'pick and place blue gauze' 5

HF_USER=YOUR_HF_USER POLICY=smolvla BATCH_SIZE=16 SAVE_FREQ=2000 \
  bash train_bi.sh bi_gauze_one_exposure 30000

# 마스킹 전처리가 끝난 데이터셋을 증강하여 학습하는 예시
HF_USER=YOUR_HF_USER POLICY=smolvla AUGMENT=1 OUT_SUFFIX=_aug \
  bash train_bi.sh bi_gauze_one_exposure_masked 30000
```

`HF_USER`는 실제 데이터셋 소유자에 맞춥니다. 로컬 데이터라면 `HF_USER=local`을 사용합니다.
학습 출력은 `outputs/train/${POLICY}_${NAME}${OUT_SUFFIX}`입니다.
SmolVLA의 평가 task는 학습에 사용한 문장과 맞춥니다.

## 왼쪽 follower 평가와 복귀

```bash
conda activate main_project
cd ~/main_project
python eval_bi.py \
  --policy-path ~/main_project/outputs/train/smolvla_bi_gauze_v2/checkpoints/last/pretrained_model \
  --task 'pick and place blue gauze' \
  --episode-time 30 --top-exposure 90 \
  --return-via-time 6 --return-home-time 6
```

이 예시는 마스크 없는 모델 기준입니다. 마스킹 데이터로 학습한 체크포인트를 사용할 때만 `--top-mask`를 추가하세요.
이름에 `v2`가 있다는 이유만으로 마스크 적용 여부를 자동 판정하지 않습니다.

- 기본값으로 작업 PC에서 측정한 **왼쪽 경유/시작 자세**가 코드에 들어 있습니다. 다른 로봇의 공통 home 값이 아닙니다.
- `--return-via`, `--start-pose`는 각각 왼쪽 6개 값이며 둘을 함께 지정해 덮어씁니다.
- 순서: `shoulder_pan shoulder_lift elbow_flex wrist_flex wrist_roll gripper`.
- 단위: 몸체 관절 `-100..100`, 그리퍼 `0..100`의 LeRobot 정규화 값. degree/radian이 아닙니다.
- Python 복귀 시간 기본값은 **구간당 2초**입니다. 위 명령은 느린 확인을 위해 명시적으로 6초로 설정했습니다.
- 각 자세 도착을 허용 오차 안에서 3회 연속 확인합니다. 기본 허용 오차 2, 구간 종료 후 도착 대기 3초입니다.
- 평가 시간이 끝나면 경유 자세 → 시작 자세로 복귀합니다. `--no-return`이면 자동 복귀를 끕니다.
- 정상 종료 후 왼쪽 토크를 끕니다. 오른쪽 위치/토크는 변경하지 않습니다.
- Python/API에는 그리퍼 개방을 자동 판정하는 검출기가 아직 없습니다. 외부 신호를 연결해야 합니다.
- 관절 보간은 충돌 회피 계획이 아니며, 개방부터 명령 전송까지 0.4초를 보장하지 않습니다.

## FastAPI: command → task → 모델 실행 → 완료 전송

### 서버 실행

```bash
conda activate main_project
cd ~/main_project
python eval_bi_api.py \
  --policy-path ~/main_project/outputs/train/smolvla_bi_gauze_v2/checkpoints/last/pretrained_model \
  --episode-time 30 --top-exposure 90 \
  --return-via-time 6 --return-home-time 6 \
  --host 0.0.0.0 --port 8000 \
  --callback-url http://RECEIVER_IP:9000/robot/result
```

`RECEIVER_IP`와 수신 경로를 상대 서버에 맞춥니다. 상대 서버는 해당 경로의 POST를 구현해야 합니다.
콜백 없이 조회만 할 때는 `--callback-url`을 생략합니다. `END_POINT_CALLBACK_URL` 환경변수로도 설정할 수 있습니다.

서버 시작만으로 로봇이 움직이지 않습니다. 첫 command에서 모델을 로드하고 이후 요청에 재사용합니다.
`--task`를 지정해도 **수신한 command가 우선**합니다. Python 평가 옵션을 그대로 전달할 수 있으며,
API에서는 `--dry-run`, `--no-return`, 복수 `--episodes`를 허용하지 않습니다.
단일 worker로 실행하고 reload는 사용하지 않습니다. 현재 API에는 인증 기능이 없으므로 접근 가능한 내부망에서 사용하세요.

### 1. 작업 명령 전송

다른 PC에서 `ROBOT_PC_IP`를 로봇 PC 주소로 바꿔 실행합니다.

```bash
curl -X POST http://ROBOT_PC_IP:8000/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"pick and place blue gauze","request_id":"cycle-001"}'
```

수신한 문자열이 `args.task`로 들어가 모델을 실행합니다. 응답은 HTTP 202이며 초기 `end_point`는 `false`입니다.
`request_id` 생략 시 서버가 생성합니다. 재시도에는 같은 ID, 새 작업에는 새 ID를 사용하세요.
같은 서버 실행 동안 중복 ID는 재이동하지 않고, 진행 중 다른 작업 요청은 409로 거부합니다.
서버 재시작 시 ID 기록은 초기화됩니다.

### 2. 실행 중 그리퍼 개방 신호 전송

```bash
curl -X POST http://ROBOT_PC_IP:8000/return \
  -H 'Content-Type: application/json' \
  -d '{"gripper_open":true,"request_id":"cycle-001"}'
```

진행 중 작업과 같은 ID를 쓰거나 ID를 생략합니다. 모델 루프가 신호를 확인하면 추가 모델 명령을 중단하고 복귀합니다.
신호가 없더라도 평가 시간이 끝나면 복귀합니다. `false`는 정지 명령이 아니며 이동을 시작하지 않습니다.
모델 실행이 없는 상태의 `/return`은 기존 복귀 단독 테스트를 실행하고, 이 경우 속도는 **구간당 6초로 고정**됩니다.

### 3. 완료 결과 수신/조회

시작 자세 도착 확인과 정상 정리가 끝나면 상대 서버에 다음 JSON을 POST합니다.

```json
{"end_point": true}
```

이동/실행 실패는 `{"end_point": false}`입니다. HTTP 헤더 `X-Request-ID`로 작업을 구분할 수 있습니다.
전송 실패 시 최대 3회 시도하며, 전송 오류 때문에 로봇 동작을 다시 실행하지 않습니다.
수신 측도 같은 ID의 중복 알림을 처리해야 합니다.

```bash
curl http://ROBOT_PC_IP:8000/end-point
curl http://ROBOT_PC_IP:8000/status
```

`/end-point`는 boolean 하나만 반환합니다. `/status`에는 `state`, `command`, `error`, `delivery`, `delivery_error`가 있습니다.
`end_point=true`는 **최근 작업에서 도착이 확인됐다는 결과**입니다. 토크 해제 후 손으로 옮겼을 때의 현재 위치를 실시간으로 표시하지는 않습니다.
네트워크 전송 실패 여부는 `delivery`를 별도로 확인하세요.

## 검증 및 제한 사항

- API 모의 테스트: `python -m unittest discover -s tests -p test_eval_bi_api.py -v`
- `tests/test_eval_bi_return.py`의 측정값 비교 테스트는 로컬 `left_return_via_measured.json`, `left_start_pose_measured.json`을 사용합니다. 이 JSON들은 Python/shell만 올린 현재 브랜치에 없으므로 새 clone에서 해당 테스트는 원본 파일을 별도로 준비해야 합니다.
- `test_left_return_once.py`는 **실제 로봇을 움직이는 스크립트**이며 모의 테스트와 다릅니다.
- 모델 추론, 카메라 읽기, 네트워크 상태에 따라 지연이 발생합니다. 현재 시스템은 ROS2 기반 실시간 제어가 아니라 LeRobot/Dynamixel 직접 제어입니다.
