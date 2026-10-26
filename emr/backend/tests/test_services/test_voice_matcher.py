"""말한 이름 → EMR 비품·장소 매칭 (2026-10-26, ~/voice_module tests/test_voice.py의 matcher 시험을 EMR 이름으로 옮김). DB 불필요."""
from __future__ import annotations

from app.services.voice_matcher import MatchTarget, best_match, normalize

SUPPLIES = [MatchTarget(1, "A 약품"), MatchTarget(2, "B 약품"), MatchTarget(4, "주사제"),
            MatchTarget(10, "멸균 거즈", ("거즈",)), MatchTarget(11, "알코올 솜", ("알콜솜", "소독솜"))]
LOCATIONS = [MatchTarget(8, "4인실 왼쪽"), MatchTarget(10, "4인실 오른쪽"), MatchTarget(9, "약제실 OMX"),
             MatchTarget(11, "1인실 가운데 위-왼"), MatchTarget(15, "수술실")]


def test_normalize_drops_spaces_and_symbols():
    assert normalize("1인실 가운데 위-왼") == "1인실가운데위왼"
    assert normalize("A 약품") == "a약품"


def test_exact_name_ignoring_spaces_and_case():
    result = best_match("a약품", SUPPLIES)
    assert result.target.id == 1 and result.score == 1.0


def test_alias_exact():
    assert best_match("알콜솜", SUPPLIES).target.id == 11


def test_contained_name():
    assert best_match("거즈", SUPPLIES).target.id == 10


def test_spacing_variation():
    assert best_match("알코올솜", SUPPLIES).target.id == 11


def test_unknown_name_is_not_forced():
    result = best_match("혈압계", SUPPLIES)
    assert result.target is None


def test_ambiguous_names_are_not_confirmed_and_give_candidates():
    """"약품"은 A·B 약품 둘 다에 들어 있다 — 고르지 않고 후보로."""
    result = best_match("약품", SUPPLIES)
    assert result.target is None
    assert {candidate.id for candidate in result.candidates} >= {1, 2}


def test_location_match():
    assert best_match("4인실 왼쪽", LOCATIONS).target.id == 8
    assert best_match("약제실", LOCATIONS).target.id == 9


def test_location_ambiguous_between_left_and_right():
    result = best_match("4인실", LOCATIONS)
    assert result.target is None and {candidate.id for candidate in result.candidates} >= {8, 10}


def test_empty_targets():
    result = best_match("거즈", [])
    assert result.target is None and result.score == 0.0 and result.candidates == []
