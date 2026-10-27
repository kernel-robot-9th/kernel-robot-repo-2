# =============================================================================
# 파일   : app/services/omx_items.py
# 역할   : OMX(로봇팔) 물품 대응표 — EMR 비품 종류 → OMX가 이미지(YOLO)로 집는 색 (2026-10-27)
# 작성일 : 2026-10-27
# 구성   :
#   - OMX_COLOR_BY_CATEGORY  약품(medication) → blue(파란 거즈), 비품(supply) → green(녹색 거즈)
#   - omx_color()            비품 종류 하나의 색
#   - omx_counts()           (종류, 수량) 목록 → OMX POST /command의 {"blue": n, "green": n}
#   - omx_command()          OMX에 실제로 보낼 command — 설정 OMX_COMMAND_FORMAT: counts면 그대로, sentence(임시, 10-27)면
#                            수량을 무시한 거즈 문장 하나 "pick and place blue gauze" (파란 거즈가 하나라도 있으면 blue, 아니면 green)
# 사용자 결정(2026-10-27): "약품 파란, 비품 녹색". OMX가 알아보는 것은 blue_gauze·green_gauze 둘뿐이라
# 비품 하나하나가 아니라 종류(supplies.category)로 나눈다 — DB 칸을 더하지 않는다
# =============================================================================
from __future__ import annotations

from collections.abc import Iterable

from app.core.config import settings
from app.models.enums import SupplyCategory

OMX_COLORS = ("blue", "green")   # OMX POST /command의 command 키 순서
OMX_COLOR_BY_CATEGORY: dict[str, str] = {
    SupplyCategory.MEDICATION: "blue",   # 약품 → 파란 거즈
    SupplyCategory.SUPPLY: "green",      # 비품 → 녹색 거즈
}


def omx_color(category: str) -> str:
    """비품 종류의 OMX 색.
    [입력] category: supplies.category (medication | supply)
    [출력] str: "blue" | "green" (모르는 종류면 ValueError — 종류를 늘리면 이 표부터 고친다)
    """
    try:
        return OMX_COLOR_BY_CATEGORY[category]
    except KeyError as error:
        raise ValueError(f"no OMX color for supply category {category!r}") from error


def omx_counts(items: Iterable[tuple[str, int]]) -> dict[str, int]:
    """물품 목록을 색깔별 개수로 센다.
    [입력] items: (비품 종류, 수량) 목록 — 예 [("medication", 2), ("supply", 1)]
    [출력] dict: {"blue": 2, "green": 1} (두 색 모두 키가 있다, 없으면 0)
    """
    counts = dict.fromkeys(OMX_COLORS, 0)
    for category, quantity in items:
        counts[omx_color(category)] += quantity
    return counts


def omx_command(counts: dict[str, int]) -> dict[str, int] | str:
    """OMX POST /command에 넣을 command.
    sentence(임시 — 10-27 실제 OMX가 문장만 받음)는 수량을 무시하고 한 색만: 파란 거즈가 하나라도 있으면 blue, 아니면 green.
    [입력] counts: {"blue": n, "green": n}
    [출력] counts 그대로 또는 "pick and place blue gauze"
    """
    if settings.OMX_COMMAND_FORMAT == "counts":
        return counts
    return f"pick and place {'blue' if counts.get('blue', 0) > 0 else 'green'} gauze"
