# 사람 감지 시 로봇 멈춤 / 재개

```
fastcampus  eval_bi_api_yolo_botharm_v2.py ──(탑뷰 영상 UDP 5000)──▶ omen@max recv_topview_yolo.py (YOLO 사람)
            ◀──────────── POST /safety {"person_exist": true|false}  0.2초마다 ─────────────┘
```

## omen@max: recv_topview_yolo.py
- `--robot-url http://<fastcampus IP>:8000`을 주면 0.2초마다 `POST /safety`로 보냅니다(안 주면 예전처럼 화면만).
- true: 최근 10프레임 중 7프레임 이상 사람(conf 0.5 이상) → 바로
- false: 사람이 2초 동안 한 번도 안 보이면
- 영상이 0.5초 넘게 안 들어오면 true(영상이 끊겼는데 false가 가지 않게)
- 화면에 `ROBOT STOP / GO`가 나오고, 터미널에 `[SAFETY]` 줄로 바뀐 순간과 전송 실패가 찍힙니다.
- 조정: `--on-frames 7 --window 10 --off-seconds 2 --stale 0.5 --conf 0.5 --send-interval 0.2`

```bash
.venv/bin/python recv_topview_yolo.py --robot-url http://<fastcampus IP>:8000 --device 0
```

## fastcampus: eval_bi_api_yolo_botharm_v2.py
- `POST /safety`를 받고, 아래면 모든 팔 동작을 멈춥니다(그 자리 유지, 토크 ON, 잡은 거즈 유지).
  - person_exist true
  - 마지막 신호 후 1초(`--safety-timeout`)가 지남: max 프로그램, 영상, 네트워크가 끊긴 경우
  - 서버를 켠 뒤 첫 신호가 오기 전
- person_exist false가 다시 오면 멈춘 자리에서 이어서 움직입니다.
- 멈추는 곳: click pick의 모든 단계(50ms마다 확인), RETURN_HIGH → home 이동, pinky 양팔 동작(grab / release / return).
  YOLO 사진 찍기, 통 대기는 원래 안 움직이니 그대로입니다.
- 로그: 서버 터미널 `[SAFETY] PAUSE: person` / `[SAFETY] RESUME: clear`, 팔별 `[LEFT] [SAFETY] paused at ramp step 9/20`.
- 상태: `GET /safety`, `GET /status`의 `safety`(paused, reason, person_exist, last_signal_age_s).
- `--no-safety`: 이 기능을 끔(max 없이 시험할 때).

## 파일
| 파일 | 하는 일 |
|---|---|
| `safety_pause.py` | 멈춤 플래그(/dev/shm/omx_pause), click pick ramp 멈춤, 멈추는 시계 |
| `click_pick_lane_v2.py` | click_pick_lane.py + 멈춤 (v2 서버가 실행) |
| `eval_bi_api_yolo_botharm_v2.py` | /safety, 1초 감시, 상태·로그 |
| `~/main_project/recv_topview_yolo.py` | max에서 실행. 사람 판단 + 전송 |
