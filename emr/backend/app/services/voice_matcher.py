# =============================================================================
# 파일   : app/services/voice_matcher.py
# 역할   : 말한 이름 → EMR 비품·장소 매칭 (순수 함수, DB 없음)
# 작성일 : 2026-10-26 (~/voice_module app/voice/matcher.py, 2026-10-14에서 옮김)
# 구성   :
#   - MatchTarget  매칭 대상(id·이름·별칭)
#   - MatchResult  가장 가까운 대상(확정 못 하면 None)·점수·후보
#   - normalize()  비교용 문자열(공백·기호 제거, 소문자)
#   - best_match() 정확 일치 → 포함 → 유사도. ACCEPT_THRESHOLD 이상이고 2위와 차이가 나야 확정
# 원칙: LLM이 적은 이름은 믿지 않는다. 최종 id는 항상 여기서 정한다.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

ACCEPT_THRESHOLD = 0.75   # 이 이상이면 자동 확정 — [검토 필요] 실제 발화로 맞춘다
AMBIGUOUS_GAP = 0.05      # 1·2위가 둘 다 기준 이상이고 차이가 이보다 작으면 애매 → 확정 안 함
CANDIDATE_MIN_SCORE = 0.3
CANDIDATE_LIMIT = 3


@dataclass(frozen=True)
class MatchTarget:
    """매칭 대상. aliases는 현장 약칭 (supplies에 별칭 칼럼이 아직 없어 지금은 비어 있다)."""

    id: int
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    """매칭 결과. target이 None이면 확정 못 함 — candidates에서 고른다."""

    target: MatchTarget | None
    score: float
    candidates: list[MatchTarget] = field(default_factory=list)


def normalize(text: str) -> str:
    """[입력] 원문 [출력] 공백·기호를 빼고 소문자로 바꾼 문자열"""
    return re.sub(r"[\s\-_/()·.,]", "", text).lower()


def _score(spoken: str, target: MatchTarget) -> float:
    """[입력] spoken: normalize한 발화 이름 / target [출력] 이름·별칭 중 가장 높은 유사도(0~1)"""
    best = 0.0
    for label in (target.name, *target.aliases):
        label = normalize(label)
        if spoken == label:
            return 1.0
        if spoken and (spoken in label or label in spoken):   # "거즈" ⊂ "멸균거즈"
            best = max(best, 0.9)
        best = max(best, SequenceMatcher(None, spoken, label).ratio())
    return best


def best_match(spoken_name: str, targets: list[MatchTarget]) -> MatchResult:
    """말한 이름에 가장 가까운 대상.
    [입력] spoken_name / targets
    [출력] MatchResult: 확정이면 target, 아니면 target=None + 후보(점수 순, 최대 CANDIDATE_LIMIT)
    """
    key = normalize(spoken_name)
    ranked = sorted(((_score(key, target), target) for target in targets), key=lambda pair: pair[0], reverse=True)
    if not ranked:
        return MatchResult(None, 0.0)
    top_score, top_target = ranked[0]
    ambiguous = (len(ranked) > 1 and ranked[1][0] >= ACCEPT_THRESHOLD
                 and top_score - ranked[1][0] < AMBIGUOUS_GAP)
    if top_score >= ACCEPT_THRESHOLD and not ambiguous:
        return MatchResult(top_target, round(top_score, 3))
    candidates = [target for score, target in ranked[:CANDIDATE_LIMIT] if score > CANDIDATE_MIN_SCORE]
    return MatchResult(None, round(top_score, 3), candidates)
