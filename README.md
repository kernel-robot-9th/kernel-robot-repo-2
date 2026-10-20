# OMX 모방학습 · il

양팔 데이터로 ACT/SmolVLA 학습. Python/API 실행은 **왼쪽만 제어**.

## 카메라

| 위치 | 녹화·ACT 키 | SmolVLA 키 | 장치 |
|---|---|---|---|
| Top | `top` | `camera1` | `/dev/cam_top` |
| 왼쪽 wrist | `wrist_left` | `camera2` | `/dev/cam_wrist_left` |
| 오른쪽 wrist | `wrist_right` | `camera3` | `/dev/cam_wrist` |

- 기본: 640×480, 30 FPS, MJPG
- SmolVLA 학습: `train_bi.sh`에서 키 변환
- 추론: 같은 매핑 자동 적용. 오른쪽 관절·카메라도 입력용으로 필요

## 옵션

| 기능 | Shell | Python / API |
|---|---|---|
| Top 수동 노출 | `TOP_EXPOSURE=90` | `--top-exposure 90` |
| Top 마스킹 | `TOP_MASK=1` | `--top-mask` |
| 마스크 영역 | 고정 | `--top-mask-roi 0 200 400 480` |
| 증강 학습 | `AUGMENT=1` | — |

- 노출 생략: 자동. 마스크 생략: 꺼짐
- 마스크: `x=[0,400)`, `y=[200,480)`만 유지. 나머지 검정, 영상 크기 유지
- **녹화·학습·추론의 노출/마스크 조건 일치 필수**
- 학습 마스킹: `masking/mask_dataset_stream.py`로 별도 전처리
- `TOP_MASK`는 shell 평가 전용. `TOP_MASK=0`도 켜짐 → 끄려면 unset

## 파일

| 파일 | 용도 |
|---|---|
| `teleop_bi.sh` | 양팔 텔레옵 |
| `record_bi.sh` | 데이터 수집 |
| `train_bi.sh` | ACT 기본 / `POLICY=smolvla` 학습 |
| `eval_bi.sh` | 양팔 평가·데이터 저장 |
| `eval_bi.py` | 왼쪽 평가·복귀 |
| `eval_bi_api.py` | command 수신·모델 실행·결과 전송 |
| `test_left_return_once.py` | 실제 왼쪽 복귀 테스트, 구간당 6초 |

## 수집·학습

```bash
cd ~/main_project
TOP_EXPOSURE=90 bash record_bi.sh bi_gauze 'pick and place blue gauze' 5
HF_USER=YOUR_HF_USER POLICY=smolvla bash train_bi.sh bi_gauze 30000
```

## API 실행

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

- 마스킹 모델만 `--top-mask` 추가
- 서버 시작: 대기. command 수신: 모델 실행
- `command` → 모델 `task`. `--task` 생략 가능
- 첫 요청에서 모델 로드, 이후 재사용

| 요청 | JSON / 결과 |
|---|---|
| `POST /command` | `{"command":"pick and place blue gauze","request_id":"cycle-001"}` |
| `POST /return` | `{"gripper_open":true,"request_id":"cycle-001"}` |
| `GET /end-point` | `{"end_point":true}` 또는 `false` |
| `GET /status` | 실행 상태·오류·전송 결과 |

**개방 신호 또는 30초 종료 → 경유 자세 → 시작 자세 → 콜백 POST `{"end_point":true}`**

- 실패: `false`. 완료 후 왼쪽 토크 OFF
- 콜백 URL: 상대 서버 수신 주소. 생략하면 외부 전송 없음
- 재시도: 같은 ID. 새 작업: 새 ID. 중복 방지는 서버 재시작 시 초기화
- `end_point`: 도착 확인 결과. 현재 위치 실시간 판정 아님

## 확인 사항

- 환경: `main_project`, LeRobot v0.4.4 + OMX 지원, `~/il_ws/src/lerobot`
- API 패키지: `pip install fastapi uvicorn httpx`
- 설치 보조 파일(`pyproject.toml`, 장치 규칙): [jaewoo 브랜치](https://github.com/kernel-robot-9th/kernel-robot-repo-2/tree/jaewoo/omx_bimanual_il) 참고. 현재 브랜치에 미포함
- 저장된 복귀 자세: 작업 PC 실측값. 다른 로봇은 재설정 필요
- 복귀 기본 시간: Python 구간당 2초. 위 API 예시는 6초
- 그리퍼 자동 감지 없음. 외부에서 신호 전달 필요
- API: 내부망·단일 worker 사용. 인증 없음. 평가/텔레옵 동시 실행 금지
- 0.4초 응답 보장 없음
