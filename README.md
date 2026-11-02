# 탑뷰 영상: 같은 와이파이 vs 클라우드(AWS)

fastcampus 로봇 서버의 탑뷰 카메라 영상을 omen(GPU 노트북)에서 받아 YOLO로 사람을 찾고,
사람이 보이면 로봇 서버에 정지 신호(`person_exist`)를 보내는 수신기입니다.

## 파일

- `recv_topview_yolo.py`: **메인 수신기.** 같은 와이파이(UDP 5000)나 클라우드(`--srt`, AWS 경유)로 영상을 받아요.
  YOLO로 사람을 찾아서, 로봇 서버 `/safety`에 `person_exist`를 계속 보내요.
- `recv_topview.py`: 예전에 쓰던 단순 영상 뷰어예요. YOLO 없이 같은 와이파이 UDP만 받아요.

### 설치 (omen)

```bash
cd ~/main_project/topview
python3 -m venv .venv && .venv/bin/pip install ultralytics opencv-python
```

- RTX 5080(Blackwell)은 CUDA 12.8 이상으로 빌드된 torch가 필요해요.
- `yolo26s.pt`는 처음 실행할 때 자동으로 다운로드돼요.
- GStreamer 플러그인이 필요해요: `gstreamer1.0-tools`, `gstreamer1.0-plugins-good`, `gstreamer1.0-plugins-bad`(SRT), `gstreamer1.0-libav`.

## 전체 흐름

```
같은 와이파이:  로봇 서버(fastcampus) ──UDP 5000──▶ omen YOLO ──/safety──▶ 로봇 서버
클라우드:       로봇 서버 ─UDP─▶ 중계(fastcampus) ─SRT─▶ AWS 3.35.89.35 ─SRT─▶ omen YOLO ──/safety──▶ 로봇 서버
```

두 방법 모두 로봇 서버는 `~/kernel-robot-repo-2-il`에서 아래 명령으로 켜요. **마지막 `--stream-host`만 달라요.**

```bash
python eval_bi_api_yolo_botharm_v2.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto \
  --joint-offset 14:-150 --pinky --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate \
  --stage-seconds 2.5 --slow-seconds 2.5 --gripper-seconds 0.6 --return-home-time 2.5 --right-no-posture \
  --stream-host <아래 참고> --stream-port 5000
```

## 1. 같은 와이파이 (team2_5G)

**fastcampus**: `--stream-host 10.42.0.222`로 켜요. omen의 IP이고 기본값이라 생략해도 돼요. 중계 명령은 필요 없어요. 켜져 있으면 꺼 주세요.

**omen**: `--srt` 없이 실행하면 UDP 5000으로 바로 받아요.

```bash
cd ~/main_project/topview
.venv/bin/python recv_topview_yolo.py --width 1280 --height 720 --imgsz 640 --device 0 \
  --robot-url http://10.42.0.147:8000
```

## 2. 클라우드 (AWS 경유)

**fastcampus ①** 로봇 서버: `--stream-host 127.0.0.1`로 켜요. 자기 자신의 중계로 보내요.

**fastcampus ②** 중계: 다른 터미널에서 실행해요. `alignment=au`와 `alignment=7`은 꼭 있어야 해요.

```bash
gst-launch-1.0 -e udpsrc port=5000 caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! \
  rtpjitterbuffer latency=50 ! rtph264depay ! h264parse config-interval=-1 ! \
  video/x-h264,stream-format=byte-stream,alignment=au ! mpegtsmux alignment=7 ! \
  srtsink uri="srt://3.35.89.35:8890?streamid=publish:topview&latency=200" wait-for-connection=false
```

- `alignment=au`가 없으면 프레임이 조각 단위로 넘어가서 PTS(시간 정보)가 빠지고, AWS(MediaMTX)가 전부 버려요. 로그에 "PTS is missing"이 떠요.
- `alignment=7`이 없으면 큰 키프레임 패킷이 SRT에서 버려져서 영상이 안 나와요.

