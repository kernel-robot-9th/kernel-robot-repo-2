# 양팔 서버: eval_bi_api_yolo_botharm.py

명령 하나에 잡을 목표와 횟수를 담으면 왼팔과 오른팔이 동시에 일합니다.
**green은 왼팔, blue는 오른팔**이 잡습니다(`--left-targets` / `--right-targets`로 바꿀 수 있음).
통(CARRY_HIGH ~ RETURN_HIGH)은 한 번에 한 팔만 들어갑니다.

```
POST /command {"command": {"blue": 1, "green": 1}, "request_id": "cycle-001"}
```
- `"blue:1, green:1"` 문자열, `blue_gauze` / `green_gauze` 키, 예전 문장 `"pick and place blue gauze"`(= blue:1)도 받습니다.
- 0은 건너뜁니다: `{"blue":1,"green":0}`이면 오른팔만 움직입니다.
- 모르는 키나 0~20 밖의 횟수가 오면 바로 422를 돌려주고 아무것도 움직이지 않습니다.
- 한 번 시도 = home에서 YOLO → HIGH … RETREAT → **[통]** CARRY_HIGH → DROP_RELEASE → RELEASE → RETURN_HIGH **[/통]** → home(토크 OFF)

## 통 순서

- CARRY_HIGH에 먼저 도착한 팔이 통을 차지합니다. 다른 팔은 RETREAT 뒤(CARRY_HIGH 전)에서 거즈를 잡은 채(토크 ON)
  기다리다가, 앞 팔의 RETURN_HIGH가 끝나면 CARRY_HIGH로 갑니다.
- 통 위에서 팔이 멈추면(오류) 통은 막힌 채로 남고, 기다리던 팔도 RETREAT에서 멈추고(토크 ON) 명령은 실패로 끝납니다.
- 한 팔이 실패하면 다른 팔은 지금 하던 시도까지만 마치고 남은 시도는 건너뜁니다.
- YOLO가 목표를 못 찾으면 그 목표의 남은 횟수는 건너뛰고(팔은 home) 다음 목표로 넘어갑니다.
- 모든 시도가 끝나야 성공(end_point true, EMR end-point). `--pinky`면 두 팔이 모두 home에 온 뒤 양팔 pinky 시퀀스.

## YOLO (카메라 상시 오픈 + YOLO 하나 + 요청 큐)

- 서버가 켜질 때 YOLO 프로세스(yolo_worker.py `--keep-open`)를 **하나만** 띄웁니다. 카메라는 그때 한 번 열고 계속 읽으며 최근 약 3초 프레임을 들고 있습니다.
- 두 팔의 YOLO 요청은 큐(FIFO)에 들어가고, 스레드 하나가 들어온 순서대로 처리합니다. 잠금(Lock)은 없습니다.
- 요청에는 "물어본 시각"이 붙고, YOLO는 그 시각 이후에 찍힌 프레임 5장을 씁니다. 앞 요청 때문에 큐에서 기다렸어도 물어본 순간의 장면을 봅니다.
- 요청마다 그 팔의 ROI·작업 영역·conf를 같이 보냅니다(왼팔 `--roi`, 오른팔 `--right-roi`). `--right-weights`가 다르면 같은 프로세스에 그 모델을 하나 더 올립니다.
- 기다리는 요청이 있으면 터미널에 `[RIGHT][YOLO] queued, 1 ahead`처럼 나옵니다.
- 서버가 카메라를 계속 쓰므로, 서버가 켜져 있는 동안 `yolo_check.py`는 카메라를 못 엽니다(`--image`로 저장된 사진은 됨).

## 실행 (~/kernel-robot-repo-2-il, env main_project)

```bash
# 1) 카메라·모터 없이 순서와 통 Lock만
python eval_bi_api_yolo_botharm.py --sim --port 8000
# 2) YOLO와 click pick 계획은 진짜, 모터는 안 움직임
python eval_bi_api_yolo_botharm.py --dry-run --host 0.0.0.0 --port 8000 \
    --joint-offset 14:-150 --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate
# 3) 양팔 실제
python eval_bi_api_yolo_botharm.py --host 0.0.0.0 --port 8000 --emr-api http://10.42.0.1:5173/api/v1 --auto --pinky \
    --joint-offset 14:-150 --open-scale 0.9 --close-extra 150 --slide 150 --obb-rotate
# 송신
python api_sender_yolo.py flow --no-callback --pinky --command '{"blue":1,"green":1}'
```
- 두 팔이 터미널 하나를 같이 쓰므로 실물은 `--auto`가 필요합니다(`--step` 불가).
- 집기 옵션(`--joint-offset --open-scale --close-extra --slide --obb-rotate --wrist-deg --no-posture --click-skip`)은 두 팔 공통입니다.
  오른팔만 다르게: `--right-joint-offset 14:-120`, `--right-open-scale`, `--right-close-extra`, `--right-slide`,
  `--right-wrist-deg`, `--right-no-obb-rotate`, `--right-no-posture`.
- 속도(json은 안 바꿈, 두 팔 공통): `--stage-seconds 2.5`(팔 단계마다 초, 기본 4.0), `--slow-seconds 4`(APPROACH·HOVER·PICK만,
  `--slow-stages`로 바꿈), `--gripper-seconds 0.6`(기본 0.8), `--return-home-time 3`(RETURN_HIGH → home, 기본 4.0).
  home 이동은 너무 빠르면 추종 오차로 멈출 수 있으니 조금씩 줄이세요.
- ROI: 왼팔 `--roi 0,0.5,0.4,1.0`, 오른팔 `--right-roi 0.68,0.4,1.0,1.0`.
- `--no-right`: 왼팔만.

## 오른팔 설정

- click pick은 omxtest-main `--arm right` (config/arms/right/의 보정·저장 자세·setup)를 씁니다. omxtest-right 복사본은 필요 없습니다
  (예전 방식은 `--right-omx <복사본>`으로 남아 있음).
- carry_high 등 오른팔 고정 자세: `python record_click_pose.py --arm right carry_high` → click_pick_poses_right.json
- 오른팔 home: pinky_sequence.json의 return.right.start + 오른쪽 그리퍼 rest (/dev/omx_follower).
  서버는 시작할 때 /dev/omx_follower가 omxtest-main에 오른팔로 등록된 장치인지 확인합니다.
- 오른팔 단독: `python eval_bi_api_yolo.py --arm right ...` (RIGHT_ARM.md)

## 파일

| 파일 | 하는 일 |
|---|---|
| `eval_bi_api_yolo_botharm.py` | 양팔 서버. eval_bi_api / eval_bi_api_yolo를 가져다 씀 |
| `click_pick_lane.py` | 팔 하나의 click pick(click_pick_yolo.py) + 통 게이트(BIN_WAIT / GO / BIN_FREE) |
| `click_pick_yolo.py` | click pick 한 번 (`--arm right` = omxtest-main 오른팔) |
| `right_arm_only.py`, `run_right_omx.py` | 예전 omxtest-right 복사본 방식용 |
