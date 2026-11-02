# 오른팔 단독 픽 (--arm right)

왼팔과 같은 순서·옵션을 오른팔로 돌립니다. 왼팔은 안 움직입니다. `--arm`을 안 주면 예전 왼팔 그대로입니다.

- 순서: home에서 YOLO → HIGH → OPEN → APPROACH → HOVER → PICK → CLOSE → RETREAT → CARRY_HIGH → DROP_RELEASE → RELEASE → RETURN_HIGH → home(토크 OFF)
- click pick: omxtest-main `--arm right` (config/arms/right/의 XY 보정, 저장 자세, click pick setup, posture 보정)
- YOLO 좌표: 640x480 → 1920x1080 (u×2.25+240, v×2.25) 그대로. 작업 영역 = config/arms/right/omx_click_pick.json regions_uv
- ROI 기본: 0.68,0.4,1.0,1.0 (오른쪽 트레이, 가운데 통 제외). 실물로 꼭 확인
- OBB 손목 회전(--obb-rotate), --slide, --close-extra, --open-scale, --joint-offset, --no-posture 모두 같은 뜻
- 잡을 점: green = 왼쪽 변 가운데, blue = 오른쪽 변 가운데 (왼팔과 같음)
- home: pinky_sequence.json return.right.start + 오른쪽 그리퍼 rest (/dev/omx_follower)
- 오른팔에서 못 쓰는 옵션: --home-first, --outbound-ov, --return-ov (왼팔 경유 자세)

## 실행 (~/kernel-robot-repo-2-il)

```bash
# 1) ROI 확인 (vision_project) -> ~/main_project/yolo/outputs/yolo_check_right_*.jpg
python yolo_check.py --arm right

# 2) 계획만 (모터 안 움직임)
python click_pick_yolo.py --arm right --uv 1340 760
python click_pick_yolo.py --arm right --uv 1340 760 --edge 1330 720 1350 800   # 손목 회전 포함

# 3) (선택) 오른팔 carry_high 저장: 토크 끄고 손으로 통 위에 놓은 뒤
python record_click_pose.py --arm right carry_high      # -> click_pick_poses_right.json

# 4) 서버 (main_project) - 처음엔 --dry-run, 그다음 --step
python eval_bi_api_yolo.py --arm right --dry-run --host 0.0.0.0 --port 8000
python eval_bi_api_yolo.py --arm right --step --obb-rotate --host 0.0.0.0 --port 8000
python eval_bi_api_yolo.py --arm right --auto --obb-rotate --emr-api http://192.168.129.135:8000/api/v1 --host 0.0.0.0 --port 8000
# 송신
python api_sender_yolo.py flow --no-callback --command "blue:1"
```

서버는 시작할 때 /dev/omx_follower가 omxtest-main에 오른팔로 등록된 장치(by-id)와 같은지 확인합니다.
왼팔·오른팔 서버를 동시에 켤 수는 없습니다(같은 잠금 파일). 양팔 동시는 eval_bi_api_yolo_botharm.py 다음 단계에서.
