"""OMX 물품 대응표 — 약품 → blue, 비품 → green (2026-10-27). DB 불필요."""
from __future__ import annotations

import pytest

from app.models.enums import SupplyCategory
from app.services.omx_items import OMX_COLOR_BY_CATEGORY, omx_color, omx_counts


def test_every_supply_category_has_a_color():
    """비품 종류를 늘리면 대응표도 같이 고쳐야 한다."""
    assert set(OMX_COLOR_BY_CATEGORY) == set(SupplyCategory)
    assert omx_color("medication") == "blue" and omx_color("supply") == "green"


def test_counts_sum_quantities_by_color():
    assert omx_counts([("medication", 2), ("supply", 1), ("medication", 1)]) == {"blue": 3, "green": 1}


def test_counts_always_have_both_colors():
    assert omx_counts([("supply", 2)]) == {"blue": 0, "green": 2}
    assert omx_counts([]) == {"blue": 0, "green": 0}


def test_unknown_category_raises():
    with pytest.raises(ValueError):
        omx_color("device")