**omen**: 중계가 켜진 다음 실행해요.

```bash
cd ~/main_project/topview
.venv/bin/python recv_topview_yolo.py --srt 3.35.89.35 --width 1280 --height 720 --imgsz 640 --device 0 \
  --robot-url http://10.42.0.147:8000
```

AWS 서버(Ubuntu 24.04, t3.micro, 서울 리전)에는 MediaMTX가 systemd 서비스(`mediamtx`)로 등록돼 있어서 따로 켤 필요 없어요. 보안 그룹은 TCP 22와 UDP 8890을 열어 뒀어요.

### 진짜 다른 와이파이일 때 (정지 신호도 AWS로)

`10.42.0.147`로 바로 갈 수 없으니까, SSH 터널을 하나씩 열고 `--robot-url http://localhost:8000`으로 바꿔요.

```bash
# fastcampus (pem은 ~/.ssh/topview-key.pem, 저장소에는 올리지 않음)
ssh -i ~/.ssh/topview-key.pem -N -R 8000:localhost:8000 ubuntu@3.35.89.35
# omen
ssh -i ~/.ssh/topview-key.pem -N -L 8000:localhost:8000 ubuntu@3.35.89.35
```

## omen 코드에서 두 방법이 갈리는 부분

`recv_topview_yolo.py` 146~160줄:

```python
    if a.srt:
        # 다른 와이파이: AWS MediaMTX에서 SRT(MPEG-TS)로 받기
        src = ["srtsrc", f"uri=srt://{a.srt}:{a.srt_port}", f"streamid={a.streamid}", f"latency={a.latency}",
               "!", "tsdemux"]
    else:
        # 같은 와이파이: UDP RTP로 직접 받기
        src = ["udpsrc", f"port={a.port}",
               "caps=application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000",
               "!", "rtpjitterbuffer", "latency=50", "drop-on-latency=true",
               "!", "rtph264depay"]
    cmd = ["gst-launch-1.0", "-q", *src,
           "!", "h264parse", "!", "avdec_h264",
           "!", "videoconvert", "!", "videoscale",
           "!", f"video/x-raw,format=BGR,width={w},height={h}",
           "!", "fdsink", "fd=1", "sync=false"]
```

영상을 받는 앞부분만 달라요. SRT는 `srtsrc → tsdemux`, UDP는 `udpsrc → rtpjitterbuffer → rtph264depay`예요. 디코딩부터 YOLO, 정지 신호 전송까지는 같아요.

## 정지 신호 규칙

`POST <robot-url>/safety {"person_exist": true|false}`를 `--send-interval`(0.2초)마다 보내요.

- true: 최근 `--window`(10) 프레임 중 `--on-frames`(7) 프레임 이상에서 사람이 보이면 바로 보내요.
- false: 사람이 `--off-seconds`(2초) 동안 한 번도 안 보이면 보내요.
- 영상이 `--stale`(0.5초) 넘게 안 들어오면 true를 보내요. 영상이 끊겼는데 false를 보내지 않게 하려는 거예요.
- 수신기가 꺼지거나 네트워크가 끊기면, 로봇 서버가 1초 뒤 스스로 멈춰요.

## 끄기와 참고

- omen 수신기를 끄려면 YOLO 창에서 `q`를 누르거나 `Ctrl+C`를 눌러요. 다른 터미널에서는 `pkill -f recv_topview_yolo.py`예요.
- omen 수신기가 꺼지면 로봇 서버는 1초 뒤 자동으로 일시정지돼요. 정상이에요.
- 정지 반응을 빠르게 하려면 omen 명령 끝에 `--window 5 --on-frames 3 --send-interval 0.1`을 붙여요.
- 측정값 (2026-10-30): 클라우드 경유 약 15fps, 정지까지 약 1초예요. 이 중 사람 확정 대기가 약 0.47초예요.
- AWS는 켜 두면 요금이 나와요. 테스트가 끝나면 EC2 인스턴스를 중지하세요.
