# =============================================================================
# 파일   : app/services/dispatch.py
# 역할   : 배송 배정·진행 — 로봇(관제 PC 배송 실행기)이 부르는 쪽의 업무 규칙 (로드맵 2단계)
# 작성일 : 2026-10-20
# 구성   :
#   - DispatchService  overview(GET /robot/me), claim(배송 가져가기 — 2026-10-23부터 로봇 서버에 상태를 물어 배터리·오염도·주행 준비 검사),
#                      2026-10-27 사용자 결정: 복귀 장소를 쓰지 않는다(어디로 돌아갈지는 팀원 FMS가 정함) — claim은 로봇 목적지(robot_dest)가 있는 장소의 배송만
#                      report_progress(병실 도착·실패 보고), report_at_pharmacy(약제실 도착 — 로그만, 2026-10-27),
#                      confirm_receipt(일회용 마커로 수령 확인)
# 계약: docs/api_contract_delivery_2026-10-20.md. 상태 흐름은 app/models/enums.py DeliveryStatus
# 성공·거부 모두 structlog로 남긴다(어느 로봇이 어느 배송에 무엇을 했는지). 실제로 상태를 바꾼 출발·도착·수령·실패는
# 배송 기록(delivery_events)에도 남긴다 — 멱등 재보고·거부는 남기지 않음 (2026-10-21, 로드맵 4단계)
# =============================================================================
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import Conflict, Forbidden, NotFound
from app.models.delivery import RECEIPT_MARKER_ID_MAX, RECEIPT_MARKER_ID_MIN, RECEIPT_WAIT_SECONDS, Delivery
from app.models.enums import DeliveryEventType, DeliveryFailureReason, DeliveryRequester, DeliveryStatus, ReceiptMethod, RobotType
from app.models.robot import Robot
from app.repositories.delivery import DeliveryRepository
from app.repositories.robot import RobotRepository
from app.services.delivery import DeliveryService
from app.services.delivery_events import DeliveryEventRecorder
from app.services.delivery_notifier import DeliveryNotifier
from app.services.robot_status import ClaimSkipReason, RobotStatusService

log = structlog.get_logger(__name__)

STAGE_ARRIVED = "arrived"
STAGE_FAILED = "failed"
STAGE_AT_PHARMACY = "at_pharmacy"   # 로그용 — 배송 상태가 아니다 (2026-10-27)

# 일회용 마커 번호를 고를 때 쓰는 난수 — 운영체제 난수원(예측하기 어렵게)
_marker_random = random.SystemRandom()


@dataclass
class RobotOverview:
    """GET /robot/me 내용."""
    robot: Robot
    active_delivery: Delivery | None
    receipt_wait_seconds: int


@dataclass
class ClaimResult:
    """claim 결과. delivery가 None이면 줄 것이 없거나(skip_reason None) 로봇 상태 때문에 주지 않은 것(skip_reason)."""
    delivery: Delivery | None
    skip_reason: ClaimSkipReason | None = None


