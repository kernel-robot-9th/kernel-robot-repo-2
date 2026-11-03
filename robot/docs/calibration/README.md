# 실물 탑뷰 카메라 캘리브레이션

팀 가이드 "OMX 탑뷰 카메라 캘리브레이션 가이드"(2026-10-21) 방식: **ChArUco 내부 캘리브레이션 → 테이블 평면 9점 호모그래피(픽셀 → 오른팔 x, y)**.
도구: `ros2 run vla_calibration top_camera …` (ROS 불필요, 카메라 직접), 팔 좌표는 `ros2 run vla_teleop teleop here`. 결과는 `~/dev_ws/robot/calib/`.

## 인쇄물 (A4, 실제 크기 100 %로 인쇄 → 100 mm 막대 확인)
| 파일 | 용도 |
|---|---|
| `charuco_7x5_30mm_22mm_A4.pdf` | 내부 캘리브레이션 보드. `DICT_5X5_100` 0–16번. 인쇄 후 칸·마커 크기를 자로 재서 `--square`·`--marker`에 넣는다. 두꺼운 판에 평평하게 |
| `point_markers_5x5_id20-32_25mm_A4.pdf` | 테이블 점 마커. 20–28 = 맞춤 9점, 29–32 = 검증점. 네 변 가운데 눈금이 중심 |
| `checkerboard_*.pdf` | (예전) `vla_calibration intrinsics`(ROS 토픽, 시뮬용) 체커보드 |
생성 스크립트: `gen_charuco_print.py`, `gen_point_markers.py`, `gen_checkerboard_print.py`.

## 순서
0. **카메라 고정**: 거치대를 단단히(이후 건드리면 2단계부터 다시). `ros2 run vla_teleop teleop camera --tune` → 노출·화이트밸런스·**초점** 고정, 해상도 1920×1080 고정.
1. **내부 캘리브레이션** (목표 RMS ≤ 0.5 px, 1 넘으면 재촬영)
   ```bash
   ros2 run vla_calibration top_camera capture --square 0.030 --marker 0.022   # 보드를 들고 위치·기울기·거리 바꿔 SPACE, 20–30장. 빨간 칸(아직 안 찍힌 화면 구역)이 없어지게
   ros2 run vla_calibration top_camera intrinsics --square 0.030 --marker 0.022 # -> calib/top_intrinsics.yaml
   ```
2. **9점 배치**: 마커 20–28을 오른팔 앞 작업 구역에 3×3으로(대략 팔 기준 앞 14·19·24 cm × 좌우 −10·0·+10 cm, 그리퍼를 세운 채 닿는 범위 ≈ 0.27 m 안). 지우개를 놓는 구역 전체를 덮게. 검증점 29–32는 그 사이 아무 곳.
3. **픽셀 기록** (팔이 가리지 않게 접은 상태에서): `ros2 run vla_calibration top_camera points` → `calib/table_points_px.csv` + 확인 이미지.
4. **팔 좌표 기록**: `ros2 run vla_teleop teleop start --arm right` → 리더로 그리퍼 끝을 마커 중심에 **수직으로**(기울기 ±5° 이내) 살짝 대고 `ros2 run vla_teleop teleop here p20` … `p28`, 검증점 `p29`…`p32`. 백래시 때문에 같은 방향에서 2–3번 찍으면(같은 이름) 평균한다. 끝나면 팔 접고 `teleop stop`.
5. **호모그래피**: `ros2 run vla_calibration top_camera homography --arm-points ~/.cache/vla_teleop/<세션>/points.csv` → `calib/top_homography.yaml`. 맞춤 평균 ≤ 5 mm, 검증점도 ≤ 5 mm면 통과. 닿은 높이로 평면 `z = a + b x + c y`(처짐 포함)도 같이 저장 — 집기 높이에 쓴다.
**점 마커가 없을 때 — 체커보드를 바닥에 깔기 (2–5 대신, 2026-10-22)**: 내부 캘리브레이션에 쓴 체커보드(9×6, 칸 23 mm 실측)를 작업 구역 바닥에 평평하게 테이프로 고정(팔 기준 앞 13–25 cm, 좌우 ±9 cm 안 — 바깥 코너까지 그리퍼를 세워 닿게).
   ```bash
   ros2 run vla_calibration top_camera board --board 9x6 --square 0.023     # 팔 접은 채: 코너 54개 픽셀 -> calib/board_points_px.csv + 이미지(빨강 = 댈 코너 4개, 자홍 = 검증 코너)
   ros2 run vla_teleop teleop here c0_0   # … c8_0, c0_5, c8_5 (바깥 4 코너, X자 교차점에 그리퍼 끝 수직으로) + 검증 c4_3, c2_2
   ros2 run vla_calibration top_camera homography --board-points ~/dev_ws/robot/calib/board_points_px.csv --arm-points ~/.cache/vla_teleop/<세션>/points.csv
   ```
   바깥 4 코너로 보드 → 팔 위치(회전·이동)를 정하고, 코너 54개 전부로 호모그래피를 맞춘다. 검증 코너의 카메라 값과 댄 값 차이 ≤ 5 mm면 통과.
