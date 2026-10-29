# =============================================================================
# 파일   : app/services/map_files.py
# 역할   : 맵 파일 해석 — ROS map_server yaml(resolution·origin)과 맵 이미지(PGM·PNG → PNG). DB를 모르는 순수 함수
# 작성일 : 2026-10-19
# 구성   :
#   - MAP_FILE_MAX_BYTES / MAP_IMAGE_MAX_SIDE_PX   업로드 한도
#   - MapYamlInfo        yaml에서 읽은 값
#   - parse_map_yaml()   yaml 텍스트 → MapYamlInfo (형식이 틀리면 BadRequest map_yaml_invalid)
#   - to_png()           이미지 바이트 → (PNG, 가로, 세로) — 흑백 맵은 흑백, 색 있는 평면도는 색 그대로(2026-10-29) (BadRequest map_image_invalid·map_file_too_large)
# Pinky Pro(slam_toolbox map_saver_cli) 맵: image: my_map.pgm / resolution: 0.05 / origin: [-2.05, -1.62, 0]
# =============================================================================
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import yaml
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import BadRequest

MAP_FILE_MAX_BYTES = 10 * 1024 * 1024   # 파일 하나 10MB
MAP_IMAGE_MAX_SIDE_PX = 4000            # 0.05 m/px면 한 변 200 m — 병동 하나는 충분
GRAYSCALE_IMAGE_MODES = frozenset({"1", "L", "LA", "I", "I;16", "F"})   # PGM·흑백 PNG — 그 밖(RGB·RGBA·P 등)은 색으로 둔다


@dataclass(frozen=True)
class MapYamlInfo:
    """map_server yaml에서 쓰는 값. 나머지(mode·negate·thresh)는 화면 표시에 필요 없어 읽지 않는다."""

    resolution_m_per_pixel: float
    origin_x_m: float
    origin_y_m: float
    origin_yaw_rad: float
    image_name: str | None   # yaml의 image: 값. 올린 이미지 이름과 달라도 올린 이미지를 쓴다


def ensure_size(file_bytes: bytes, what: str) -> None:
    """업로드 파일 크기 확인.
    [입력] file_bytes / what: 오류 문구용 ("map yaml", "map image")
    [출력] 없음 (MAP_FILE_MAX_BYTES 초과면 BadRequest map_file_too_large)
    """
    if len(file_bytes) > MAP_FILE_MAX_BYTES:
        raise BadRequest(f"{what} is larger than {MAP_FILE_MAX_BYTES} bytes", code="map_file_too_large")


def _finite_number(value: object) -> float | None:
    """숫자(정수·실수, bool 제외)이고 유한하면 float, 아니면 None.
    [입력] value  [출력] float | None
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def parse_map_yaml(yaml_text: str) -> MapYamlInfo:
    """map_server yaml을 읽는다. resolution > 0, origin은 숫자 3개 [x_m, y_m, yaw_rad].
    [입력] yaml_text
    [출력] MapYamlInfo (형식이 틀리면 BadRequest map_yaml_invalid)
    """
    try:
        document = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        raise BadRequest(f"map yaml cannot be parsed: {error}", code="map_yaml_invalid") from None
    if not isinstance(document, dict):
        raise BadRequest("map yaml must be a mapping", code="map_yaml_invalid")
    resolution = _finite_number(document.get("resolution"))
    if resolution is None or resolution <= 0:
        raise BadRequest("map yaml needs resolution > 0", code="map_yaml_invalid")
    origin = document.get("origin")
    origin_numbers = [_finite_number(value) for value in origin] if isinstance(origin, list) else []
    if len(origin_numbers) != 3 or None in origin_numbers:
        raise BadRequest("map yaml needs origin: [x, y, yaw] (3 numbers)", code="map_yaml_invalid")
    image_name = document.get("image")
    return MapYamlInfo(
        resolution_m_per_pixel=resolution,
        origin_x_m=origin_numbers[0], origin_y_m=origin_numbers[1], origin_yaw_rad=origin_numbers[2],
        image_name=str(image_name) if image_name is not None else None,
    )


def to_png(image_bytes: bytes) -> tuple[bytes, int, int]:
    """맵 이미지(PGM P2·P5, PNG 등 Pillow가 읽는 형식)를 PNG로 바꾼다. 브라우저가 PGM을 못 그려서다.
    흑백 맵(ROS trinary)은 흑백(L), 색 있는 이미지(병원 평면도, 2026-10-29)는 색(RGB, 투명도는 버림)으로 둔다.
    [입력] image_bytes
    [출력] (png_bytes, width_px, height_px) (이미지가 아니면 map_image_invalid, 너무 크면 map_file_too_large)
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width_px, height_px = image.size
            if width_px > MAP_IMAGE_MAX_SIDE_PX or height_px > MAP_IMAGE_MAX_SIDE_PX:
                raise BadRequest(
                    f"map image {width_px}x{height_px} px exceeds {MAP_IMAGE_MAX_SIDE_PX} px", code="map_file_too_large",
                )
            # trinary 맵: 흰=빈 곳, 검정=벽, 회색=모름
            converted = image.convert("L" if image.mode in GRAYSCALE_IMAGE_MODES else "RGB")
            output = io.BytesIO()
            converted.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise BadRequest(f"map image cannot be read: {error}", code="map_image_invalid") from None
    if width_px <= 0 or height_px <= 0:
        raise BadRequest("map image is empty", code="map_image_invalid")
    return output.getvalue(), width_px, height_px
