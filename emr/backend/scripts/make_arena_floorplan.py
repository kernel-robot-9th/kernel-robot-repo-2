# =============================================================================
# 파일   : scripts/make_arena_floorplan.py
# 역할   : 팀원 아레나 평면도(layout_diagram.png)에서 EMR "병원 지도"용 평면도 PNG + map_server yaml을 만든다 (2026-10-29)
# 작성일 : 2026-10-29
# 구성   :
#   - diagram_pixel()          그림 cm → layout_diagram.png 픽셀 (팀원 driving/graph/build_graph.py diagram_px와 같은 값)
#   - crop_arena()             아레나 (0,0)–(210,200) cm 상자만 잘라 RESOLUTION_M_PER_PIXEL로 키움 (축 눈금·바깥 틀 뺌)
#   - draw_center_passage()    중앙 검은 블록을 빈칸 없이 통로(초록)로 칠하고 실제 주행 선 (40,70)→(130,90)을 점선으로
#                              (10-29 사용자 "검은 구간을 다른 통로와 동일하게, 빈칸없이" · "아이보리색 테두리, H자 중앙")
#   - dark_block_mask()        상자 안 검은 블록 마스크
#   - round_dilate()           마스크를 원으로 넓힘 — 아이보리 테두리 모서리를 둥글게 (10-29 사용자 "아이보리는 모서리를 곡선 처리")
#   - write_yaml()             origin (0, 0, 0) — 그림 cm/100 = m. FMS pose·EMR 장소 좌표와 같은 프레임
# 그림에는 중앙 통로가 없고(검은 블록), 실제 아레나·FMS 주행 그래프(L70–R90, Nav2 대각선)에는 있다 → 표시용으로만 그려 넣는다.
# 그 밖(수술실·옆 검은 블록 등)은 원본 그대로 (10-29 사용자 "통로는 유지, 수술실만 원래대로").
# 호스트에서 Pillow로 돌리고, 결과를 맵 "Pinky 아레나" 파일 교체(PUT /api/v1/maps/{id}/files)로 올린다 — 장소 좌표는 그대로:
#   /usr/bin/python3 backend/scripts/make_arena_floorplan.py \
#       --diagram ~/fms/kernel-robot-repo-2/driving/tools/layout_diagram.png --out-dir /tmp/arena [--original: 통로 없이 원본만]
# =============================================================================
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ARENA_WIDTH_CM = 210
ARENA_HEIGHT_CM = 200
DIAGRAM_ORIGIN_PX = (76, 40)          # 그림 (0, 200) cm 의 layout_diagram.png 픽셀
DIAGRAM_PX_PER_CM = 3.39
RESOLUTION_M_PER_PIXEL = 0.0015       # 1 cm = 6.67 px (원본의 약 2배)

PASSAGE_START_CM = (40.0, 70.0)       # 주행 그래프 L70 — 점선(실제 주행 선)의 시작
PASSAGE_END_CM = (130.0, 90.0)        # 주행 그래프 R90 — 점선의 끝
CENTER_BLOCK_BOX_CM = (44.0, 58.0, 121.0, 104.0)   # 중앙 검은 블록을 찾을 상자 (x0, y0, x1, y1) — 블록은 x 52~120, y 63~100
# 블록과 양옆 협로 초록 띠 사이의 흰 여백도 칠해 빈칸 없이 잇는다: (칠할 x 범위 cm, 블록이 있는지 볼 열 x cm)
JOINS_CM = (((43.0, 54.0), 54.0), ((118.0, 128.0), 118.0))
FLOOR_LUMINANCE_MIN = 160             # 이보다 밝으면 협로 바닥·블록 흐린 가장자리 — 이음에서는 이것만 칠한다 (점선·병실은 안 칠함)
GREEN_COLOR = (180, 211, 195)         # 통로 초록 (그림 협로에서 뽑은 색)
MARGIN_COLOR = (240, 243, 242)        # 통로 가장자리 아이보리 테두리 (그림 협로 테두리 색)
MARGIN_WIDTH_CM = 6.45                # 병실 벽에서 이 폭만큼 테두리 — 그림 협로·복도 테두리 폭(30곳 잰 가운데값 43 px, 10-29 사용자 "협로와 같은 폭으로")
DASH_COLOR = (138, 157, 149)          # 통로 가운데 점선
WALL_COLOR = (110, 120, 122)          # 병실과 맞닿는 곳에 남기는 벽 선
DARK_LUMINANCE_MAX = 160              # 밝기(0~255)가 이보다 낮으면 검은 블록


def diagram_pixel(x_cm: float, y_cm: float) -> tuple[float, float]:
    """[입력] 그림 cm [출력] layout_diagram.png 픽셀 (x, y)"""
    return DIAGRAM_ORIGIN_PX[0] + DIAGRAM_PX_PER_CM * x_cm, DIAGRAM_ORIGIN_PX[1] + DIAGRAM_PX_PER_CM * (ARENA_HEIGHT_CM - y_cm)


