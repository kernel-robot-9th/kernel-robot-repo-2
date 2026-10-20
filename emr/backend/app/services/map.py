# =============================================================================
# 파일   : app/services/map.py
# 역할   : 맵(파일 이름·맵 정보·맵 이미지) 관리
# 작성일 : 2026-10-14
# 구성   :
#   - MapFile     업로드 파일 하나 (이름 + 바이트)
#   - MapService  list/get/create/update/delete, create_from_files/replace_files/get_image (2026-10-19)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.map import Map
from app.repositories.map import MapRepository
from app.services.map_files import MapYamlInfo, ensure_size, parse_map_yaml, to_png
from app.schemas.map import MapCreate, MapUpdate


MAP_NAME_MAX_LENGTH = 64
MAP_FILE_NAME_MAX_LENGTH = 128


@dataclass(frozen=True)
class MapFile:
    """업로드한 파일 하나. API 계층이 multipart에서 꺼내 넘긴다 (서비스는 HTTP를 모른다)."""

    file_name: str
    content: bytes


class MapService:
    """맵 관리 — 등록·편집·조회·삭제. 장소가 쓰는 맵은 삭제할 수 없다."""

    def __init__(self, db: Session) -> None:
        self.repo = MapRepository(db)

    def list(self, limit: int = 100, offset: int = 0) -> list[Map]:
        """맵 목록.
        [입력] limit / offset
        [출력] list[Map]: 이름 순
        """
        return self.repo.list_by_name(limit, offset)

    def get(self, map_id: int) -> Map:
        """한 건 조회.
        [입력] map_id
        [출력] Map (없으면 NotFound)
        """
        map_ = self.repo.get(map_id)
        if map_ is None:
            raise NotFound(f"map {map_id} not found", code="map_not_found")
        return map_

    def create(self, data: MapCreate) -> Map:
        """맵 등록. 이름·파일 이름 중복이면 Conflict.
        [입력] data
        [출력] Map
        """
        self._ensure_unique(data.name, data.file_name)
        return self.repo.add(Map(**data.model_dump()))

    def update(self, map_id: int, data: MapUpdate) -> Map:
        """보낸 필드만 수정. null로 보낸 필드는 무시한다.
        [입력] map_id / data
        [출력] Map (이름·파일 이름이 다른 맵과 겹치면 Conflict)
        """
        map_ = self.get(map_id)
        changes = data.model_dump(exclude_none=True)
        self._ensure_unique(changes.get("name"), changes.get("file_name"), exclude_id=map_id)
        for field, value in changes.items():
            setattr(map_, field, value)
        return map_

    def delete(self, map_id: int) -> None:
        """맵 삭제. 장소가 쓰고 있으면 Conflict.
        [입력] map_id
        [출력] 없음
        """
        map_ = self.get(map_id)
        if self.repo.is_used_by_location(map_id):
            raise Conflict(f"map {map_id} is used by locations", code="map_in_use")
        self.repo.delete(map_)

    def _ensure_unique(self, name: str | None, file_name: str | None, exclude_id: int | None = None) -> None:
        """이름·파일 이름이 다른 맵과 겹치지 않는지 확인.
        [입력] name / file_name: None이면 검사 안 함 / exclude_id: 자기 자신
        [출력] 없음 (겹치면 Conflict)
        """
        if name is not None:
            same_name = self.repo.get_by_name(name)
            if same_name is not None and same_name.id != exclude_id:
                raise Conflict(f"map name {name} already exists", code="map_name_duplicate")
        if file_name is not None:
            same_file = self.repo.get_by_file_name(file_name)
            if same_file is not None and same_file.id != exclude_id:
                raise Conflict(f"map file_name {file_name} already exists", code="map_file_name_duplicate")

    def create_from_files(self, name: str, map_yaml: MapFile, map_image: MapFile) -> Map:
        """map_server yaml + 이미지로 맵 등록. resolution·origin은 yaml에서 읽는다.
        [입력] name: 맵 이름 / map_yaml: yaml 파일 (file_name이 maps.file_name) / map_image: PGM·PNG
        [출력] Map (형식 오류 BadRequest, 이름·파일 이름 중복 Conflict)
        """
        name = name.strip()
        if not 1 <= len(name) <= MAP_NAME_MAX_LENGTH:
            raise BadRequest(f"map name must be 1..{MAP_NAME_MAX_LENGTH} characters", code="map_name_invalid")
        yaml_file_name = self._file_name(map_yaml)
        info = self._read_yaml(map_yaml)
        png_bytes, width_px, height_px = self._read_image(map_image)
        self._ensure_unique(name, yaml_file_name)
        robot_map = Map(name=name, file_name=yaml_file_name)
        self._apply_files(robot_map, info, map_image, png_bytes, width_px, height_px)
        return self.repo.add(robot_map)

    def replace_files(self, map_id: int, map_yaml: MapFile, map_image: MapFile) -> Map:
        """맵을 다시 만들었을 때 yaml·이미지 교체. 장소 좌표는 그대로 둔다 — 좌표계(원점)가 바뀌었으면 장소를 다시 찍어야 한다.
        [입력] map_id / map_yaml / map_image
        [출력] Map (없으면 NotFound, 형식 오류 BadRequest, 파일 이름이 다른 맵과 겹치면 Conflict)
        """
        robot_map = self.get(map_id)
        yaml_file_name = self._file_name(map_yaml)
        info = self._read_yaml(map_yaml)
        png_bytes, width_px, height_px = self._read_image(map_image)
        self._ensure_unique(None, yaml_file_name, exclude_id=map_id)
        robot_map.file_name = yaml_file_name
        self._apply_files(robot_map, info, map_image, png_bytes, width_px, height_px)
        self.repo.db.flush()   # updated_at(onupdate)을 확정해 응답에 새 값이 나가게
        return robot_map

    def get_image(self, map_id: int) -> bytes:
        """맵 이미지(PNG).
        [입력] map_id
        [출력] bytes (맵이 없으면 map_not_found, 이미지가 없으면 map_image_not_found — 둘 다 NotFound)
        """
        robot_map = self.get(map_id)
        if robot_map.image_png is None:
            raise NotFound(f"map {map_id} has no image", code="map_image_not_found")
        return robot_map.image_png

    @staticmethod
    def _file_name(map_file: MapFile) -> str:
        """업로드 파일 이름 확인 (경로는 떼고 이름만).
        [입력] map_file  [출력] str (비었거나 너무 길면 BadRequest)
        """
        file_name = map_file.file_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not 1 <= len(file_name) <= MAP_FILE_NAME_MAX_LENGTH:
            raise BadRequest(f"file name must be 1..{MAP_FILE_NAME_MAX_LENGTH} characters", code="map_file_name_invalid")
        return file_name

    @staticmethod
    def _read_yaml(map_yaml: MapFile) -> MapYamlInfo:
        """yaml 파일 → 값.
        [입력] map_yaml  [출력] MapYamlInfo (BadRequest)
        """
        ensure_size(map_yaml.content, "map yaml")
        try:
            yaml_text = map_yaml.content.decode("utf-8")
        except UnicodeDecodeError:
            raise BadRequest("map yaml must be UTF-8 text", code="map_yaml_invalid") from None
        return parse_map_yaml(yaml_text)

    @staticmethod
    def _read_image(map_image: MapFile) -> tuple[bytes, int, int]:
        """이미지 파일 → PNG·크기.
        [입력] map_image  [출력] (png, width_px, height_px) (BadRequest)
        """
        ensure_size(map_image.content, "map image")
        return to_png(map_image.content)

    def _apply_files(
        self, robot_map: Map, info: MapYamlInfo, map_image: MapFile, png_bytes: bytes, width_px: int, height_px: int,
    ) -> None:
        """yaml 값과 이미지를 맵에 넣는다.
        [입력] robot_map / info / map_image: 원래 이름용 / png_bytes / width_px / height_px
        [출력] 없음
        """
        robot_map.resolution_m_per_pixel = info.resolution_m_per_pixel
        robot_map.origin_x_m = info.origin_x_m
        robot_map.origin_y_m = info.origin_y_m
        robot_map.origin_yaw_rad = info.origin_yaw_rad
        robot_map.image_png = png_bytes
        robot_map.image_width_px = width_px
        robot_map.image_height_px = height_px
        robot_map.image_file_name = self._file_name(map_image)
