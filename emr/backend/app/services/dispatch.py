# =============================================================================
# 파일   : app/services/dispatch.py
# 역할   : 배송 배정·진행 — 로봇(관제 PC 배송 실행기)이 부르는 쪽의 업무 규칙 (로드맵 2단계)
# 작성일 : 2026-10-20
# 구성   :
#   - DispatchService  overview(GET /robot/me), claim(배송 가져가기), report_progress(도착·실패 보고),
#                      confirm_receipt(일회용 마커로 수령 확인)
# 계약: docs/api_contract_delivery_2026-10-20.md. 상태 흐름은 app/models/enums.py DeliveryStatus
# 성공·거부 모두 structlog로 남긴다(어느 로봇이 어느 배송에 무엇을 했는지). 별도 기록 테이블은 4단계
# =============================================================================
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, Forbidden, NotFound
from app.models.delivery import RECEIPT_MARKER_ID_MAX, RECEIPT_MARKER_ID_MIN, RECEIPT_WAIT_SECONDS, Delivery
from app.models.enums import DeliveryFailureReason, DeliveryStatus, RobotType
from app.models.location import Location
from app.models.robot import Robot
from app.repositories.delivery import DeliveryRepository
from app.repositories.robot import RobotRepository
from app.services.delivery import DeliveryService
from app.services.delivery_notifier import DeliveryNotifier

log = structlog.get_logger(__name__)

STAGE_ARRIVED = "arrived"
STAGE_FAILED = "failed"

# 일회용 마커 번호를 고를 때 쓰는 난수 — 운영체제 난수원(예측하기 어렵게)
_marker_random = random.SystemRandom()


@dataclass
class RobotOverview:
    """GET /robot/me 내용."""
    robot: Robot
    home_location: Location | None   # 좌표까지 있는 복귀 장소. 없거나 좌표가 없으면 None
    active_delivery: Delivery | None
    receipt_wait_seconds: int


