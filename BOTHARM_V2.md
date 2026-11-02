# 양팔 서버 v2: 카메라 하나로 YOLO + 영상 전송

`eval_bi_api_yolo_botharm_v2.py`는 `eval_bi_api_yolo_botharm.py`와 똑같이 동작하고, 카메라만 다르게 다룹니다.
기존 파일(eval_bi_api_yolo_botharm.py, yolo_worker.py)은 바꾸지 않았습니다.

- 탑 카메라는 YOLO 프로세스(`yolo_worker_v2.py`) 하나만 엽니다(1280x720, 30fps, 노출 90).
- 읽은 프레임마다
  - 영상 전송: H.264 RTP/UDP로 `--stream-host:--stream-port`(기본 10.42.0.222:5000)에 보냅니다. send_topview.sh와 같은 설정이라 받는 쪽은 그대로 쓰면 됩니다.
  - YOLO: 가운데 4:3 부분(960x720)을 640x480으로 줄여서 씁니다. 카메라의 640x480 모드와 같은 화면이라 좌표 변환(×2.25+240)은 그대로입니다.
- 영상 전송이 끊기거나 느려도 YOLO는 영향을 안 받습니다. 전송은 2초 뒤 다시 시작합니다.
- 서버를 끄면 영상 전송도 같이 꺼집니다.

## 실행

```bash
# 1) send_topview.sh가 돌고 있으면 먼저 끄기 (켜져 있으면 서버가 누가 잡고 있는지 보여주고 멈춤)
pkill -f send_topview.sh; pkill -f 'udpsink host='
fuser -v /dev/cam_top        # 아무것도 안 나와야 함

# 2) 서버 (옵션은 예전과 같음, 영상은 기본으로 10.42.0.222:5000)
python eval_bi_api_yolo_botharm_v2.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto --pinky \
    --joint-offset 14:-150 --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate \
    --stage-seconds 2.5 --slow-seconds 2.5 --gripper-seconds 0.6 --return-home-time 2.5
```
- 다른 주소로 보내기: `--stream-host 10.42.0.189 --stream-port 5000`
- 영상 없이 YOLO만: `--no-stream`
- 카메라 해상도 바꾸기: `--capture-size 1920x1080` (YOLO 화면 계산은 자동으로 맞춤)

## 처음 한 번 확인할 것

- 1280x720 모드가 1920x1080과 같은 화면(가운데를 자르지 않은 전체 화면)인지. 다르면 YOLO 좌표가 어긋납니다.
  서버 로그의 `[YOLO]` 잡는 점이 예전(eval_bi_api_yolo_botharm.py)과 비슷한 자리면 맞는 것입니다.
- 노출이 90(수동)으로 고정되므로 긴급정지 쪽 영상도 그 밝기로 보입니다.

## OMX 서버 실행법

### 기본 실행 (영상 전송 없음/기본 설정)

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

주의:
- 중계는 카메라(`v4l2src`)를 직접 열면 안 됩니다. 서버가 카메라를 쓰고 있어서 `Device busy`가 납니다. 꼭 `udpsrc port=5000`으로 서버가 보내는 영상을 받아야 합니다.
- pem 키 등 비밀 정보는 이 문서에 넣지 않습니다.
