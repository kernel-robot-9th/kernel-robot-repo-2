"""비품 유효기간 자동값 (2026-10-19). DB 없이 도는 단위 테스트."""
from __future__ import annotations

from datetime import date, timedelta

from app.services.supply import AUTO_EXPIRY_MAX_DAYS, AUTO_EXPIRY_MIN_DAYS, auto_expiry_date


def test_auto_expiry_is_six_months_to_one_year():
    today = date(2026, 10, 19)
    values = {auto_expiry_date(today) for _ in range(2000)}
    assert min(values) >= today + timedelta(days=AUTO_EXPIRY_MIN_DAYS)
    assert max(values) <= today + timedelta(days=AUTO_EXPIRY_MAX_DAYS)
    assert len(values) > 50  # 한 날짜로 몰리지 않고 범위 안에 퍼진다
