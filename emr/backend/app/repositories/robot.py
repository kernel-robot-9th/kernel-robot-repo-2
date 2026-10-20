# =============================================================================
# 파일   : app/repositories/robot.py
# 역할   : 로봇 조회
# 작성일 : 2026-10-14
# 구성   :
#   - RobotRepository  list_filtered, get_by_name, get_by_api_key_hash, lock, delete
# =============================================================================
from __future__ import annotations

from sqlalchemy import select

from app.models.robot import Robot
from app.repositories.base import BaseRepository


class RobotRepository(BaseRepository[Robot]):
    """robots 접근."""

    model = Robot

    def list_filtered(
        self, robot_type: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
    ) -> list[Robot]:
        """로봇 목록, id 순.
        [입력] robot_type·status: 있으면 그것만 / limit / offset
        [출력] list[Robot]
        """
        statement = select(Robot)
        if robot_type:
            statement = statement.where(Robot.robot_type == robot_type)
        if status:
            statement = statement.where(Robot.status == status)
        return list(self.db.scalars(statement.order_by(Robot.id).limit(limit).offset(offset)))

    def get_by_name(self, name: str) -> Robot | None:
        """이름으로 조회 (중복 검사).
        [입력] name
        [출력] Robot | None
        """
        return self.db.scalar(select(Robot).where(Robot.name == name))

    def get_by_api_key_hash(self, api_key_hash: str) -> Robot | None:
        """API 키 해시로 조회 (로봇 인증).
        [입력] api_key_hash: sha256 hex
        [출력] Robot | None
        """
        return self.db.scalar(select(Robot).where(Robot.api_key_hash == api_key_hash))

    def lock(self, robot_id: int) -> Robot | None:
        """로봇 행을 잠가 다시 읽는다 — 같은 로봇의 claim이 동시에 두 번 들어와도 한 번씩 처리되게.
        [입력] robot_id
        [출력] Robot | None
        """
        statement = (
            select(Robot).where(Robot.id == robot_id).with_for_update().execution_options(populate_existing=True)
        )
        return self.db.scalar(statement)

    def delete(self, robot: Robot) -> None:
        """행 삭제.
        [입력] robot
        [출력] 없음
        """
        self.db.delete(robot)
        self.db.flush()
