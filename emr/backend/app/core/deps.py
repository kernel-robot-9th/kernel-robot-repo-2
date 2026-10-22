# =============================================================================
# 파일   : app/core/deps.py
# 역할   : FastAPI 공용 Depends (세션·현재 간호사)
# 작성일 : 2026-10-13
# 구성   :
#   - DB                   세션 주입 타입 별칭
#   - get_current_nurse()  Bearer 토큰 → Nurse
#   - CurrentNurse         로그인 필수 파라미터 타입 별칭
#   - get_current_admin()  로그인 + 관리자 확인 (아니면 403 admin_required)
#   - CurrentAdmin         관리자 필수 파라미터 타입 별칭, ADMIN_RESPONSES
#   - get_current_robot()  X-Robot-Api-Key 헤더 → Robot (로봇 전용 API, 2026-10-19)
#   - CurrentRobot         로봇 키 필수 파라미터 타입 별칭, ROBOT_RESPONSES
#   - get_current_bedside() / CurrentBedside / BEDSIDE_RESPONSES   X-Bedside-Api-Key 헤더 → 병상 단말 (2026-10-22)
# =============================================================================
from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_token, hash_robot_api_key
from app.models.bedside_device import BedsideDevice
from app.models.enums import NurseRole
from app.models.nurse import Nurse
from app.models.robot import Robot
from app.repositories.bedside_device import BedsideDeviceRepository
from app.repositories.robot import RobotRepository
from app.services.auth import AuthService

# auto_error=False: 헤더가 없을 때도 우리 오류 형식({"code","detail"})으로 401을 내기 위함
bearer_scheme = HTTPBearer(auto_error=False, description="POST /api/v1/auth/login 으로 받은 access_token")

# 라우터 파라미터 타입: 요청 단위 세션.
# scope="function": 엔드포인트가 끝나면 응답을 보내기 *전에* commit한다. 기본값("request")은 응답을 보낸 뒤 commit해서
# 클라이언트가 200을 받고 바로 다시 조회하면 커밋 전 데이터를 받거나(목록에 취소 전 상태), 방금 만든 행이 404가 났다.
# 그래서 엔드포인트는 세션이 닫히기 전에 응답 스키마(XOut.model_validate)를 만들어 반환해야 한다.
DB: TypeAlias = Annotated[Session, Depends(get_db, scope="function")]


def get_current_nurse(
    db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Nurse:
    """Authorization: Bearer 토큰을 검증해 현재 로그인한 간호사를 반환한다. 실패 시 401.
    [입력] db: 세션 / credentials: Authorization 헤더 (없으면 None)
    [출력] Nurse: 활성 상태인 간호사
    """
    if credentials is None:
        raise Unauthorized("missing bearer token", code="token_missing")
    nurse_id = decode_token(credentials.credentials)
    if nurse_id is None:
        raise Unauthorized("invalid or expired token", code="token_invalid")
    nurse = AuthService(db).get_active_nurse(nurse_id)
    if nurse is None:
        raise Unauthorized("inactive or unknown user", code="user_inactive")
    return nurse


CurrentNurse: TypeAlias = Annotated[Nurse, Depends(get_current_nurse)]  # 라우터 파라미터 타입: 로그인 필수


def get_current_admin(nurse: CurrentNurse) -> Nurse:
    """로그인한 간호사가 관리자인지 확인한다. 로그인 안 했으면 401, 관리자가 아니면 403.
    [입력] nurse: 로그인한 간호사
    [출력] Nurse: 관리자
    """
    if nurse.role != NurseRole.ADMIN:
        raise Forbidden("admin role required", code="admin_required")
    return nurse


CurrentAdmin: TypeAlias = Annotated[Nurse, Depends(get_current_admin)]  # 라우터 파라미터 타입: 관리자 필수
ADMIN_RESPONSES = {  # 관리자 전용 엔드포인트의 OpenAPI 오류 응답
    401: {"description": "토큰 없음·만료·비활성 간호사"},
    403: {"description": "관리자가 아님 (admin_required)"},
}


# 간호사 JWT(Authorization)와 섞이지 않게 로봇 키는 헤더를 따로 쓴다. auto_error=False: 우리 오류 형식으로 401
robot_api_key_scheme = APIKeyHeader(
    name="X-Robot-Api-Key", auto_error=False, description="관리자가 POST /api/v1/robots/{id}/api-key로 발급한 로봇별 키",
)


def get_current_robot(db: DB, raw_api_key: Annotated[str | None, Depends(robot_api_key_scheme)]) -> Robot:
    """X-Robot-Api-Key 헤더의 키로 로봇을 찾는다. 실패 시 401.
    [입력] db / raw_api_key: 헤더 값 (없으면 None)
    [출력] Robot: 키가 지금 유효한 로봇 (재발급·폐기된 키는 해시가 없어 실패)
    """
    if not raw_api_key:
        raise Unauthorized("missing robot api key", code="robot_key_missing")
    robot = RobotRepository(db).get_by_api_key_hash(hash_robot_api_key(raw_api_key))
    if robot is None:
        raise Unauthorized("invalid or revoked robot api key", code="robot_key_invalid")
    return robot


CurrentRobot: TypeAlias = Annotated[Robot, Depends(get_current_robot)]  # 라우터 파라미터 타입: 로봇 키 필수
ROBOT_RESPONSES = {401: {"description": "로봇 키 없음·틀림·폐기됨 (robot_key_missing·robot_key_invalid)"}}


# 병상 단말 키도 헤더를 따로 쓴다 (간호사 JWT·로봇 키와 섞이지 않게, 2026-10-22)
bedside_api_key_scheme = APIKeyHeader(
    name="X-Bedside-Api-Key", auto_error=False,
    description="관리자가 POST /api/v1/bedside-devices/{id}/api-key로 발급한 병상 단말 키",
)


def get_current_bedside(db: DB, raw_api_key: Annotated[str | None, Depends(bedside_api_key_scheme)]) -> BedsideDevice:
    """X-Bedside-Api-Key 헤더의 키로 병상 단말을 찾는다. 실패 시 401.
    [입력] db / raw_api_key: 헤더 값
    [출력] BedsideDevice: 키가 지금 유효한 단말 (병실 로드됨)
    """
    if not raw_api_key:
        raise Unauthorized("missing bedside api key", code="bedside_key_missing")
    device = BedsideDeviceRepository(db).get_by_api_key_hash(hash_robot_api_key(raw_api_key))
    if device is None:
        raise Unauthorized("invalid or revoked bedside api key", code="bedside_key_invalid")
    return device


CurrentBedside: TypeAlias = Annotated[BedsideDevice, Depends(get_current_bedside)]  # 라우터 파라미터 타입: 병상 단말 키 필수
BEDSIDE_RESPONSES = {401: {"description": "병상 단말 키 없음·틀림·폐기됨 (bedside_key_missing·bedside_key_invalid)"}}