def crop_arena(diagram: Image.Image) -> Image.Image:
    """[입력] diagram: layout_diagram.png (RGB) [출력] 아레나 상자만, RESOLUTION_M_PER_PIXEL 크기"""
    left_px, top_px = diagram_pixel(0, ARENA_HEIGHT_CM)
    right_px, bottom_px = diagram_pixel(ARENA_WIDTH_CM, 0)
    pixels_per_cm = 0.01 / RESOLUTION_M_PER_PIXEL
    size_px = (round(ARENA_WIDTH_CM * pixels_per_cm), round(ARENA_HEIGHT_CM * pixels_per_cm))
    return diagram.resize(size_px, Image.Resampling.LANCZOS, box=(left_px, top_px, right_px, bottom_px))


def round_dilate(mask: Image.Image, near_mask: Image.Image, radius_px: float) -> Image.Image:
    """mask를 원(반지름 radius_px)으로 넓힌다 — 모서리가 둥글다(다른 통로 테두리처럼). near_mask 근처 가장자리만 계산.
    [입력] mask / near_mask: 이 둘레 radius_px 안의 가장자리만 원을 찍는다 / radius_px [출력] 넓힌 마스크
    """
    edge_mask = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
    reach_mask = near_mask
    for _ in range(math.ceil(radius_px / 4)):
        reach_mask = reach_mask.filter(ImageFilter.MaxFilter(9))
    edge_mask = ImageChops.multiply(edge_mask, reach_mask)
    result = mask.copy()
    draw = ImageDraw.Draw(result)
    bbox = edge_mask.getbbox()
    if bbox is None:
        return result
    pixels = edge_mask.crop(bbox).load()
    for row in range(bbox[3] - bbox[1]):
        for column in range(bbox[2] - bbox[0]):
            if pixels[column, row]:
                x_px, y_px = column + bbox[0], row + bbox[1]
                draw.ellipse([x_px - radius_px, y_px - radius_px, x_px + radius_px, y_px + radius_px], fill=255)
    return result


def dark_block_mask(floorplan: Image.Image, box_cm: tuple[float, float, float, float]) -> Image.Image:
    """상자 안 검은 블록 — 어두운 픽셀에서 가는 선·글자를 빼고(열기), 흐린 가장자리 1px까지.
    [입력] floorplan / box_cm: (x0, y0, x1, y1) 그림 cm [출력] 마스크 (블록 255)
    """
    pixels_per_cm = 0.01 / RESOLUTION_M_PER_PIXEL
    box_x0, box_y0, box_x1, box_y1 = box_cm
    box_mask = Image.new("L", floorplan.size, 0)
    ImageDraw.Draw(box_mask).rectangle([
        (round(box_x0 * pixels_per_cm), round(floorplan.height - box_y1 * pixels_per_cm)),
        (round(box_x1 * pixels_per_cm), round(floorplan.height - box_y0 * pixels_per_cm)),
    ], fill=255)
    dark_mask = floorplan.convert("L").point(lambda luminance: 255 if luminance < DARK_LUMINANCE_MAX else 0)
    block_mask = ImageChops.multiply(dark_mask, box_mask)
    return block_mask.filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MaxFilter(3))