class DispatchService:
    """로봇이 배송을 가져가고(claim), 도착·실패를 보고하고, 일회용 마커로 수령을 확인한다."""

    def __init__(self, db: Session) -> None:
        self.repo = DeliveryRepository(db)
        self.robots = RobotRepository(db)
        self.deliveries = DeliveryService(db)
        self.notifier = DeliveryNotifier(db)
        self.events = DeliveryEventRecorder(db)
        self.robot_status = RobotStatusService(db)

    def overview(self, robot: Robot) -> RobotOverview:
        """로봇 자신의 정보 — 실행기가 시작·재시작할 때 이어서 할 일을 알려 준다.
        [입력] robot: 키로 확인된 로봇
        [출력] RobotOverview
        """
        return RobotOverview(
            robot=robot,
            active_delivery=self.repo.get_active_for_robot(robot.id),
            receipt_wait_seconds=RECEIPT_WAIT_SECONDS,
        )

    def claim(self, robot_id: int) -> ClaimResult:
        """배송 하나를 맡는다. 이미 맡은 배송이 있으면 그것을 그대로 돌려준다(멱등 — 응답을 잃어도 다시 부르면 된다).
        없으면 reserved이고 예약 시각이 지났고 목적지에 로봇 목적지 이름(robot_dest)이 있는 것 중 가장 이른 것을 dispatched로
        (2026-10-27: 복귀 장소·같은 맵 조건을 없앰 — 팀원 FMS가 /goto {dest}로 갈 수 있는 곳만 내준다).
        줄 배송이 있으면 그 전에 로봇 서버에 지금 상태를 묻는다(배터리·오염도·주행 준비, 2026-10-23) — 기준 밖이면 주지 않는다.
        [입력] robot_id: 키로 확인된 로봇
        [출력] ClaimResult: 줄 것이 없으면 delivery None, 상태 때문이면 skip_reason까지 (AMR이 아니면 Forbidden)
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
            return ClaimResult(active)
        if settings.FMS_BASE_URL:   # FMS 연동 중(2026-10-27) — 배차는 FMS가. 예전 claim이 같은 배송을 함께 바꾸지 않게 막는다
            return ClaimResult(None)
        now = datetime.now(UTC)
        # 줄 것이 있을 때만 로봇 서버에 묻는다. 묻는 동안(최대 ROBOT_SERVER_TIMEOUT_SECONDS) 배송 행을 잠가 두지 않으려고 먼저 잠금 없이 본다
        if self.repo.lock_next_claimable(now, lock=False) is None:
            return ClaimResult(None)
        skip_reason = self.robot_status.check_before_claim(robot, now)
        if skip_reason is not None:
            return ClaimResult(None, skip_reason)   # 이유는 응답 헤더로
        delivery = self.repo.lock_next_claimable(now)
        if delivery is None:   # 묻는 사이 다른 로봇이 가져갔거나 간호사가 취소함
            return ClaimResult(None)
        delivery.status = DeliveryStatus.DISPATCHED
        delivery.assigned_robot_id = robot.id
        delivery.assigned_robot = robot
        delivery.dispatched_at = now
        attempt.info("delivery_dispatched", delivery_id=delivery.id, destination_location_id=delivery.destination_location_id)
        self.notifier.notify_dispatched(delivery)
        self.events.record_by_robot(delivery, DeliveryEventType.DISPATCHED, robot, now)
        return ClaimResult(delivery)

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
            if delivery.status == DeliveryStatus.RECEIVED and delivery.receipt_method == ReceiptMethod.NONE:
                return delivery   # 로봇 전용 장소 이동의 같은 도착 보고 (멱등)
            if delivery.status != DeliveryStatus.DISPATCHED:
                return self._reject_transition(attempt, delivery, stage)
            if delivery.receipt_method == ReceiptMethod.NONE:
                return self._complete_robot_move(attempt, delivery, now)
            # 마커를 먼저 고른다 — 고르는 조회가 자동 flush를 일으켜, 상태부터 바꾸면 마커 없는 arrived가 CHECK에 걸린다
            receipt_marker_id = self._pick_receipt_marker_id()
            delivery.status = DeliveryStatus.ARRIVED
            delivery.arrived_at = now
            delivery.receipt_marker_id = receipt_marker_id
            attempt.info("delivery_arrived")
            self.notifier.notify_arrived(delivery)
            self.events.record_by_robot(delivery, DeliveryEventType.ARRIVED, delivery.assigned_robot, now)
            return delivery

        # stage == failed
        if delivery.status == DeliveryStatus.FAILED:
            return delivery
        if delivery.status == DeliveryStatus.RECEIVED:
            attempt.info("progress_rejected", code="delivery_already_received")
            raise Conflict(f"delivery {delivery_id} is already received", code="delivery_already_received")
        if delivery.status not in (DeliveryStatus.PREPARING, DeliveryStatus.DISPATCHED, DeliveryStatus.ARRIVED):
            return self._reject_transition(attempt, delivery, stage)
        self.deliveries.restore_stock(delivery)
        delivery.status = DeliveryStatus.FAILED
        delivery.failed_at = now
        delivery.failure_reason = failure_reason
        attempt.info("delivery_failed", failure_reason=failure_reason)
        self.notifier.notify_failed(delivery)
        self.events.record_by_robot(
            delivery, DeliveryEventType.FAILED, delivery.assigned_robot, now, {"failure_reason": failure_reason},
        )
        return delivery

    def list_waiting(self, due_only: bool, limit: int) -> list[Delivery]:
        """맡지 않은 예약 목록 — 로봇 배정 없이 배송 정보만 넘긴다 (2026-10-22, 팀원 FMS가 어느 로봇이 갈지 정한다).
        [입력] due_only: 예약 시각이 지난 것만 / limit [출력] list[Delivery]
        """
        return self.repo.list_waiting(datetime.now(UTC) if due_only else None, limit)

    def report_at_pharmacy(self, robot_id: int) -> Delivery:
        """약제실 도착 — 이 로봇이 맡은 배송을 실으러 약제실에 왔다 (2026-10-27 사용자 결정: /robot/arrived는 약제실 전용).
        서버 로그(robot_at_pharmacy)만 남긴다 — 배송 상태·알림·배송 기록은 그대로(dispatched). 병실 도착은 report_progress(arrived).
        여러 번 불러도 같다.
        [입력] robot_id: 키로 확인된 로봇
        [출력] Delivery: dispatched 그대로. 맡은 배송이 없으면 Conflict robot_no_active_delivery, 이미 병실 도착(arrived)이면 delivery_invalid_transition
        """
        active = self.repo.get_active_for_robot(robot_id)
        if active is None:
            log.warning("progress_rejected", robot_id=robot_id, stage=STAGE_AT_PHARMACY, code="robot_no_active_delivery")
            raise Conflict(f"robot {robot_id} has no dispatched or arrived delivery", code="robot_no_active_delivery")
        attempt = log.bind(robot_id=robot_id, delivery_id=active.id, stage=STAGE_AT_PHARMACY)
        if active.status not in (DeliveryStatus.PREPARING, DeliveryStatus.DISPATCHED):   # 준비 = FMS가 약제실로 부름 (2026-10-29)
            return self._reject_transition(attempt, active, STAGE_AT_PHARMACY)
        attempt.info("robot_at_pharmacy")
        return active

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
        if delivery.requester_type == DeliveryRequester.BEDSIDE:   # 병상 배송은 환자 화면 버튼으로만 (2026-10-22)
            attempt.warning("receipt_rejected", code="delivery_receipt_by_button")
            raise Conflict(f"delivery {delivery_id} is received by the bedside button", code="delivery_receipt_by_button")
        if aruco_marker_id != delivery.receipt_marker_id:
            attempt.warning("receipt_rejected", code="receipt_marker_not_for_delivery")
            raise Forbidden(f"aruco_marker_id {aruco_marker_id} is not this delivery's receipt marker", code="receipt_marker_not_for_delivery")
        DeliveryService.mark_received(delivery, datetime.now(UTC), delivery.nurse_id)   # 받은 간호사 = 예약 간호사
        attempt.info("receipt_confirmed", nurse_id=delivery.nurse_id)
        self.notifier.notify_received(delivery)
        self.events.record_by_robot(delivery, DeliveryEventType.RECEIVED, delivery.assigned_robot, delivery.received_at)
        return delivery

    # ---- 내부 ----------------------------------------------------------------

    def _complete_robot_move(self, attempt, delivery: Delivery, now: datetime) -> Delivery:
        """로봇 전용 장소(충전 등)로의 품목 없는 이동 — 도착 보고가 곧 완료 (2026-10-22). 마커·수령 대기 없음.
        [입력] attempt: 로그 / delivery: dispatched / now [출력] Delivery: received (받은 간호사 = 요청 간호사)
        """
        delivery.arrived_at = now
        DeliveryService.mark_received(delivery, now, delivery.nurse_id)   # 받은 간호사 = 요청 간호사
        attempt.info("robot_move_completed")
        self.notifier.notify_received(delivery)
        self.events.record_by_robot(delivery, DeliveryEventType.ARRIVED, delivery.assigned_robot, now)
        self.events.record_by_robot(delivery, DeliveryEventType.RECEIVED, delivery.assigned_robot, now)
        return delivery

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
