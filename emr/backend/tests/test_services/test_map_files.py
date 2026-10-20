"""맵 파일 해석 (map_server yaml, PGM·PNG → PNG). DB 불필요."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.exceptions import BadRequest
from app.services.map_files import MAP_IMAGE_MAX_SIDE_PX, parse_map_yaml, to_png

PINKY_MY_MAP_YAML = """image: my_map.pgm
mode: trinary
resolution: 0.05
origin: [-2.05, -1.62, 0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.25
"""


def make_pgm(width_px: int = 82, height_px: int = 63) -> bytes:
    """Pinky my_map.pgm과 같은 P5(바이너리) PGM. 가운데 검정 벽 한 줄."""
    pixels = bytearray([254] * (width_px * height_px))
    for column in range(width_px):
        pixels[(height_px // 2) * width_px + column] = 0
    return f"P5\n{width_px} {height_px}\n255\n".encode() + bytes(pixels)


def test_parse_pinky_map_yaml():
    info = parse_map_yaml(PINKY_MY_MAP_YAML)
    assert (info.resolution_m_per_pixel, info.origin_x_m, info.origin_y_m, info.origin_yaw_rad) == (0.05, -2.05, -1.62, 0.0)
    assert info.image_name == "my_map.pgm"


@pytest.mark.parametrize("bad_yaml", [
    "resolution: 0.05\n",                           # origin 없음
    "resolution: 0\norigin: [0, 0, 0]\n",            # resolution 0
    "resolution: 0.05\norigin: [0, 0]\n",            # origin 2개
    "resolution: 0.05\norigin: [0, 'a', 0]\n",       # 숫자 아님
    "resolution: true\norigin: [0, 0, 0]\n",         # bool
    "resolution: .nan\norigin: [0, 0, 0]\n",         # NaN
    "- just\n- a list\n",                           # 매핑 아님
    "resolution: [0.05\n",                          # 깨진 yaml
])
def test_parse_map_yaml_rejects(bad_yaml):
    with pytest.raises(BadRequest) as error:
        parse_map_yaml(bad_yaml)
    assert error.value.code == "map_yaml_invalid"


def test_to_png_converts_pgm():
    png_bytes, width_px, height_px = to_png(make_pgm())
    assert (width_px, height_px) == (82, 63)
    with Image.open(io.BytesIO(png_bytes)) as image:
        assert image.format == "PNG" and image.mode == "L" and image.size == (82, 63)
        assert image.getpixel((0, 31)) == 0 and image.getpixel((0, 0)) == 254   # 벽·빈 곳이 그대로


def test_to_png_rejects_non_image_and_too_large():
    with pytest.raises(BadRequest) as error:
        to_png(b"not an image")
    assert error.value.code == "map_image_invalid"
    with pytest.raises(BadRequest) as error:
        to_png(make_pgm(MAP_IMAGE_MAX_SIDE_PX + 1, 2))
    assert error.value.code == "map_file_too_large"
