# omx_bimanual_il

OMX 양팔(좌/우 follower + leader 2쌍) 모방학습 코드. LeRobot v0.4.4 위에서
커스텀 플러그인 `lerobot_robot_bi_omx`(robot `bi_omx_follower`, teleop `bi_omx_leader`)로
두 팔을 한 프로세스에서 다루고, 카메라 3대(top, wrist_left, wrist_right)로 데이터를 녹화해
ACT 또는 SmolVLA를 학습/실행합니다.

## 설치

```bash
# LeRobot v0.4.4 (스크립트는 ~/il_ws/src/lerobot 에서 실행됨)
pip install -e ".[dynamixel,smolvla]"      # lerobot 폴더에서
# 양팔 플러그인 (LeRobot이 third-party plugin으로 자동 로드)
pip install -e lerobot_robot_bi_omx
# 장치 고정 이름 (/dev/omx_follower, /dev/omx_follower_left, /dev/omx_leader(_left), /dev/cam_top, /dev/cam_wrist(_left))
sudo install -m 755 omx-cam-side /usr/local/bin/ && sudo cp 99-omx.rules /etc/udev/rules.d/ \
  && sudo udevadm control --reload-rules && sudo udevadm trigger
```

스크립트는 conda 환경 `main_project`, `~/main_project` 경로를 가정합니다. 시리얼 번호는 각자 보드에 맞게 `99-omx.rules`, `omx-cam-side`에서 수정하세요.

## 주요 스크립트

| 파일 | 내용 |
|---|---|
| `teleop_bi.sh` | 양팔 텔레오퍼레이션 + 카메라 3대 + rerun 뷰어 |
| `record_bi.sh <name> "<task>" [episodes]` | 양팔 데이터셋 녹화 (관절 12개 + 카메라 3대). HF 로그인 시 업로드, 아니면 로컬 저장 |
| `train_bi.sh <name> [steps]` | ACT 학습 (기본). `POLICY=smolvla`면 `lerobot/smolvla_base` 파인튜닝, `AUGMENT=1` 이미지 증강, `RESUME=1` 이어서 학습 |
| `train_group.sh A\|B\|<1-6>` | SmolVLA 실험 6개(마스킹/증강 조합)를 순서대로 학습, `logs/`에 로그 저장 |
| `eval_bi.sh <name> [step] ["task"]` | 학습된 체크포인트로 로봇 실행 (`POLICY=smolvla`, `TOP_MASK=1`, `TOP_EXPOSURE=90` 등은 학습 조건과 맞출 것) |
| `eval_bi.py --policy-path <ckpt>` | `eval_bi.sh`와 같은 추론을 파이썬 단독 스크립트로 (데이터셋 저장 없음). 아래 참고 |
| `set_top_exposure.sh <value>` | 스트리밍 시작 후 top 카메라 수동 노출 적용 (record/eval/teleop에서 `TOP_EXPOSURE` 설정 시 백그라운드 실행) |
| `clear_motor_errors.py` | 실행 전 모터 에러 해제 및 전체 모터 응답 확인 (record/eval/teleop이 자동 호출) |
| `teleop_cam.sh`, `teleop_cam_left.sh` | 단일 팔(오른쪽/왼쪽) 텔레오퍼레이션 |
| `masking/` | LeRobot v3 데이터셋의 한 카메라를 사각형 영역만 남기고 검게 마스킹(`mask_dataset.py`, 저메모리 `mask_dataset_stream.py`), 노출 보정+마스킹(`darken_mask_dataset.py`), 통계 재계산(`mask_stats.py`), 예시 프레임 그리드(`example_grid.py`) |

## eval_bi.py (단독 추론 스크립트)

`lerobot-record`(LeRobot v0.4.4 `lerobot_record.py`)에서 정책 실행 부분만 뽑은 코드입니다. 다른 코드에서 `load_policy()`, `make_robot()`, `run_episode()`를 import해서 쓸 수 있습니다.

```bash
python eval_bi.py --policy-path ~/main_project/outputs/train/smolvla_bi_gauze/checkpoints/last/pretrained_model \
    --task "pick and place blue gauze" --episode-time 60 --top-mask --top-exposure 90
python eval_bi.py --policy-path <ckpt> --dry-run   # 로봇 없이 랜덤 입력으로 모델 동작만 확인
```

- 정책 종류(ACT/SmolVLA)는 체크포인트의 `config.json`에서 자동으로 읽습니다. 카메라 키는 `--cam-keys auto`(SmolVLA는 camera1..3, 그 외는 top/wrist_left/wrist_right)입니다.
- 전체 옵션은 `python eval_bi.py --help`로 볼 수 있습니다(포트, 카메라 장치/해상도, fps, 에피소드 수/시간, `--top-mask-roi`, `--device` 등).
- `mask_rois`가 있는 이 폴더의 `lerobot_robot_bi_omx`가 설치되어 있어야 합니다(`pip install -e lerobot_robot_bi_omx`).
