"""DB 없이 도는 순수 단위 테스트."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.schemas.nurse import NurseCreate


def test_password_hash_roundtrip():
    password_hash = hash_password("nurse1234")
    assert password_hash != "nurse1234"
    assert verify_password("nurse1234", password_hash) and not verify_password("nurse12345", password_hash)


def test_token_roundtrip():
    assert decode_token(create_access_token(7)) == 7


def test_token_rejects_garbage_wrong_secret_and_expired():
    assert decode_token("not-a-token") is None
    forged = jwt.encode({"sub": "7", "exp": datetime.now(UTC) + timedelta(minutes=5)}, "another-secret-that-is-long-enough-000", algorithm="HS256")
    assert decode_token(forged) is None
    expired = jwt.encode({"sub": "7", "exp": datetime.now(UTC) - timedelta(minutes=1)}, settings.JWT_SECRET, algorithm="HS256")
    assert decode_token(expired) is None


def test_nurse_password_length_limits():
    with pytest.raises(ValidationError):
        NurseCreate(employee_no="N1", name="x", password="short")
    with pytest.raises(ValidationError):
        NurseCreate(employee_no="N1", name="x", password="a" * 73)
