# =============================================================================
# 파일   : app/services/robot.py
# 역할   : 로봇 등록·이름·상태 관리
# 작성일 : 2026-10-14
# 구성   :
#   - RobotService  list/get/create/update/delete, issue_api_key/revoke_api_key (로봇 전용 API용 로봇별 키)
#                   update: 이름·상태·로봇 서버 주소 (복귀 장소는 2026-10-27 없앰 — 팀원 FMS가 정함). delete: 진행 중 배송이 있으면 409
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, NotFound
from app.core.security import generate_robot_api_key, hash_api_key
from app.models.enums import RobotStatus, RobotType
from app.models.robot import Robot
from app.repositories.delivery import DeliveryRepository
from app.repositories.robot import RobotRepository
from app.schemas.robot import RobotCreate, RobotUpdate

log = structlog.get_logger(__name__)


class RobotService:
    """로봇 등록·조회·수정·삭제·API 키 관리. 종류는 등록 때만 정한다.
    삭제는 행을 지운다 — 수령 기록(deliveries.received_by_robot_id)은 NULL이 되고 키도 함께 사라진다.
    """

    def __init__(self, db: Session) -> None:
        self.repo = RobotRepository(db)
        self.deliveries = DeliveryRepository(db)

    def list(
        self, robot_type: RobotType | None = None, status: RobotStatus | None = None, limit: int = 100, offset: int = 0,
    ) -> list[Robot]:
        """로봇 목록.
        [입력] robot_type·status: 있으면 그것만 / limit / offset
        [출력] list[Robot]: id 순
        """
        return self.repo.list_filtered(robot_type, status, limit, offset)

    def get(self, robot_id: int) -> Robot:
        """한 건 조회.
        [입력] robot_id
        [출력] Robot (없으면 NotFound)
        """
        robot = self.repo.get(robot_id)
        if robot is None:
            raise NotFound(f"robot {robot_id} not found", code="robot_not_found")
        return robot

    def create(self, data: RobotCreate) -> Robot:
        """로봇 등록. 이름 중복이면 Conflict.
        [입력] data
        [출력] Robot: status=idle
        """
        if self.repo.get_by_name(data.name):
            raise Conflict(f"robot name {data.name} already exists", code="robot_name_duplicate")
        return self.repo.add(Robot(name=data.name, robot_type=data.robot_type, status=RobotStatus.IDLE))

    def update(self, robot_id: int, data: RobotUpdate) -> Robot:
        """보낸 필드만 수정. null로 보낸 필드는 무시한다.
        [입력] robot_id / data
        [출력] Robot (바꾸려는 이름이 이미 있으면 Conflict)
        """
        robot = self.get(robot_id)
        changes = data.model_dump(exclude_none=True)
        if "name" in changes and changes["name"] != robot.name and self.repo.get_by_name(changes["name"]):
            raise Conflict(f"robot name {changes['name']} already exists", code="robot_name_duplicate")
        for field, value in changes.items():
            setattr(robot, field, value)
        return robot

    def delete(self, robot_id: int) -> None:
        """로봇 삭제. 진행 중(preparing·dispatched·arrived) 배송을 맡고 있으면 Conflict — 끝난 배송의 로봇 칸은 NULL이 된다.
        [입력] robot_id
        [출력] 없음 (없으면 NotFound)
        """
        # [검토 필요] 수령 기록이 로봇을 참조하게 됐다(삭제 시 NULL). 어느 로봇이 확인했는지 남겨야 하면 행 삭제 대신 비활성화로 바꿔야 한다.
        robot = self.get(robot_id)
        if self.deliveries.get_active_for_robot(robot_id) is not None:
            raise Conflict(f"robot {robot_id} has an active delivery", code="robot_has_active_delivery")
        self.repo.delete(robot)

    def issue_api_key(self, robot_id: int) -> tuple[Robot, str]:
        """키 발급·재발급. 이전 키는 즉시 쓸 수 없게 된다.
        [입력] robot_id
        [출력] (Robot, 평문 키) — 평문은 응답으로 한 번만 돌려주고 저장·로그하지 않는다 (없으면 NotFound)
        """
        robot = self.get(robot_id)
        raw_api_key = generate_robot_api_key()
        robot.api_key_hash = hash_api_key(raw_api_key)
        robot.api_key_issued_at = datetime.now(UTC)
        log.info("robot_api_key_issued", robot_id=robot.id)
        return robot, raw_api_key

    def revoke_api_key(self, robot_id: int) -> None:
        """키 폐기. 이후 그 로봇의 요청은 401.
        [입력] robot_id
        [출력] 없음 (없으면 NotFound. 키가 이미 없어도 성공)
        """
        robot = self.get(robot_id)
        robot.api_key_hash = None
        robot.api_key_issued_at = None
        log.info("robot_api_key_revoked", robot_id=robot.id)