class DispatchService:
    """로봇이 배송을 가져가고(claim), 도착·실패를 보고하고, 일회용 마커로 수령을 확인한다."""

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryRepository(db)
        self.robots = RobotRepository(db)
        self.deliveries = DeliveryService(db)
        self.notifier = DeliveryNotifier(db)

    def overview(self, robot: Robot) -> RobotOverview:
        """로봇 자신의 정보 — 실행기가 시작·재시작할 때 이어서 할 일을 알려 준다.
        [입력] robot: 키로 확인된 로봇
        [출력] RobotOverview
        """
        return RobotOverview(
            robot=robot,
            home_location=self._usable_home(robot),
            active_delivery=self.repo.get_active_for_robot(robot.id),
            receipt_wait_seconds=RECEIPT_WAIT_SECONDS,
        )

    def claim(self, robot_id: int) -> Delivery | None:
        """배송 하나를 맡는다. 이미 맡은 배송이 있으면 그것을 그대로 돌려준다(멱등 — 응답을 잃어도 다시 부르면 된다).
        없으면 reserved이고 예약 시각이 지났고 목적지가 복귀 장소와 같은 맵에 좌표가 있는 것 중 가장 이른 것을 dispatched로.
        [입력] robot_id: 키로 확인된 로봇
        [출력] Delivery | None: 줄 것이 없으면 None (AMR이 아니면 Forbidden, 복귀 장소가 없으면 Conflict)
        """
        robot = self.robots.lock(robot_id)   # 같은 로봇의 claim이 겹쳐도 한 번씩
        if robot is None:
            raise NotFound(f"robot {robot_id} not found", code="robot_not_found")
        attempt = log.bind(robot_id=robot.id)
        if robot.robot_type != RobotType.AMR:
            attempt.warning("claim_rejected", code="robot_not_amr")
            raise Forbidden("only amr robots deliver", code="robot_not_amr")
        active = self.repo.get_active_for_robot(robot.id)
        if active is not None:
            return active
        home = self._usable_home(robot)
        if home is None:
            attempt.warning("claim_rejected", code="robot_home_not_set")
            raise Conflict("robot home location is not set or has no map coordinates", code="robot_home_not_set")
        now = datetime.now(UTC)
        delivery = self.repo.lock_next_claimable(now, home.map_id)
        if delivery is None:
            return None
        delivery.status = DeliveryStatus.DISPATCHED
        delivery.assigned_robot_id = robot.id
        delivery.assigned_robot = robot
        delivery.dispatched_at = now
        attempt.info("delivery_dispatched", delivery_id=delivery.id, destination_location_id=delivery.destination_location_id)
        self.notifier.notify_dispatched(delivery)
        return delivery

    def report_progress(
        self, delivery_id: int, robot_id: int, stage: str, failure_reason: DeliveryFailureReason | None,
    ) -> Delivery:
        """도착·실패 보고. 같은 보고를 두 번 해도 결과가 같다.
        dispatched→arrived: 일회용 마커 배정. dispatched·arrived→failed: 재고 복구.
        [입력] delivery_id / robot_id: 키로 확인된 로봇 / stage: arrived | failed / failure_reason: failed일 때
        [출력] Delivery (없으면 NotFound, 맡은 로봇이 아니면 Forbidden, 맞지 않는 전이면 Conflict)
        """
        attempt = log.bind(robot_id=robot_id, delivery_id=delivery_id, stage=stage)
        delivery = self.repo.get_with_items(delivery_id, lock=True)
        if delivery is None:
            attempt.warning("progress_rejected", code="delivery_not_found")
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.assigned_robot_id != robot_id:
            attempt.warning("progress_rejected", code="delivery_not_assigned_to_robot")
            raise Forbidden(f"delivery {delivery_id} is not assigned to this robot", code="delivery_not_assigned_to_robot")
        now = datetime.now(UTC)

        if stage == STAGE_ARRIVED:
            if delivery.status == DeliveryStatus.ARRIVED:
                return delivery
            if delivery.status != DeliveryStatus.DISPATCHED:
                return self._reject_transition(attempt, delivery, stage)
            # 마커를 먼저 고른다 — 고르는 조회가 자동 flush를 일으켜, 상태부터 바꾸면 마커 없는 arrived가 CHECK에 걸린다
            receipt_marker_id = self._pick_receipt_marker_id()
            delivery.status = DeliveryStatus.ARRIVED
            delivery.arrived_at = now
            delivery.receipt_marker_id = receipt_marker_id
            attempt.info("delivery_arrived")
            self.notifier.notify_arrived(delivery)
            return delivery

        # stage == failed
        if delivery.status == DeliveryStatus.FAILED:
            return delivery
        if delivery.status == DeliveryStatus.RECEIVED:
            attempt.info("progress_rejected", code="delivery_already_received")
            raise Conflict(f"delivery {delivery_id} is already received", code="delivery_already_received")
        if delivery.status not in (DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED):
            return self._reject_transition(attempt, delivery, stage)
        self.deliveries.restore_stock(delivery)
        delivery.status = DeliveryStatus.FAILED
        delivery.failed_at = now
        delivery.failure_reason = failure_reason
        attempt.info("delivery_failed", failure_reason=failure_reason)
        self.notifier.notify_failed(delivery)
        return delivery

    def confirm_receipt(self, delivery_id: int, aruco_marker_id: int, robot_id: int) -> Delivery:
        """수령 확인. 도착해 있고 이 로봇이 맡은 배송이며, 읽은 번호가 그 배송의 일회용 마커일 때만 received.
        간호사 고정 마커(0~49)로는 받을 수 없다(2026-10-20 결정). 받은 간호사 = 예약한 간호사. 재고는 예약 때 이미 뺐다.
        [입력] delivery_id / aruco_marker_id: 로봇 카메라가 읽은 번호 / robot_id: 키로 확인된 로봇
        [출력] Delivery: received (없으면 NotFound, 도착 전·끝난 배송이면 Conflict, 로봇·마커가 다르면 Forbidden)
        """
        attempt = log.bind(robot_id=robot_id, delivery_id=delivery_id, aruco_marker_id=aruco_marker_id)
        delivery = self.repo.get_with_items(delivery_id, lock=True)
        if delivery is None:
            attempt.warning("receipt_rejected", code="delivery_not_found")
            raise NotFound(f"delivery {delivery_id} not found", code="delivery_not_found")
        if delivery.status != DeliveryStatus.ARRIVED:
            attempt.warning("receipt_rejected", code="delivery_not_arrived", status=delivery.status)
            raise Conflict(f"delivery {delivery_id} is {delivery.status}; only arrived can be received", code="delivery_not_arrived")
        if delivery.assigned_robot_id != robot_id:
            attempt.warning("receipt_rejected", code="delivery_not_assigned_to_robot")
            raise Forbidden(f"delivery {delivery_id} is not assigned to this robot", code="delivery_not_assigned_to_robot")
        if aruco_marker_id != delivery.receipt_marker_id:
            attempt.warning("receipt_rejected", code="receipt_marker_not_for_delivery")
            raise Forbidden(f"aruco_marker_id {aruco_marker_id} is not this delivery's receipt marker", code="receipt_marker_not_for_delivery")
        delivery.status = DeliveryStatus.RECEIVED
        delivery.received_at = datetime.now(UTC)
        delivery.received_by_nurse_id = delivery.nurse_id
        delivery.received_by_robot_id = robot_id
        attempt.info("receipt_confirmed", nurse_id=delivery.nurse_id)
        self.notifier.notify_received(delivery)
        return delivery

    # ---- 내부 ----------------------------------------------------------------

    @staticmethod
    def _usable_home(robot: Robot) -> Location | None:
        """좌표까지 있는 복귀 장소.
        [입력] robot
        [출력] Location | None
        """
        home = robot.home_location
        if home is None or home.map_id is None or home.map_x_m is None:
            return None
        return home

    def _pick_receipt_marker_id(self) -> int:
        """지금 도착해 있는 다른 배송이 쓰지 않는 일회용 마커 번호를 무작위로 고른다.
        [입력] 없음
        [출력] int: RECEIPT_MARKER_ID_MIN~MAX (다 쓰고 있으면 Conflict — 동시에 200건 도착은 현실적으로 없다)
        """
        in_use = self.repo.arrived_receipt_marker_ids()
        free = [marker_id for marker_id in range(RECEIPT_MARKER_ID_MIN, RECEIPT_MARKER_ID_MAX + 1) if marker_id not in in_use]
        if not free:
            raise Conflict("all receipt markers are in use", code="receipt_marker_exhausted")
        return _marker_random.choice(free)

    @staticmethod
    def _reject_transition(attempt, delivery: Delivery, stage: str) -> Delivery:
        """맞지 않는 상태 전이 거부.
        [입력] attempt: 바인딩된 로거 / delivery / stage
        [출력] 없음 (항상 Conflict)
        """
        attempt.warning("progress_rejected", code="delivery_invalid_transition", status=delivery.status)
        raise Conflict(f"delivery {delivery.id} is {delivery.status}; cannot report {stage}", code="delivery_invalid_transition")
