# =============================================================================
# 파일   : app/services/auth.py
# 역할   : 간호사 로그인·토큰 → 간호사 복원
# 작성일 : 2026-10-14
# 구성   :
#   - AuthService  login(), get_active_nurse(), change_password()
# 비밀번호 취급 (raw_* 인자):
#   - 요청 본문으로 **평문**을 받는다. 운영에서는 HTTPS(TLS)로만 받아야 한다 — 개발용 http://localhost는 암호화되지 않음
#   - 평문은 bcrypt 대조(verify_password)·해시(hash_password)에만 쓰고, DB·로그·응답 어디에도 남기지 않는다
#   - DB에는 nurses.password_hash(bcrypt, 되돌릴 수 없음)만 저장한다
# =============================================================================
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Unauthorized
from app.core.security import create_access_token, hash_password, verify_password
from app.models.nurse import Nurse
from app.repositories.nurse import NurseRepository


class AuthService:
    """간호사 인증. 로그인 검증과 토큰 → 간호사 복원."""

    def __init__(self, db: Session) -> None:
        self.repo = NurseRepository(db)

    def login(self, employee_no: str, raw_password: str) -> str:
        """사번·비밀번호 검증 후 JWT 발급. 사번 없음·비밀번호 틀림·비활성을 구분해 알려주지 않는다(계정 열거 방지).
        [입력] employee_no / raw_password: 요청으로 받은 평문 — 저장된 bcrypt 해시와 대조만 하고 버린다
        [출력] str: access_token (실패 시 Unauthorized)
        """
        nurse = self.repo.get_by_employee_no(employee_no)
        if nurse is None or not nurse.is_active or not verify_password(raw_password, nurse.password_hash):
            raise Unauthorized("invalid credentials", code="invalid_credentials")
        return create_access_token(nurse.id)

    def get_active_nurse(self, nurse_id: int) -> Nurse | None:
        """토큰의 간호사 id로 복원. 비활성이면 None (토큰이 살아 있어도 접근 차단).
        [입력] nurse_id
        [출력] Nurse | None
        """
        nurse = self.repo.get(nurse_id)
        if nurse is None or not nurse.is_active:
            return None
        return nurse

    @staticmethod
    def change_password(nurse: Nurse, raw_current_password: str, raw_new_password: str) -> None:
        """본인 비밀번호 변경. 현재 비밀번호가 틀리면 BadRequest — 401이면 프론트가 로그아웃시키므로 쓰지 않는다.
        [입력] nurse: 로그인한 간호사 / raw_current_password: 요청으로 받은 평문 (해시와 대조만)
              / raw_new_password: 요청으로 받은 평문 (bcrypt 해시로 바꿔 저장)
        [출력] 없음
        """
        if not verify_password(raw_current_password, nurse.password_hash):
            raise BadRequest("current password does not match", code="current_password_mismatch")
        nurse.password_hash = hash_password(raw_new_password)
