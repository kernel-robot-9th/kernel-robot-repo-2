# =============================================================================
# 파일   : app/services/quick_dispatch.py
# 역할   : v2 간단 API — 시험용으로 절차를 건너뛴다 (2026-10-22, 사용자: "상태를 받기에 절차가 너무 많아, 테스트를 못 하고 있어")
# 작성일 : 2026-10-22
# 구성   :
#   - QuickDispatchService.set_status()  배송을 원하는 단계로 바로 (사이 단계는 자동으로 채움 — 출발 로봇·시각, 도착 마커, 수령)
#   - record_robot_status()/robot_statuses()  로봇이 아무 때나 보내는 상태를 메모리에 마지막 값만 보관 (저장 안 함)
# v1 규칙(예약 시각·claim·맡은 로봇·마커)은 그대로 두고 여기서만 건너뛴다. 알림·배송 기록·재고 복구는 v1 서비스를 그대로 쓴다.
# 설정 QUICK_API_ENABLED=1일 때만 열린다(app/api/v2/quick.py)
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import Conflict, NotFound
from app.models.delivery import Delivery
from app.models.enums import DeliveryEventType, DeliveryFailureReason, DeliveryStatus
from app.repositories.delivery import DeliveryRepository
from app.repositories.robot import RobotRepository
from app.services.dispatch import STAGE_ARRIVED, DispatchService

ORDER = [DeliveryStatus.RESERVED, DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED, DeliveryStatus.RECEIVED]
FINISHED = {DeliveryStatus.RECEIVED, DeliveryStatus.FAILED, DeliveryStatus.CANCELLED}

_robot_statuses: dict[int, dict[str, Any]] = {}   # 로봇 id → 마지막 상태 (프로세스 메모리, 재시작하면 비어 있음)


def record_robot_status(robot_id: int, status: dict[str, Any]) -> dict[str, Any]:
    """[입력] robot_id / status: 로봇이 보낸 그대로 [출력] 보관한 값 (+ robot_id, received_at)"""
    saved = {**status, "robot_id": robot_id, "received_at": datetime.now(UTC).isoformat()}
    _robot_statuses[robot_id] = saved
    return saved


def robot_statuses() -> list[dict[str, Any]]:
    """[출력] 로봇별 마지막 상태 (id 순)"""
    return [_robot_statuses[robot_id] for robot_id in sorted(_robot_statuses)]


class QuickDispatchService:
    """배송 상태를 바로 바꾼다 — 시험용."""

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryRepository(db)
        self.robots = RobotRepository(db)
        self.dispatch = DispatchService(db)

    def set_status(self, delivery_id: int, target: DeliveryStatus, robot_id: int | None = None,
                   failure_reason: DeliveryFailureReason | None = None) -> Delivery:
        """reserved → dispatched → arrived → received 중 target까지 차례로(사이 단계 자동), 또는 failed.
        [입력] delivery_id / target / robot_id: 맡길 로봇(없으면 이미 맡은 로봇, 그것도 없으면 ROBOT_KEY_DISABLED_AS)
               / failure_reason: failed일 때 (없으면 robot_error)
        [출력] Delivery (없으면 404, 이미 끝난 배송이면 409 delivery_finished, 로봇이 다른 배송 중이면 409 robot_busy)
        """
        delivery = self.repo.get_with_items(delivery_id, lock=True)
        if delivery is None:
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.status == target:
            return delivery
        if delivery.status in FINISHED:
            raise Conflict(f"delivery {delivery_id} is already {delivery.status}", code="delivery_finished")
        robot_id = robot_id or delivery.assigned_robot_id or settings.ROBOT_KEY_DISABLED_AS
        if delivery.status == DeliveryStatus.RESERVED:
            self._dispatch(delivery, robot_id)
        if target == DeliveryStatus.FAILED:
            return self.dispatch.report_progress(delivery.id, delivery.assigned_robot_id, "failed",
                                                 failure_reason or DeliveryFailureReason.ROBOT_ERROR)
        if ORDER.index(target) >= ORDER.index(DeliveryStatus.ARRIVED) and delivery.status == DeliveryStatus.DISPATCHED:
            delivery = self.dispatch.report_progress(delivery.id, delivery.assigned_robot_id, STAGE_ARRIVED, None)
        if target == DeliveryStatus.RECEIVED and delivery.status == DeliveryStatus.ARRIVED:
            self._receive(delivery)
        return delivery

    def _dispatch(self, delivery: Delivery, robot_id: int) -> None:
        """claim 없이 바로 출발 (예약 시각·맵 검사 없음). 로봇은 진행 중 배송 하나만."""
        robot = self.robots.get(robot_id)
        if robot is None:
            raise NotFound(f"robot {robot_id} not found", code="robot_not_found")
        active = self.repo.get_active_for_robot(robot.id)
        if active is not None and active.id != delivery.id:
            raise Conflict(f"robot {robot.id} is busy with delivery {active.id}", code="robot_busy")
        now = datetime.now(UTC)
        delivery.status = DeliveryStatus.DISPATCHED
        delivery.assigned_robot_id = robot.id
        delivery.assigned_robot = robot
        delivery.dispatched_at = now
        self.dispatch.notifier.notify_dispatched(delivery)
        self.dispatch.events.record_by_robot(delivery, DeliveryEventType.DISPATCHED, robot, now)

    def _receive(self, delivery: Delivery) -> None:
        """마커·버튼 없이 바로 수령 (받은 간호사 = 예약 간호사, 병상 배송은 간호사 없음)."""
        now = datetime.now(UTC)
        delivery.status = DeliveryStatus.RECEIVED
        delivery.received_at = now
        delivery.received_by_nurse_id = delivery.nurse_id
        delivery.received_by_robot_id = delivery.assigned_robot_id
        self.dispatch.notifier.notify_received(delivery)
        self.dispatch.events.record_by_robot(delivery, DeliveryEventType.RECEIVED, delivery.assigned_robot, now)
