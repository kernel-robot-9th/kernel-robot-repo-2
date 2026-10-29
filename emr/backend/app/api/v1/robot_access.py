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
#   - report_at_pharmacy POST /robot/arrived                    — 약제실 도착 (배송 id 없이, 맡은 배송, 로그만) (2026-10-22, 2026-10-27 약제실 전용으로)
#   - confirm_receipt   POST /robot/deliveries/{id}/receipt     — 일회용 마커로 수령 확인
#   - omx_end_point     GET  /robot/{request_id}/end-point      — OMX 완료 신호 (인증 없음, 성공만, 로그만 — 2026-10-26)
# 계약: docs/api_contract_delivery_2026-10-20.md. 로봇용 응답(RobotDeliveryOut)에는 일회용 마커·간호사 정보가 없다
# =============================================================================
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Body, Path, Query, Request, Response, status

from app.core.deps import DB, ROBOT_RESPONSES, CurrentRobot
from app.schemas.delivery import DeliveryProgressIn, DeliveryReceiptIn, RobotDeliveryOut, RobotMeOut
from app.schemas.robot import OmxEndPointOut
from app.services.dispatch import DispatchService
from app.services.fms_events import FmsEventHandler, pinky_signals_pharmacy
from app.services.omx_signal import OmxSignalService

router = APIRouter(responses=ROBOT_RESPONSES)
log = structlog.get_logger(__name__)
NOT_ASSIGNED = "delivery_not_assigned_to_robot(이 로봇이 맡은 배송이 아님)"
CLAIM_SKIP_REASON_HEADER = "X-Claim-Skip-Reason"


@router.get(
    "/me", response_model=RobotMeOut,
    summary="로봇 자신의 정보 (로봇)",
    description="로봇 쪽이 시작·재시작할 때, 수령을 기다리는 동안 부른다. 로봇 정보, 맡고 있는 dispatched·arrived 배송, 수령 대기 시간(초). 복귀 장소는 2026-10-27 없앰(팀원 FMS가 정함).",
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
        "이미 맡은 배송이 있으면 그것을 200으로(멱등). 없으면 reserved이고 예약 시각이 지났고 목적지에 로봇 목적지 이름(robot_dest)이 "
        "있는 것 중 가장 이른 것을 dispatched로 바꿔 200(2026-10-27: 복귀 장소 조건 없앰). 줄 것이 없으면 204. 여러 로봇이 동시에 불러도 한 건은 한 로봇에만. "
        "줄 배송이 있으면 EMR이 그 전에 로봇 서버(관리자가 정한 robot_server_url)의 GET /status를 부른다(2초 제한) — 서버 주소 없음·응답 없음·"
        "배터리·오염도 칸 없음·주행 준비 안 됨(localized·nav2_ready·state=idle)·배터리 30 미만·오염도 70 초과면 204와 X-Claim-Skip-Reason 헤더 "
        "(robot_server_not_set · robot_server_unreachable · robot_status_incomplete · robot_not_ready · robot_battery_low · robot_contamination_high). 2026-10-23"
    ),
    responses={
        204: {"description": "맡을 배송 없음. 로봇 상태 때문이면 X-Claim-Skip-Reason 헤더에 이유"},
        403: {"description": "robot_not_amr(AMR만 배송)"},
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
    "/arrived", response_model=RobotDeliveryOut, summary="약제실 도착",
    description="이 로봇이 맡은 배송(dispatched)을 실으러 **약제실에 도착**했다고 알린다. 배송 id가 필요 없다 — 팀원 Pinky FMS가 약제실 정밀 주차를 "
                "마치면 부른다. 본문 없음, 여러 번 불러도 같다. **EMR은 서버 로그만 남긴다** — 배송 상태는 dispatched 그대로, 간호사 알림·배송 기록 없음. "
                "**병실 도착은 `POST /robot/deliveries/{id}/progress {stage: arrived}`**. 2026-10-22, 2026-10-27 약제실 전용으로 바꿈(사용자 결정). "
                "**2026-10-28**: 설정 `FMS_PHARMACY_SIGNAL=pinky`(FMS가 가상인 동안)면 실물 Pinky의 이 신호(본문 = Pinky ArrivedSignal)를 "
                "'정밀 주차 끝'으로 보고, 기다리던 OMX 묶음에 내려놓기(/pinky)를 시작한다. **2026-10-29**: 그 묶음의 배송을 준비 → 출발로(출발 알림·기록)",
    responses={409: {"description": "맡은 배송 없음 (robot_no_active_delivery) · 이미 병실 도착(delivery_invalid_transition)"}},
)
def report_at_pharmacy(db: DB, robot: CurrentRobot, signal: dict[str, Any] | None = Body(default=None)) -> RobotDeliveryOut:
    """
    [입력] robot: 키로 확인된 로봇 / signal: Pinky ArrivedSignal {event, dest, job_id, dock_error, …} (없어도 됨)
    [출력] RobotDeliveryOut: dispatched 그대로
    """
    signal = signal or {}
    if pinky_signals_pharmacy() and signal.get("dest", "PHARMACY") == "PHARMACY":
        events = FmsEventHandler(db)
        batch = events.pinky_docked_at_pharmacy()
        log.info("pinky_arrived_signal", robot_id=robot.id, job_id=signal.get("job_id"), dock_error=signal.get("dock_error"),
                 batch_id=batch.batch_id if batch else None)
        delivery = events.delivery_for_batch(batch) if batch is not None else None
        if delivery is not None:
            return RobotDeliveryOut.model_validate(delivery)
    return RobotDeliveryOut.model_validate(DispatchService(db).report_at_pharmacy(robot.id))


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


@router.get(
    "/{request_id}/end-point", response_model=OmxEndPointOut,
    summary="OMX 완료 신호 (인증 없음)",
    description=(
        "팀원 OMX(로봇팔)가 작업을 마치면 부른다. request_id는 OMX /command·/pinky에 넣은 값 그대로(영문·숫자·`._-`, 1~64자). "
        "지금은 성공 신호만 받는다 — EMR은 서버 로그에 남기고 200을 돌려준다(DB에는 남기지 않음). 같은 request_id를 여러 번 보내도 매번 200. "
        "인증 없음(로봇 키 필요 없음). 2026-10-26"
    ),
    responses={422: {"description": "request_id 형식이 틀림"}},   # 401은 라우터 공통 설명일 뿐 — 이 엔드포인트는 키를 보지 않는다
)
def omx_end_point(
    request: Request, response: Response,
    request_id: str = Path(pattern=r"^[A-Za-z0-9._-]{1,64}$", description="OMX 작업의 request_id", examples=["yolo-8b5efa75"]),
) -> OmxEndPointOut:
    """
    [입력] request_id: 경로값 / request: 보낸 쪽 주소를 로그에 남기려고
    [출력] OmxEndPointOut
    """
    response.headers["Cache-Control"] = "no-store"   # GET이 중간에서 캐시되어 신호가 EMR에 닿지 않는 일을 막는다
    client_host = request.client.host if request.client else None
    received_at = OmxSignalService().record_end_point(request_id, client_host)
    return OmxEndPointOut(request_id=request_id, received=True, received_at=received_at)

