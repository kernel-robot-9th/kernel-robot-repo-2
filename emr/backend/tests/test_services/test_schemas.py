"""DB 없이 도는 순수 단위 테스트."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.supply import SupplyCreate, SupplyUpdate


def test_stock_qty_non_negative():
    with pytest.raises(ValidationError):
        SupplyCreate(code="X", name="x", category="supply", requestable_by="patient", stock_qty=-1)


def test_category_must_be_known():
    with pytest.raises(ValidationError):
        SupplyCreate(code="X", name="x", category="food", requestable_by="patient")


def test_update_sends_only_given_fields():
    assert SupplyUpdate(stock_qty=3).model_dump(exclude_unset=True) == {"stock_qty": 3}