def draw_center_passage(floorplan: Image.Image) -> Image.Image:
    """중앙 검은 블록을 빈칸 없이 통로로 칠한다(H자 가운데 가로대) — 양옆 협로와 그 사이 흰 여백까지 잇고, 가운데 초록,
    병실 벽 쪽은 아이보리 테두리(MARGIN_WIDTH_CM)와 벽 선,
    실제 주행 선(L70→R90)은 협로처럼 점선.
    [입력] floorplan: crop_arena 결과 [출력] 칠한 그림
    """
    pixels_per_cm = 0.01 / RESOLUTION_M_PER_PIXEL
    height_px = floorplan.height

    def to_pixel(x_cm: float, y_cm: float) -> tuple[int, int]:
        return round(x_cm * pixels_per_cm), round(height_px - y_cm * pixels_per_cm)

    block_mask = dark_block_mask(floorplan, CENTER_BLOCK_BOX_CM)

    # 병실 색(파란 기가 도는 회색: B − G > 5)은 칠하지 않는다 — 협로 흰 바닥·초록과 구별된다
    _, green, blue = floorplan.split()
    room_mask = ImageChops.subtract(blue, green).point(lambda difference: 255 if difference > 5 else 0)
    room_mask = room_mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))   # 블록 가장자리 점 같은 작은 얼룩은 병실이 아님

    # 양옆 이음: 블록 끝 열에 블록이 있는 줄만, 그 사이 흰 바닥(병실 아님)을 칠한다
    floor_mask = ImageChops.multiply(
        floorplan.convert("L").point(lambda luminance: 255 if luminance > FLOOR_LUMINANCE_MIN else 0), ImageChops.invert(room_mask))
    join_mask = Image.new("L", floorplan.size, 0)
    for (join_x0_cm, join_x1_cm), edge_x_cm in JOINS_CM:
        join_x0_px, _ = to_pixel(join_x0_cm, 0)
        join_x1_px, _ = to_pixel(join_x1_cm, 0)
        edge_x_px, _ = to_pixel(edge_x_cm, 0)
        edge_column = block_mask.crop((edge_x_px, 0, edge_x_px + 1, height_px))
        join_mask.paste(edge_column.resize((join_x1_px - join_x0_px, height_px)), (join_x0_px, 0))
    fill_mask = ImageChops.lighter(block_mask, ImageChops.multiply(join_mask, floor_mask))

    result = Image.composite(Image.new("RGB", floorplan.size, GREEN_COLOR), floorplan, fill_mask)
    # 병실 벽에서 MARGIN_WIDTH_CM 안쪽은 아이보리 테두리 — 다른 통로처럼 H자 가운데 가로대가 된다
    near_room_mask = round_dilate(room_mask, ImageChops.lighter(fill_mask.filter(ImageFilter.MaxFilter(9)), fill_mask),
                                  MARGIN_WIDTH_CM * pixels_per_cm)
    result = Image.composite(Image.new("RGB", floorplan.size, MARGIN_COLOR), result, ImageChops.multiply(fill_mask, near_room_mask))
    wall_mask = ImageChops.multiply(ImageChops.subtract(fill_mask.filter(ImageFilter.MaxFilter(5)), fill_mask), room_mask)
    result = Image.composite(Image.new("RGB", floorplan.size, WALL_COLOR), result, wall_mask)

    # 실제 주행 선 L70 → R90 점선 — 칠한 곳 안에만
    start, end = to_pixel(*PASSAGE_START_CM), to_pixel(*PASSAGE_END_CM)
    dashes = Image.new("L", floorplan.size, 0)
    draw = ImageDraw.Draw(dashes)
    length_px = math.dist(start, end)
    dash_px = 3 * pixels_per_cm
    distance_px = 0.0
    while distance_px < length_px:
        dash_end_px = min(distance_px + dash_px, length_px)
        draw.line([
            (start[0] + (end[0] - start[0]) * distance_px / length_px, start[1] + (end[1] - start[1]) * distance_px / length_px),
            (start[0] + (end[0] - start[0]) * dash_end_px / length_px, start[1] + (end[1] - start[1]) * dash_end_px / length_px),
        ], fill=255, width=max(2, round(0.4 * pixels_per_cm)))
        distance_px += 2 * dash_px
    return Image.composite(Image.new("RGB", floorplan.size, DASH_COLOR), result, ImageChops.multiply(dashes, fill_mask))


def write_yaml(path: str, image_file_name: str) -> None:
    """[입력] path / image_file_name [출력] 없음 — map_server yaml (EMR은 resolution·origin만 읽는다)"""
    with open(path, "w", encoding="utf-8") as yaml_file:
        yaml_file.write(
            f"image: {image_file_name}\n"
            f"resolution: {RESOLUTION_M_PER_PIXEL}\n"
            "origin: [0.0, 0.0, 0.0]\n"
            "# 그림 cm/100 = m, 왼쪽 아래 원점 — FMS pose(cm)·EMR 장소(Pinky 아레나)와 같은 프레임. 표시용 평면도(벽 판정에 쓰지 않음)\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="layout_diagram.png → EMR 평면도 PNG + yaml")
    parser.add_argument("--diagram", required=True, help="팀원 driving/tools/layout_diagram.png")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--original", action="store_true",
                        help="중앙 통로를 그리지 않고 원본 평면도만 잘라 키움 → arena_floorplan_original.png (2026-10-29)")
    args = parser.parse_args()

    diagram = Image.open(os.path.expanduser(args.diagram)).convert("RGB")
    floorplan = crop_arena(diagram) if args.original else draw_center_passage(crop_arena(diagram))
    base_name = "arena_floorplan_original" if args.original else "arena_floorplan"
    os.makedirs(args.out_dir, exist_ok=True)
    image_path = os.path.join(args.out_dir, f"{base_name}.png")
    floorplan.save(image_path, optimize=True)
    write_yaml(os.path.join(args.out_dir, f"{base_name}.yaml"), f"{base_name}.png")
    print(f"{image_path} {floorplan.width}x{floorplan.height}px, resolution {RESOLUTION_M_PER_PIXEL} m/px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
