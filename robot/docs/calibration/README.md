# 실물 캘리브레이션 인쇄물

| 파일 | 내용 | 명령 |
|---|---|---|
| `checkerboard_9x6_25mm_A4.pdf` | 내부 코너 9×6(칸 10×7), 칸 25 mm, 보드 250 × 175 mm (권장: 여백 넉넉) | `ros2 run vla_calibration intrinsics --board 9x6 --square 0.025` |
| `checkerboard_8x5_30mm_A4.pdf` | 내부 코너 8×5(칸 9×6), 칸 30 mm, 보드 270 × 180 mm (칸이 커서 멀리서도 잘 보임, 좌우 여백 13.5 mm) | `ros2 run vla_calibration intrinsics --board 8x5 --square 0.03` |
| `gen_checkerboard_print.py` | 생성 스크립트: `python3 gen_checkerboard_print.py <cols> <rows> <square_mm>` (A4 가로, 300 dpi, OpenCV 코너 자가 검사) | |

- 인쇄: **실제 크기(100 %)**, "페이지에 맞춤" 끄기. 인쇄 후 아래 100 mm 막대를 자로 재서 다르면 `--square`를 실측 칸 크기로 넣는다.
- 휘지 않게 두꺼운 판(폼보드 등)에 붙인다. 반사가 적은 무광 용지가 좋다.
- 기본 도구값(9×6, 30 mm)은 A4에 300 × 210 mm로 꽉 차서 인쇄가 잘리므로 쓰지 않는다.
- 도구는 ROS 이미지 토픽(`/camera/image_raw`)을 받는다: 실물 탑뷰 카메라를 `usb_cam` 등으로 먼저 띄워야 한다.
