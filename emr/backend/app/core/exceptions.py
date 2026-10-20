# =============================================================================
# 파일   : app/core/exceptions.py
# 역할   : 도메인 예외 계층 (서비스 → HTTP 변환은 main.py)
# 작성일 : 2026-10-13
# 구성   :
#   - DomainError         베이스. status_code·code 보유
#   - BadRequest          400 잘못된 요청
#   - Unauthorized        401 인증 필요
#   - Forbidden           403 권한 없음
#   - NotFound            404
#   - Conflict            409 상태 충돌
#   - ServiceUnavailable  503 외부 시스템 연결 불가
# 성공(2xx)·리다이렉트(3xx)는 예외가 아니므로 여기 없다 — 라우터의 status_code에서 지정.
# =============================================================================
from __future__ import annotations


class DomainError(Exception):
    """서비스 레이어 예외의 베이스. HTTP를 모른다.
    main.py의 핸들러가 status_code·code를 읽어 JSON 응답으로 바꾼다.
    """

    status_code: int = 400   # 핸들러가 쓰는 HTTP 상태
    code: str = "domain_error"  # 클라이언트가 분기할 기계용 코드 (클래스 기본값)

    def __init__(self, detail: str, code: str | None = None) -> None:
        """
        [입력] detail: 개발자용 메시지(영어) / code: 구체적인 오류 코드(예: location_in_use). 없으면 클래스 기본값
        [출력] 없음
        프론트는 code를 frontend/src/api/errorMessages.ts에서 한국어 안내로 바꾼다 — 새 code를 만들면 거기도 추가한다.
        """
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class BadRequest(DomainError):
    """값은 형식에 맞지만 업무 규칙상 받을 수 없는 요청 → 400."""
    status_code = 400
    code = "bad_request"


class Unauthorized(DomainError):
    """로그인 안 됨·토큰 만료 → 401."""
    status_code = 401
    code = "unauthorized"


class Forbidden(DomainError):
    """로그인은 됐지만 권한 없음 → 403."""
    status_code = 403
    code = "forbidden"


class NotFound(DomainError):
    """조회 대상 없음 → 404."""
    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    """중복 코드 등 상태 충돌 → 409."""
    status_code = 409
    code = "conflict"


class ServiceUnavailable(DomainError):
    """DB·로봇 등 외부 시스템에 연결할 수 없음 → 503."""
    status_code = 503
    code = "service_unavailable"
