# =============================================================================
# 파일   : app/repositories/map.py
# 역할   : 맵 조회·삭제
# 작성일 : 2026-10-14
# 구성   :
#   - MapRepository  list_by_name, get_by_name, get_by_file_name, is_used_by_location, delete
# =============================================================================
from __future__ import annotations

from sqlalchemy import exists, select

from app.models.location import Location
from app.models.map import Map
from app.repositories.base import BaseRepository


class MapRepository(BaseRepository[Map]):
    """maps 접근."""

    model = Map

    def list_by_name(self, limit: int = 100, offset: int = 0) -> list[Map]:
        """맵 목록, 이름 순.
        [입력] limit / offset
        [출력] list[Map]
        """
        return list(self.db.scalars(select(Map).order_by(Map.name).limit(limit).offset(offset)))

    def get_by_name(self, name: str) -> Map | None:
        """이름으로 조회 (중복 검사).
        [입력] name
        [출력] Map | None
        """
        return self.db.scalar(select(Map).where(Map.name == name))

    def get_by_file_name(self, file_name: str) -> Map | None:
        """파일 이름으로 조회 (중복 검사).
        [입력] file_name
        [출력] Map | None
        """
        return self.db.scalar(select(Map).where(Map.file_name == file_name))

    def is_used_by_location(self, map_id: int) -> bool:
        """이 맵을 쓰는 장소가 있는가.
        [입력] map_id
        [출력] bool
        """
        return bool(self.db.scalar(select(exists().where(Location.map_id == map_id))))

    def delete(self, map_: Map) -> None:
        """행 삭제.
        [입력] map_
        [출력] 없음
        """
        self.db.delete(map_)
        self.db.flush()
