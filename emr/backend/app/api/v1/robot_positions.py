# =============================================================================
# 파일   : app/api/v1/robot_positions.py
# 역할   : 병원 지도용 로봇 위치 (/robot-positions) — FMS robot-status의 마지막 값 (2026-10-29)
# 작성일 : 2026-10-29
# 구성   :
#   - list_robot_positions   GET — 간호사 로그인. 화면이 1초마다 묻는다
# /robots/{robot_id}와 겹치지 않게 따로 둔다. 값은 메모리에만 있다(services/fms_robot_positions.py)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import DB, CurrentNurse
from app.schemas.robot_position import RobotPositionsOut
from app.services.fms_robot_positions import RobotPositionService

router = APIRouter()


@router.get(
    "",
    response_model=RobotPositionsOut,
    summary="로봇 위치 (병원 지도)",
    description=(
        "팀원 FMS가 1초마다 보내는 로봇 상태의 마지막 위치. 좌표는 맵 `map_id`의 미터·라디안(FMS 그림 cm/100, ° → rad). "
        "`is_stale`이면 연결 끊김으로 표시한다. EMR을 다시 켜면 FMS가 다시 보낼 때까지 빈 목록. 2026-10-29"
    ),
)
def list_robot_positions(db: DB, nurse: CurrentNurse) -> RobotPositionsOut:
    """
    [입력] db / nurse: 로그인한 간호사
    [출력] RobotPositionsOut
    """
    return RobotPositionService(db).list_positions()
