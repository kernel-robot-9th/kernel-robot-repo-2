# OMX 양팔 거즈 집기 서버 · vision

탑 카메라 YOLO로 거즈를 찾고, 클릭 픽 자세로 양팔이 집어서 통에 넣습니다.
메인 서버는 `eval_bi_api_yolo_botharm_v2.py`입니다. **green은 왼팔, blue는 오른팔**이 잡습니다.

## OMX 서버 실행법

```bash
conda activate main_project
cd ~/kernel-robot-repo-2-il

# send_topview.sh가 돌고 있으면 먼저 끄기 (카메라는 서버 하나만 열 수 있음)
pkill -f send_topview.sh; pkill -f 'udpsink host='
fuser -v /dev/cam_top        # 아무것도 안 나와야 함
```

### 기본 실행

```bash
python eval_bi_api_yolo_botharm_v2.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto --joint-offset 14:-150 --pinky --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate --stage-seconds 2.5 --slow-seconds 2.5 --gripper-seconds 0.6 --return-home-time 2.5 --right-no-posture
```

### AWS 버전 실행 (탑뷰 영상을 AWS로 중계)

서버는 탑뷰 영상을 로컬 UDP 5000(RTP H.264)으로 보내고, 별도 터미널의 GStreamer 중계가 이를 받아 AWS SRT 서버로 보냅니다.

터미널 1 (OMX 서버):

```bash
python eval_bi_api_yolo_botharm_v2.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto --joint-offset 14:-150 --pinky --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate --stage-seconds 2.5 --slow-seconds 2.5 --gripper-seconds 0.6 --return-home-time 2.5 --right-no-posture --stream-host 127.0.0.1 --stream-port 5000
```

터미널 2 (AWS 중계):

```bash
gst-launch-1.0 -v udpsrc port=5000 caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! rtph264depay ! h264parse ! mpegtsmux ! srtsink uri="srt://3.35.89.35:8890?streamid=publish:topview&latency=200"
```

- 중계는 카메라(`v4l2src`)를 직접 열면 안 됩니다. 서버가 카메라를 쓰고 있어서 `Device busy`가 납니다.
- 영상 없이 YOLO만: `--no-stream` / 모터 없이 확인: `--dry-run`

## 명령

```
POST /command {"command": {"blue": 1, "green": 1}, "request_id": "cycle-001"}
```

- 0은 건너뜀. 모르는 키나 0~20 밖의 횟수는 422, 아무것도 안 움직임
- 모든 시도가 끝나면 EMR로 end-point 전송. `--pinky`면 두 팔이 home에 온 뒤 pinky 시퀀스
- `GET /detection`: 최근 YOLO 결과 / `POST /safety {"person_exist": true}`: 사람 감지 시 멈춤

## 확인 사항

- 환경: `main_project`, LeRobot v0.4.4 + OMX 지원(`~/il_ws/src/lerobot`, 모터 제어용)
- 패키지: `pip install fastapi uvicorn httpx ultralytics`
- `eval_bi_api.py`는 API 뼈대(/command, /status, /end-point)로 계속 쓰이므로 지우지 말 것
- 자세 파일: `pinky_sequence.json`(`pinky_record.py`로 기록), `click_pick_poses_right.json`. 작업 PC 실측값이라 다른 로봇은 재설정 필요
- API: 내부망·단일 worker. 인증 없음

## 문서

| 파일 | 내용 |
|---|---|
| [BOTHARM_V2.md](BOTHARM_V2.md) | v2 서버: 카메라 하나로 YOLO + 영상 전송 |
| [BOTHARM.md](BOTHARM.md) | 양팔 명령 형식, 통 순서, YOLO 큐 |
| [RIGHT_ARM.md](RIGHT_ARM.md) | 오른팔 단독 실행 |
| [SAFETY.md](SAFETY.md) | 사람 감지 시 멈춤 / 재개 |
| [VISION.md](VISION.md) | YOLO + 클릭 픽 흐름, 좌표 변환, 작업 영역 |
