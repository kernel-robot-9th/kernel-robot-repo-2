# =============================================================================
# 파일   : app/api/v1/robots.py
# 역할   : 로봇 등록·조회·수정·삭제 엔드포인트 (/robots)
# 작성일 : 2026-10-14
# 구성   :
#   - list/get                누구나 (로그인 없이 조회 — 2026-10-15 결정)
#   - create/update/delete    관리자만
#   - issue/revoke api key    관리자만 — 수령 확인 API(/robot/...)를 부를 로봇별 키 (2026-10-19)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import ADMIN_RESPONSES, DB, get_current_admin
from app.models.enums import RobotStatus, RobotType
from app.schemas.robot import RobotApiKeyOut, RobotCreate, RobotOut, RobotUpdate
from app.services.robot import RobotService

router = APIRouter()
NOT_FOUND_RESPONSE = {404: {"description": "로봇 없음"}}
NAME_CONFLICT_RESPONSE = {409: {"description": "name 중복"}}


@router.get("", response_model=list[RobotOut], summary="로봇 목록", description="id 순.")
def list_robots(
    db: DB,
    robot_type: RobotType | None = Query(default=None, description="있으면 그 종류만"),
    status_filter: RobotStatus | None = Query(default=None, alias="status", description="있으면 그 상태만"),
    limit: int = Query(100, le=500), offset: int = 0,
) -> list[RobotOut]:
    """
    [입력] robot_type / status / limit / offset
    [출력] list[RobotOut]
    """
    return [RobotOut.model_validate(robot) for robot in RobotService(db).list(robot_type, status_filter, limit, offset)]


@router.get("/{robot_id}", response_model=RobotOut, summary="로봇 단건", responses=NOT_FOUND_RESPONSE)
def get_robot(db: DB, robot_id: int) -> RobotOut:
    """
    [입력] robot_id
    [출력] RobotOut
    """
    return RobotOut.model_validate(RobotService(db).get(robot_id))


@router.post(
    "", response_model=RobotOut, status_code=status.HTTP_201_CREATED,
    summary="로봇 등록 (관리자)", description="종류(manipulator·amr)를 정해 등록한다. 상태는 idle로 시작하고, 종류는 이후 바꿀 수 없다.", responses={**ADMIN_RESPONSES, **NAME_CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def create_robot(db: DB, data: RobotCreate) -> RobotOut:
    """
    [입력] data
    [출력] RobotOut
    """
    return RobotOut.model_validate(RobotService(db).create(data))


@router.patch(
    "/{robot_id}", response_model=RobotOut,
    summary="로봇 이름·상태 변경 (관리자)", description="보낸 필드만 바뀐다.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, **NAME_CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def update_robot(db: DB, robot_id: int, data: RobotUpdate) -> RobotOut:
    """
    [입력] robot_id / data: 부분
    [출력] RobotOut
    """
    return RobotOut.model_validate(RobotService(db).update(robot_id, data))


@router.delete(
    "/{robot_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="로봇 삭제 (관리자)", description="행을 지운다. 키도 함께 사라지고, 이 로봇이 확인한 수령 기록의 로봇은 null이 된다.", responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def delete_robot(db: DB, robot_id: int) -> None:
    """
    [입력] robot_id
    [출력] 없음 (204)
    """
    RobotService(db).delete(robot_id)


@router.post(
    "/{robot_id}/api-key", response_model=RobotApiKeyOut, status_code=status.HTTP_201_CREATED,
    summary="로봇 API 키 발급·재발급 (관리자)",
    description=(
        "수령 확인 API(`POST /robot/deliveries/{id}/receipt`)를 부를 키를 만든다. 평문 키는 **이 응답에만** 나오고 "
        "서버는 해시만 보관한다. 다시 발급하면 이전 키는 즉시 쓸 수 없다."
    ),
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def issue_robot_api_key(db: DB, robot_id: int) -> RobotApiKeyOut:
    """
    [입력] robot_id
    [출력] RobotApiKeyOut: 평문 키 포함
    """
    robot, raw_api_key = RobotService(db).issue_api_key(robot_id)
    return RobotApiKeyOut(robot_id=robot.id, api_key=raw_api_key, issued_at=robot.api_key_issued_at)


@router.delete(
    "/{robot_id}/api-key", status_code=status.HTTP_204_NO_CONTENT,
    summary="로봇 API 키 폐기 (관리자)", description="이후 이 로봇의 수령 확인 요청은 401.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def revoke_robot_api_key(db: DB, robot_id: int) -> None:
    """
    [입력] robot_id
    [출력] 없음 (204)
    """
    RobotService(db).revoke_api_key(robot_id)
