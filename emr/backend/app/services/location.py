# =============================================================================
# 파일   : app/services/location.py
# 역할   : 장소(배송 위치·맵 좌표) 관리
# 작성일 : 2026-10-14
# 구성   :
#   - LocationService  list/get/create/update/delete
# =============================================================================
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.location import Location
from app.repositories.location import LocationRepository
from app.repositories.map import MapRepository
from app.schemas.location import LocationCreate, LocationUpdate


class LocationService:
    """장소 관리 — 등록·편집·조회·삭제. 예약이 참조하는 장소는 삭제할 수 없다."""

    def __init__(self, db: Session) -> None:
        self.repo = LocationRepository(db)
        self.maps = MapRepository(db)

    def list(self, limit: int = 100, offset: int = 0) -> list[Location]:
        """장소 목록.
        [입력] limit / offset
        [출력] list[Location]: 이름 순
        """
        return self.repo.list_by_name(limit, offset)

    def get(self, location_id: int) -> Location:
        """한 건 조회.
        [입력] location_id
        [출력] Location (없으면 NotFound)
        """
        location = self.repo.get(location_id)
        if location is None:
            raise NotFound(f"location {location_id} not found", code="location_not_found")
        return location

    def create(self, data: LocationCreate) -> Location:
        """장소 등록. 이름 중복이면 Conflict.
        [입력] data
        [출력] Location
        """
        if self.repo.get_by_name(data.name):
            raise Conflict(f"location name {data.name} already exists", code="location_name_duplicate")
        self._check_robot_dest(data.robot_dest, None)
        location = Location(**data.model_dump())
        location.admin_note = location.admin_note or None   # 빈 메모는 없음으로
        self._validate_map(location)
        return self.repo.add(location)

    def update(self, location_id: int, data: LocationUpdate) -> Location:
        """보낸 필드만 수정. null로 보낸 필드는 무시한다 (좌표를 지우는 기능은 없다).
        [입력] location_id / data
        [출력] Location (바꾸려는 이름이 이미 있으면 Conflict, 맵 없이 좌표만 있으면 BadRequest)
        """
        location = self.get(location_id)
        changes = data.model_dump(exclude_none=True)
        if "name" in changes and changes["name"] != location.name and self.repo.get_by_name(changes["name"]):
            raise Conflict(f"location name {changes['name']} already exists", code="location_name_duplicate")
        self._check_robot_dest(changes.get("robot_dest"), location.id)
        for field, value in changes.items():
            setattr(location, field, value)
        if changes.get("admin_note") == "":   # 관리자 메모는 빈 문자열로 지운다 (2026-10-30)
            location.admin_note = None
        self._validate_map(location)
        return location

    def delete(self, location_id: int) -> None:
        """장소 삭제. 예약(취소된 것 포함)이나 병상 단말이 참조하면 Conflict.
        예전 복귀 장소(2026-10-27부터 안 씀)로 남아 있으면 그 로봇의 값을 비우고 지운다 — DB 칸은 남겨 두어 FK RESTRICT가 막지 않게.
        [입력] location_id
        [출력] 없음
        """
        location = self.get(location_id)
        self.repo.clear_robot_home(location_id)
        if self.repo.is_bedside_room(location_id):   # 2026-10-22
            raise Conflict(f"location {location_id} is a bedside room", code="location_is_bedside_room")
        if self.repo.is_used_by_delivery(location_id):
            raise Conflict(f"location {location_id} is used by deliveries", code="location_in_use")
        self.repo.delete(location)

    def _check_robot_dest(self, robot_dest: str | None, location_id: int | None) -> None:
        """로봇 목적지 이름은 장소 하나에만 (2026-10-22). [입력] robot_dest / location_id: 수정 중인 장소 [출력] 없음 (겹치면 Conflict)"""
        if robot_dest is None:
            return
        other = self.repo.get_by_robot_dest(robot_dest)
        if other is not None and other.id != location_id:
            raise Conflict(f"robot_dest {robot_dest} is already used by location {other.id}", code="location_robot_dest_duplicate")

    def _validate_map(self, location: Location) -> None:
        """변경이 반영된 최종 상태로 맵을 검사: map_id가 있으면 존재해야 하고, 좌표가 있으면 맵이 있어야 한다.
        관계(location.map)도 함께 맞춰 응답에 옛 맵이 남지 않게 한다.
        [입력] location: 변경이 반영된 장소
        [출력] 없음 (BadRequest)
        """
        if location.map_id is not None:
            map_ = self.maps.get(location.map_id)
            if map_ is None:
                raise BadRequest(f"map {location.map_id} not found", code="map_not_found")
            location.map = map_
        elif location.map_x_m is not None:
            raise BadRequest("map_id is required when map pose is given", code="map_id_required")