6. 사용: `vla_calibration.top_camera.pixel_to_arm(u, v, load_calibration())`.

## 흔한 문제 (가이드 표)
가장자리만 오차 큼 → 왜곡 보정·9점을 넓게 / 날마다 다름 → 초점·거치대 / 전체가 밀림 → 끝점 기준 통일 / 같은 점이 흔들림 → 같은 방향 접근·평균 / 수십 mm → 해상도 불일치·번호 짝 확인.

## 1차 실측 결과 (2026-10-22)
| 단계 | 결과 |
|---|---|
| 카메라 고정 | SNAP U2 수동 노출은 못 씀(78 = 어둠, ≥150 = 포화, 중간 없음) → 노출·화이트밸런스는 자동, **초점만 고정(0)** (`calib/camera_settings.yaml`) |
| 내부 | 손에 든 체커보드 9×6, 칸 23 mm(축소 인쇄), 36장, **RMS 0.54 px**, fx 1540 fy 1549 cx 922 cy 549 (`calib/top_intrinsics.yaml`). 맨 아래 줄은 팔 받침대 때문에 덜 덮임 |
| 테이블 | 바닥에 깐 다른 체커보드 9×6(칸 ≈ 30 mm, 팔로 잰 값), 코너 54개 검출. 리더로 6점 댐: 맞춤 `c0_0 c8_0 c0_2 c8_2`, 검증 `c4_0 2.8`·`c4_2 4.9`·`c6_1 6.1` mm → **평균 4.6 mm** (`calib/top_homography.yaml`, `--direct`) |

배운 것:
- 보드 모양으로 팔 좌표를 계산하는 방식(4점 강체)은 팔을 멀리 뻗을 때의 FK 오차(같은 방향으로 약 8 mm)를 못 따라간다 → **댄 점마다 픽셀 ↔ FK를 직접 짝짓는 `--direct`**를 쓴다(집을 때도 같은 FK로 명령하므로 상쇄).
- 리더로 그리퍼를 수직으로 유지하기 어렵다(기울기 6–14°, 기울면 7–16 mm 어긋남). 그리퍼를 세운 채 닿는 거리(≈ 0.27 m) 밖 코너는 대지 않는다.
- 보드 면이 바닥보다 약 3 cm 높았다(댄 높이 −0.01 vs 바닥 −0.044) → 바닥 물체에는 몇 mm 차이가 생길 수 있다. 다음엔 보드를 바닥에 직접 깔고, `teleop tap`으로 팔이 수직으로 코너 위에 내려가 손목 카메라로 확인하는 자동 검증을 붙인다.
