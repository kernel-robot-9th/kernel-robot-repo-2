# =============================================================================
# 파일   : app/core/security.py
# 역할   : 비밀번호 해시·JWT 발급/검증
# 작성일 : 2026-10-14
# 구성   :
#   - hash_password()        bcrypt 해시
#   - verify_password()      해시 대조
#   - create_access_token()  JWT 발급
#   - decode_token()         JWT 검증 → 간호사 id
#   - generate_robot_api_key() / hash_api_key()   로봇별 API 키 발급 · 로봇·병상 단말 키 공용 해시 (2026-10-19, 이름 2026-10-23)
#   - generate_bedside_api_key()   병상 단말 키 발급 (해시는 hash_api_key, 2026-10-22)
# =============================================================================
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

ROBOT_API_KEY_PREFIX = "emr_rk_"   # 로그·설정 파일에서 EMR 로봇 키임을 알아보게
BEDSIDE_API_KEY_PREFIX = "emr_bk_"  # 병상 단말 키 (2026-10-22)


def hash_password(raw_password: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환한다.
    [입력] raw_password: 평문 (72바이트 이하 — 스키마에서 제한)
    [출력] str: 해시 문자열 (DB 저장용)
    """
    return bcrypt.hashpw(raw_password.encode(), bcrypt.gensalt()).decode()


def verify_password(raw_password: str, password_hash: str) -> bool:
    """평문과 해시를 대조한다.
    [입력] raw_password: 평문 / password_hash: DB의 password_hash
    [출력] bool: 일치 여부
    """
    try:
        return bcrypt.checkpw(raw_password.encode(), password_hash.encode())
    except ValueError:  # 72바이트 초과 평문·깨진 해시
        return False


def create_access_token(nurse_id: int) -> str:
    """간호사 PK를 sub로 담은 JWT를 발급한다. 만료는 JWT_EXPIRE_MINUTES.
    [입력] nurse_id
    [출력] str: 서명된 JWT
    """
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(nurse_id), "exp": expires_at}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> int | None:
    """JWT를 검증하고 간호사 id를 꺼낸다. 서명 불일치·만료·형식 오류면 None.
    [입력] token: Bearer 토큰 문자열
    [출력] int | None: 간호사 id
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def generate_robot_api_key() -> str:
    """로봇에 줄 무작위 API 키를 만든다 (256비트).
    [입력] 없음
    [출력] str: "emr_rk_..." 평문. 발급 응답에서 한 번만 보여 주고 저장·로그하지 않는다
    """
    return ROBOT_API_KEY_PREFIX + secrets.token_urlsafe(32)


def generate_bedside_api_key() -> str:
    """병상 단말에 줄 무작위 API 키 (256비트, 2026-10-22). 해시는 hash_api_key로 (로봇 키와 같은 sha256).
    [입력] 없음
    [출력] str: "emr_bk_..." 평문. 발급 응답에서 한 번만 보여 준다
    """
    return BEDSIDE_API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(raw_api_key: str) -> str:
    """API 키 → DB 저장·조회용 sha256. 사람이 정한 비밀번호가 아니라 256비트 무작위 값이라 bcrypt 없이 바로 조회한다.
    [입력] raw_api_key: 평문 키
    [출력] str: 64자 hex
    """
    return hashlib.sha256(raw_api_key.encode()).hexdigest()
