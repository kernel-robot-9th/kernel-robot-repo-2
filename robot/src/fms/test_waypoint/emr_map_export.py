#!/usr/bin/env python3
# =============================================================================
# 파일   : emr_map_export.py
# 역할   : EMR에 저장된 맵을 Nav2 map_server용 yaml + png로 꺼낸다 — 로봇에 맵 파일이 없을 때 EMR과 같은 좌표계로 넘기기
# 작성일 : 2026-10-20
# 구성   :
#   - find_map()        EMR 맵 목록에서 id 또는 이름으로 찾기
#   - build_map_yaml()  map_server yaml 내용 (resolution·origin은 EMR 값 그대로)
#   - main()            GET /maps, /maps/{id}/image → <출력 폴더>/<원래 yaml 이름>.yaml + .png
# EMR은 업로드 때 원본 pgm을 크기·픽셀 값 그대로 흑백 PNG로 저장한다(emr/backend/app/services/map_files.py) → 픽셀이 같다.
# EMR이 저장하지 않는 mode·negate·thresh는 Pinky 맵(pinky_navigation/map/*.yaml)과 같은 값을 쓴다:
#   trinary, negate 0, occupied 0.65, free 0.25 — 이미지 값 0(벽)·205(모름)·254(빈 곳)를 Pinky 맵과 똑같이 읽는다.
# 표준 라이브러리만 쓴다.
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_EMR_URL = "http://localhost:8000/api/v1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def find_map(maps: list[dict[str, Any]], map_key: str) -> dict[str, Any]:
    """EMR 맵을 id(숫자) 또는 이름으로 찾는다.
    [입력] maps: GET /maps 응답 / map_key: "4" 또는 "병원"
    [출력] dict: 맵 (없거나 이미지가 없으면 ValueError)
    """
    matches = [item for item in maps if str(item["id"]) == map_key or item["name"] == map_key]
    if not matches:
        available = ", ".join(f"{item['id']}={item['name']}" for item in maps) or "(없음)"
        raise ValueError(f"EMR에 '{map_key}' 맵이 없습니다 — 있는 맵: {available}")
    found = matches[0]
    if not found.get("has_image"):
        raise ValueError(f"'{found['name']}' 맵은 이미지가 없습니다(숫자만 등록됨). EMR에서 yaml과 이미지를 올려 주세요.")
    return found


def build_map_yaml(emr_map: dict[str, Any], image_file_name: str) -> str:
    """map_server yaml.
    [입력] emr_map: EMR 맵 / image_file_name: yaml 옆에 둘 이미지 파일 이름
    [출력] str: yaml 텍스트
    """
    return (
        f"# EMR 맵 '{emr_map['name']}'(id {emr_map['id']}, 원본 {emr_map['file_name']})에서 꺼냄 — emr_map_export.py\n"
        f"image: {image_file_name}\n"
        "mode: trinary\n"
        f"resolution: {emr_map['resolution_m_per_pixel']}\n"
        f"origin: [{emr_map['origin_x_m']}, {emr_map['origin_y_m']}, {emr_map['origin_yaw_rad']}]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.25\n"
    )


def main(argv: list[str] | None = None) -> int:
    """[입력] argv [출력] 종료 코드 0 성공 · 2 실패"""
    parser = argparse.ArgumentParser(description="EMR 맵을 Nav2 map_server용 yaml + png로 저장합니다.")
    parser.add_argument("map", help="EMR 맵 id 또는 이름 (예: 4, 병원)")
    parser.add_argument("output_dir", help="저장할 폴더 (없으면 만든다)")
    parser.add_argument("--emr", default=DEFAULT_EMR_URL, help=f"EMR API 주소 (기본 {DEFAULT_EMR_URL})")
    args = parser.parse_args(argv)
    emr_url = args.emr.rstrip("/")

    try:
        with urllib.request.urlopen(f"{emr_url}/maps", timeout=10) as response:
            maps = json.loads(response.read().decode("utf-8"))
        emr_map = find_map(maps, args.map)
        with urllib.request.urlopen(f"{emr_url}/maps/{emr_map['id']}/image", timeout=30) as response:
            image_bytes = response.read()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as error:
        print(f"EMR에서 맵을 받지 못했습니다 ({emr_url}): {error}", file=sys.stderr)
        return 2
    if not image_bytes.startswith(PNG_SIGNATURE):
        print("EMR이 PNG가 아닌 응답을 줬습니다.", file=sys.stderr)
        return 2

    stem = Path(emr_map["file_name"]).stem or f"emr_map_{emr_map['id']}"
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{stem}.png"
    yaml_path = output_dir / f"{stem}.yaml"
    image_path.write_bytes(image_bytes)
    yaml_path.write_text(build_map_yaml(emr_map, image_path.name), encoding="utf-8")
    print(f"저장: {yaml_path}")
    print(f"      {image_path} ({emr_map['image_width_px']}x{emr_map['image_height_px']} px, "
          f"{emr_map['resolution_m_per_pixel']} m/px, 원점 {emr_map['origin_x_m']}, {emr_map['origin_y_m']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
