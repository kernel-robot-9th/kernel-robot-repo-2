# =============================================================================
# 파일   : app/schemas/nurse.py
# 역할   : 간호사 등록·편집·비밀번호 초기화·응답 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - NurseCreate    등록 (관리자)
#   - NurseUpdate    편집 (관리자)
#   - PasswordReset  비밀번호 초기화 (관리자)
#   - NurseOut
# =============================================================================
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import NurseRole
from app.models.nurse import ARUCO_MARKER_ID_MAX
from app.schemas.common import OrmOut

ROLE_DESCRIPTION = "admin(관리자: 간호사 관리·장소·맵·로봇 변경) | nurse(일반)"
# 비밀번호는 요청 본문에 평문으로 온다. 운영에서는 HTTPS로만 받는다. 서버는 평문을 저장·로그·응답하지 않는다
PASSWORD_DESCRIPTION = "로그인 비밀번호 (8~72자). 평문으로 받는다(운영은 HTTPS로만). bcrypt 해시로 바꿔 저장하고 평문은 남기지 않는다"
ARUCO_MARKER_DESCRIPTION = "신분증 대신 쓰는 ArUco 마커 번호 (DICT_4X4_50, 0~49). 다른 간호사와 겹치면 409. null=미배정"


class NurseCreate(BaseModel):
    """간호사 등록 본문."""

    employee_no: str = Field(min_length=1, max_length=32, description="사번 (UNIQUE)", examples=["N001"])
    name: str = Field(min_length=1, max_length=64, description="이름", examples=["김간호"])
    password: str = Field(min_length=8, max_length=72, description=PASSWORD_DESCRIPTION)
    role: NurseRole = Field(default=NurseRole.NURSE, description=ROLE_DESCRIPTION)
    aruco_marker_id: int | None = Field(default=None, ge=0, le=ARUCO_MARKER_ID_MAX, description=ARUCO_MARKER_DESCRIPTION)


class NurseUpdate(BaseModel):
    """간호사 편집 본문. 보낸 필드만 바뀐다(PATCH). employee_no는 변경 불가.
    null은 aruco_marker_id에서만 '배정 해제'로 쓰이고, 나머지 필드의 null은 무시한다.
    """

    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = Field(default=None, description="false=퇴사·휴직, true=복귀")
    role: NurseRole | None = Field(default=None, description=ROLE_DESCRIPTION)
    aruco_marker_id: int | None = Field(default=None, ge=0, le=ARUCO_MARKER_ID_MAX, description=ARUCO_MARKER_DESCRIPTION)


class PasswordReset(BaseModel):
    """관리자가 다른 간호사 비밀번호를 임시 값으로 바꾼다. 간호사는 로그인 후 본인이 다시 바꾼다."""

    new_password: str = Field(min_length=8, max_length=72, description=PASSWORD_DESCRIPTION)


class NurseOut(OrmOut):
    """간호사 응답. password_hash는 절대 포함하지 않는다."""

    id: int
    employee_no: str = Field(description="사번")
    name: str
    is_active: bool = Field(description="false면 퇴사·휴직 (삭제된 간호사)")
    role: str = Field(description=ROLE_DESCRIPTION)
    aruco_marker_id: int | None = Field(description=ARUCO_MARKER_DESCRIPTION)
