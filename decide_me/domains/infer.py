from __future__ import annotations

import re

from decide_me.domains.model import DecisionTypeSpec, DomainPack


SEPARATOR_PATTERN = re.compile(r"[_\-/]+")
WHITESPACE_PATTERN = re.compile(r"\s+")
GENERIC_DECISION_TYPE_TOKENS = {
    "choice",
    "decision",
    "definition",
    "method",
    "plan",
    "question",
    "review",
    "selection",
    "strategy",
}


def infer_decision_type(pack: DomainPack, text: str) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    scores = [
        (_score_decision_type(spec, normalized), index, spec.id)
        for index, spec in enumerate(pack.decision_types)
    ]
    positive = [(score, index, type_id) for score, index, type_id in scores if score > 0]
    if not positive:
        return None
    best_score = max(score for score, _index, _type_id in positive)
    best = [(index, type_id) for score, index, type_id in positive if score == best_score]
    if len(best) != 1:
        return None
    return sorted(best)[0][1]


def _score_decision_type(spec: DecisionTypeSpec, normalized_text: str) -> int:
    score = 0
    for phrase in _decision_type_phrases(spec):
        if _contains_phrase(normalized_text, phrase):
            score += 10 + len(_tokens(phrase))

    text_tokens = set(_tokens(normalized_text))
    for token in _decision_type_tokens(spec):
        if token in text_tokens:
            score += 1
    return score


def _decision_type_phrases(spec: DecisionTypeSpec) -> tuple[str, ...]:
    return (
        _normalize_text(spec.id),
        _normalize_text(spec.label),
    )


def _decision_type_tokens(spec: DecisionTypeSpec) -> tuple[str, ...]:
    tokens: list[str] = []
    for source in (spec.id, spec.label):
        for token in _tokens(source):
            if token in GENERIC_DECISION_TYPE_TOKENS:
                continue
            if token not in tokens:
                tokens.append(token)
    return tuple(tokens)


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text) is not None


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in _normalize_text(text).split()
        if token and token not in GENERIC_DECISION_TYPE_TOKENS
    ]


def _normalize_text(text: str) -> str:
    normalized = str(text or "").casefold()
    normalized = SEPARATOR_PATTERN.sub(" ", normalized)
    normalized = WHITESPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()
