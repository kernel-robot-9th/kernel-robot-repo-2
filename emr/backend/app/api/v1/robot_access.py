# =============================================================================
# 파일   : app/api/v1/robot_access.py
# 역할   : 로봇 전용 엔드포인트 (/robot) — 간호사 JWT가 아니라 로봇별 API 키(X-Robot-Api-Key)로 부른다
# 작성일 : 2026-10-19
# 구성   :
#   - robot_me          GET  /robot/me                          — 로봇·복귀 장소·맡은 배송 (2026-10-20)
#   - claim_delivery    POST /robot/deliveries/claim            — 배송 하나 맡기 (멱등, 없으면 204) (2026-10-20)
#                                                                 EMR이 로봇 서버 /status에 물어 기준 밖이면 204 + X-Claim-Skip-Reason (2026-10-23)
#   - report_progress   POST /robot/deliveries/{id}/progress    — 도착·실패 보고 (2026-10-20)
#   - list_deliveries   GET  /robot/deliveries                  — 맡지 않은 예약 목록 (로봇 배정 없이 조회만) (2026-10-22)
#   - report_arrived    POST /robot/arrived                     — "지금 도착했습니다" (배송 id 없이, 맡은 배송) (2026-10-22)
#   - confirm_receipt   POST /robot/deliveries/{id}/receipt     — 일회용 마커로 수령 확인
# 계약: docs/api_contract_delivery_2026-10-20.md. 로봇용 응답(RobotDeliveryOut)에는 일회용 마커·간호사 정보가 없다
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from app.core.deps import DB, ROBOT_RESPONSES, CurrentRobot
from app.schemas.delivery import DeliveryProgressIn, DeliveryReceiptIn, RobotDeliveryOut, RobotMeOut
from app.services.dispatch import DispatchService

router = APIRouter(responses=ROBOT_RESPONSES)
NOT_ASSIGNED = "delivery_not_assigned_to_robot(이 로봇이 맡은 배송이 아님)"
CLAIM_SKIP_REASON_HEADER = "X-Claim-Skip-Reason"


@router.get(
    "/me", response_model=RobotMeOut,
    summary="로봇 자신의 정보 (로봇)",
    description="실행기가 시작·재시작할 때, 수령을 기다리는 동안 부른다. 복귀 장소(좌표 있는 것만), 맡고 있는 dispatched·arrived 배송, 수령 대기 시간(초).",
)
def robot_me(db: DB, robot: CurrentRobot) -> RobotMeOut:
    """
    [입력] robot: 키로 확인된 로봇
    [출력] RobotMeOut
    """
    return RobotMeOut.model_validate(DispatchService(db).overview(robot))


@router.post(
    "/deliveries/claim", response_model=RobotDeliveryOut,
    summary="배송 하나 맡기 (로봇)",
    description=(
        "이미 맡은 배송이 있으면 그것을 200으로(멱등). 없으면 reserved이고 예약 시각이 지났고 목적지가 복귀 장소와 같은 맵에 "
        "좌표가 있는 것 중 가장 이른 것을 dispatched로 바꿔 200. 줄 것이 없으면 204. 여러 로봇이 동시에 불러도 한 건은 한 로봇에만. "
        "줄 배송이 있으면 EMR이 그 전에 로봇 서버(관리자가 정한 robot_server_url)의 GET /status를 부른다(2초 제한) — 서버 주소 없음·응답 없음·"
        "배터리·오염도 칸 없음·주행 준비 안 됨(localized·nav2_ready·state=idle)·배터리 30 미만·오염도 70 초과면 204와 X-Claim-Skip-Reason 헤더 "
        "(robot_server_not_set · robot_server_unreachable · robot_status_incomplete · robot_not_ready · robot_battery_low · robot_contamination_high). 2026-10-23"
    ),
    responses={
        204: {"description": "맡을 배송 없음. 로봇 상태 때문이면 X-Claim-Skip-Reason 헤더에 이유"},
        403: {"description": "robot_not_amr(AMR만 배송)"},
        409: {"description": "robot_home_not_set(복귀 장소가 없거나 좌표가 없음)"},
    },
)
def claim_delivery(db: DB, robot: CurrentRobot) -> RobotDeliveryOut | Response:
    """
    [입력] robot: 키로 확인된 로봇
    [출력] RobotDeliveryOut | 204
    """
    result = DispatchService(db).claim(robot.id)
    if result.delivery is None:
        headers = {CLAIM_SKIP_REASON_HEADER: result.skip_reason} if result.skip_reason else None
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
    return RobotDeliveryOut.model_validate(result.delivery)


