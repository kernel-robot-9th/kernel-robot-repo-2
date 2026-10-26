# Vision branch: YOLO gauze pick (replaces the IL policy in the API)

`eval_bi_api_yolo.py` keeps the `eval_bi_api.py` API, but on `POST /command` the left arm
picks with **YOLO + click pick** instead of the imitation-learning policy.

## Flow

```
POST /command {"command": "pick and place blue gauze", "request_id": "..."}
  -> YOLO on the top camera (arm at home)
  -> click pick: HIGH -> OPEN -> APPROACH -> HOVER -> PICK -> CLOSE -> RETREAT
                 -> CARRY_HIGH -> DROP_RELEASE -> RELEASE -> RETURN_HIGH
  -> HOME (left torque off) -> end_point success
  -> (--pinky) both-arm pinky sequence: grab & hold -> pinky_arrive -> release -> return
```

- `blue` in the command -> only `blue_gauze`; `green` -> only `green_gauze`. No target in the
  work area -> the arm does not move and the command fails.
- Grasp point: `green_gauze` = middle of the box's left edge (two smallest-x corners),
  `blue_gauze` = middle of the right edge (two largest-x corners).
- Work area: grasp point inside x 0~0.4, y 0.5~1 of the 640x480 frame (leaves out the black box)
  **and**, mapped to 1920x1080, inside the click-pick `regions_uv`.
- YOLO runs at 640x480 (same as training). 640x480 = centre 1440x1080 of 1920x1080 scaled 2.25x:
  `u1080 = u*2.25 + 240`, `v1080 = v*2.25` (re-measure with `vision/fov_check.py`).

## Run

```bash
conda activate main_project
cd ~/kernel-robot-repo-2-il
# server (results to EMR; add --step instead of --auto to confirm each step with SPACE)
python eval_bi_api_yolo.py --host 0.0.0.0 --port 8000 --emr-api http://192.168.129.135:8000/api/v1 --auto --pinky
# test sender (plays the command sender + Pinky)
python api_sender_yolo.py flow --no-callback --pinky --command "pick and place blue gauze"
```

No motors: add `--dry-run` to the server (YOLO and the click-pick plan run for real, moves are logged).
With a local callback receiver instead of EMR: `--callback-url http://127.0.0.1:9000/robot/result`
on the server and `api_sender_yolo.py flow` without `--no-callback`.

### Server options

| option | meaning |
|---|---|
| `--auto` / `--step` | no confirmations / SPACE before every arm-gripper step (q = stop, torque kept) |
| `--dry-run` | no motor port opened |
| `--emr-api URL` | on success `GET URL/robot/<request_id>/end-point` (200 = received, 3 tries) |
| `--callback-url URL` | old way: POST `{"end_point": true}` |
| `--pinky` | both-arm pinky sequence after home (off by default) |
| `--joint-offset ID:PULSES` + `--offset-stages` | add pulses to joints in stages (default APPROACH), e.g. `14:-100` |
| `--close-extra N` | close N pulses past `close_pulse` (thin bags, try 50~100) |
| `--open-scale F` | OPEN width fraction (default 1) |
| `--click-skip ...` | click-pick stages left out (default `LIFT DROP_RETREAT`) |
| `--home-first` / `--outbound-ov` / `--return-ov` | old v5 moves back on |

Log lines: `[YOLO] ...`, `[ARM] HIGH`, `[GRIPPER] OPEN`, `[STEP] next: ...`, `[EMR] end-point sent ... -> 200`.
`/status` phase: detect -> pick -> drop -> to_home -> done; `GET /detection` = last YOLO result.

## Tools

| file | what |
|---|---|
| `yolo_check.py` (env `vision_project`) | what YOLO sees now, every box + what the API would pick |
| `record_click_pose.py carry_high` | save a click-pick stage pose (pulses) -> `click_pick_poses.json` |
| `pinky_record.py torque-off / approach_high / above_target / lift / hold / open` | re-record `pinky_sequence.json` (backup kept) |
| `pinky_move.py grab / release / return / --check` | test the pinky sequence alone |
| `clear_motor_errors.py /dev/omx_follower` | clear latched motor errors (hold the arm) |

## Files

- `eval_bi_api_yolo.py` server, `api_sender_yolo.py` test sender
- `yolo_worker.py` YOLO process (env `vision_project`; the robot env has no ultralytics on purpose)
- `click_pick_yolo.py` = `omxtest-main/tools/picking/omx_click_pick.py run --live` with the YOLO point
- `left_arm_only.py` click pick uses `/dev/omx_follower_left` even with several OpenRBs plugged in
- `step_key.py` SPACE gate for `--step`
- `vision/` capture, labelme -> YOLO, training, live view, FOV check (`vision/README_yolo_train.md`)

Not in git: YOLO weights (`~/main_project/yolo/runs/obb/gauze_obb_v1/weights/best.pt`), images,
the click-pick config/calibration (`~/main_project/omxtest-main/config/`).

## Calibration notes (2026-10-26)

- Click-pick XY calibration `omxtest-main/config/single/omx_xy_calibration.json` (1920x1080, mean error 5.3 mm).
- Posture correction `omx_click_pick.json` `joint_offset_pulses: [7, 119, -150, 107, 15]`
  (`omx_click_adjust.py --posture`), applied to APPROACH/HOVER/PICK/LIFT/RETREAT.
- `pinky_sequence.json` re-recorded 2026-10-26 (approach_high, above_target incl. left arm, lift, gripper close).
- Top camera vs 2026-10-25: markers moved 2~3 px (~4 mm).
- TODO: rotation-proof edge choice for the grasp point, see `vision/TODO.md`.
