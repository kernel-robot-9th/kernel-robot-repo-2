# =============================================================================
# 파일   : app/api/v1/auth.py
# 역할   : 로그인 엔드포인트 (/auth)
# 작성일 : 2026-10-14
# 구성   :
#   - login()            사번·비밀번호 → JWT
#   - me()               토큰의 간호사 정보 (역할 포함)
#   - change_password()  내 비밀번호 변경
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, status

from app.core.config import settings
from app.core.deps import DB, CurrentNurse
from app.schemas.auth import LoginIn, PasswordChange, TokenOut
from app.schemas.nurse import NurseOut
from app.services.auth import AuthService

router = APIRouter()
UNAUTHORIZED_RESPONSE = {401: {"description": "인증 실패", "content": {"application/json": {"example": {"code": "invalid_credentials", "detail": "invalid credentials"}}}}}


@router.post(
    "/login", response_model=TokenOut,
    summary="간호사 로그인",
    description="사번·비밀번호로 Bearer 토큰을 받는다. /docs 우상단 Authorize에 `access_token`을 붙여 넣으면 된다.",
    responses=UNAUTHORIZED_RESPONSE,
)
def login(db: DB, data: LoginIn) -> TokenOut:
    """
    [입력] data.employee_no / data.password
    [출력] TokenOut
    """
    access_token = AuthService(db).login(data.employee_no, data.password)
    return TokenOut(access_token=access_token, expires_in_seconds=settings.JWT_EXPIRE_MINUTES * 60)


@router.get(
    "/me", response_model=NurseOut,
    summary="내 정보",
    description="토큰의 간호사 정보. 프론트가 로그인 상태 확인용으로 호출.",
    responses=UNAUTHORIZED_RESPONSE,
)
def me(nurse: CurrentNurse) -> NurseOut:
    """
    [입력] nurse: 토큰에서 복원
    [출력] NurseOut
    """
    return NurseOut.model_validate(nurse)


@router.post(
    "/password", status_code=status.HTTP_204_NO_CONTENT,
    summary="내 비밀번호 변경",
    description="현재 비밀번호가 맞아야 바뀐다. 틀리면 400 `current_password_mismatch` (401이 아님 — 로그인은 유지된다).",
    responses={400: {"description": "현재 비밀번호 틀림"}, 401: {"description": "토큰 없음·만료·비활성 간호사"}},
)
def change_password(db: DB, nurse: CurrentNurse, data: PasswordChange) -> None:
    """
    [입력] nurse: 토큰에서 복원 / data.current_password / data.new_password
    [출력] 없음 (204)
    """
    AuthService(db).change_password(nurse, data.current_password, data.new_password)