@router.post(
    "/deliveries/{delivery_id}/progress", response_model=RobotDeliveryOut,
    summary="도착·실패 보고 (로봇)",
    description=(
        "`{stage: arrived}`: dispatched → arrived(일회용 마커 생성). `{stage: failed, failure_reason}`: dispatched·arrived → failed"
        "(재고 복구). 같은 보고를 다시 보내도 200. 이미 received인데 failed면 409 delivery_already_received(성공으로 볼 것)."
    ),
    responses={
        403: {"description": NOT_ASSIGNED},
        404: {"description": "배송 없음"},
        409: {"description": "delivery_already_received · delivery_invalid_transition"},
    },
)
def report_progress(db: DB, robot: CurrentRobot, delivery_id: int, data: DeliveryProgressIn) -> RobotDeliveryOut:
    """
    [입력] delivery_id / data.stage·failure_reason / robot: 키로 확인된 로봇
    [출력] RobotDeliveryOut
    """
    delivery = DispatchService(db).report_progress(delivery_id, robot.id, data.stage, data.failure_reason)
    return RobotDeliveryOut.model_validate(delivery)


@router.get(
    "/deliveries", response_model=list[RobotDeliveryOut], summary="예약된 배송 목록 (맡지 않음)",
    description="로봇이 아직 맡지 않은(reserved) 배송을 예약 시각 순으로. 로봇 배정·상태 변경 없이 보기만 한다 — 어느 로봇이 갈지는 "
                "로봇 쪽(팀원 FMS)이 정한다. 목적지 destination.robot_dest가 Pinky 목적지 이름. 2026-10-22",
)
def list_deliveries(
    db: DB, robot: CurrentRobot,
    due_only: bool = Query(True, description="예약 시각이 지난 것만 (false면 앞으로 예정된 것까지)"),
    limit: int = Query(50, ge=1, le=200),
) -> list[RobotDeliveryOut]:
    """
    [입력] robot / due_only / limit
    [출력] list[RobotDeliveryOut]
    """
    return [RobotDeliveryOut.model_validate(delivery) for delivery in DispatchService(db).list_waiting(due_only, limit)]


@router.post(
    "/arrived", response_model=RobotDeliveryOut, summary="지금 도착했습니다",
    description="이 로봇이 맡은 배송(dispatched)을 도착(arrived)으로. 배송 id가 필요 없다 — 팀원 Pinky FMS 등 로봇 쪽이 도착하면 한 번 부른다. "
                "본문 없음, 멱등(이미 arrived면 200 그대로). progress {stage: arrived}와 같은 처리(알림·배송 기록). 2026-10-22",
    responses={409: {"description": "맡은 배송 없음 (robot_no_active_delivery)"}},
)
def report_arrived(db: DB, robot: CurrentRobot) -> RobotDeliveryOut:
    """
    [입력] robot: 키로 확인된 로봇
    [출력] RobotDeliveryOut: arrived
    """
    return RobotDeliveryOut.model_validate(DispatchService(db).report_arrived_now(robot.id))


@router.post(
    "/deliveries/{delivery_id}/receipt", response_model=RobotDeliveryOut,
    summary="배송 수령 확인 (로봇)",
    description=(
        "로봇 카메라가 읽은 ArUco DICT_4X4_250 마커 번호를 보낸다. 도착(arrived)해 있고 이 로봇이 맡은 배송이며 그 배송의 "
        "**일회용 마커**(도착 때 예약 간호사 화면에 뜬 것)일 때만 received. 간호사 고정 마커(0~49)로는 받을 수 없다."
    ),
    responses={
        403: {"description": f"{NOT_ASSIGNED} · receipt_marker_not_for_delivery(이 배송의 일회용 마커가 아님)"},
        404: {"description": "배송 없음"},
        409: {"description": "delivery_not_arrived(도착 전이거나 끝난 배송)"},
    },
)
def confirm_receipt(db: DB, robot: CurrentRobot, delivery_id: int, data: DeliveryReceiptIn) -> RobotDeliveryOut:
    """
    [입력] delivery_id / data.aruco_marker_id / robot: 키로 확인된 로봇
    [출력] RobotDeliveryOut: received
    """
    return RobotDeliveryOut.model_validate(DispatchService(db).confirm_receipt(delivery_id, data.aruco_marker_id, robot.id))
