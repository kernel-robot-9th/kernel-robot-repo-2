# =============================================================================
# 파일   : app/schemas/auth.py
# 역할   : 로그인 요청·토큰 응답·비밀번호 변경 스키마
# 작성일 : 2026-10-14
# 구성   :
#   - LoginIn
#   - PasswordChange  본인 비밀번호 변경
#   - TokenOut
# =============================================================================
from __future__ import annotations

from pydantic import BaseModel, Field

# 비밀번호는 요청 본문에 평문으로 온다. 운영에서는 HTTPS로만 받는다. 서버는 평문을 저장·로그하지 않는다
RAW_PASSWORD_FOR_CHECK = "평문으로 받는다(운영은 HTTPS로만). 저장하지 않고 bcrypt 해시와 대조만 한다"
RAW_PASSWORD_FOR_STORE = "평문으로 받는다(운영은 HTTPS로만). bcrypt 해시로 바꿔 저장하고 평문은 남기지 않는다"


class LoginIn(BaseModel):
    """간호사 로그인 요청 본문."""

    employee_no: str = Field(min_length=1, max_length=32, description="사번 (로그인 ID)", examples=["N001"])
    password: str = Field(min_length=1, max_length=72, description=RAW_PASSWORD_FOR_CHECK)


class PasswordChange(BaseModel):
    """본인 비밀번호 변경 본문. 현재 비밀번호가 맞아야 바뀐다."""

    current_password: str = Field(min_length=1, max_length=72, description=f"지금 비밀번호. {RAW_PASSWORD_FOR_CHECK}")
    new_password: str = Field(min_length=8, max_length=72, description=f"새 비밀번호 (8~72자). {RAW_PASSWORD_FOR_STORE}")


class TokenOut(BaseModel):
    """JWT 발급 응답. 이후 요청에 `Authorization: Bearer <access_token>` 헤더로 보낸다."""

    access_token: str = Field(description="Bearer 토큰")
    token_type: str = Field(default="bearer", description="항상 'bearer'")
    expires_in_seconds: int = Field(description="토큰 유효 시간(초)")
