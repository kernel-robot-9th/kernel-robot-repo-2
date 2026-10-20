# =============================================================================
# 파일   : app/repositories/location.py
# 역할   : 장소 조회·삭제
# 작성일 : 2026-10-14
# 구성   :
#   - LocationRepository  list_by_name, get_by_name, is_used_by_delivery, is_robot_home(2026-10-20), delete
# =============================================================================
from __future__ import annotations

from sqlalchemy import exists, select

from app.models.delivery import Delivery
from app.models.robot import Robot
from app.models.location import Location
from app.repositories.base import BaseRepository


class LocationRepository(BaseRepository[Location]):
    """locations 접근."""

    model = Location

    def list_by_name(self, limit: int = 100, offset: int = 0) -> list[Location]:
        """장소 목록, 이름 순.
        [입력] limit / offset
        [출력] list[Location]
        """
        return list(self.db.scalars(select(Location).order_by(Location.name).limit(limit).offset(offset)))

    def get_by_name(self, name: str) -> Location | None:
        """이름으로 조회 (중복 검사).
        [입력] name
        [출력] Location | None
        """
        return self.db.scalar(select(Location).where(Location.name == name))

    def is_used_by_delivery(self, location_id: int) -> bool:
        """이 장소를 배송 위치로 쓰는 예약이 있는가 (상태 무관).
        [입력] location_id
        [출력] bool
        """
        return bool(self.db.scalar(select(exists().where(Delivery.destination_location_id == location_id))))

    def is_robot_home(self, location_id: int) -> bool:
        """이 장소를 복귀 장소로 쓰는 로봇이 있는가 (2026-10-20).
        [입력] location_id
        [출력] bool
        """
        return bool(self.db.scalar(select(exists().where(Robot.home_location_id == location_id))))

    def delete(self, location: Location) -> None:
        """행 삭제.
        [입력] location
        [출력] 없음
        """
        self.db.delete(location)
        self.db.flush()
