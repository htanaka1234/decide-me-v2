from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from decide_me.domains.model import DecisionTypeSpec, DomainPack


GENERIC_PACK_ID = "generic"
ALIAS_WEIGHT = 3
AMBIGUOUS_HINTS = frozenset(
    {
        "session",
        "service",
        "report",
        "copy",
        "flow",
        "support",
        "endpoint",
    }
)
SEPARATOR_PATTERN = re.compile(r"[_\-/]+")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class DomainRegistry:
    packs: Mapping[str, DomainPack]

    def __post_init__(self) -> None:
        packs = dict(self.packs)
        invalid_values = sorted(
            str(pack_id)
            for pack_id, pack in packs.items()
            if not isinstance(pack, DomainPack)
        )
        if invalid_values:
            raise ValueError("domain registry values must be DomainPack: " + ", ".join(invalid_values))

        mismatched = sorted(
            str(pack_id)
            for pack_id, pack in packs.items()
            if pack_id != pack.pack_id
        )
        if mismatched:
            raise ValueError("domain registry keys must match pack_id: " + ", ".join(mismatched))
        if GENERIC_PACK_ID not in packs:
            raise ValueError("domain registry must include generic domain pack")

        object.__setattr__(self, "packs", MappingProxyType(packs))

    def get(self, pack_id: str) -> DomainPack:
        try:
            return self.packs[pack_id]
        except KeyError as exc:
            raise KeyError(f"unknown domain pack: {pack_id}") from exc

    def list(self) -> list[DomainPack]:
        return [self.packs[pack_id] for pack_id in sorted(self.packs)]

    def infer_from_context(self, text: str) -> str:
        normalized = _normalize_text(text)
        if not normalized:
            return GENERIC_PACK_ID

        packs = [pack for pack in self.list() if pack.pack_id != GENERIC_PACK_ID]
        alias_scores = [(_score_aliases(pack, normalized), pack.pack_id) for pack in packs]
        positive_alias_scores = [(score, pack_id) for score, pack_id in alias_scores if score > 0]
        if positive_alias_scores:
            best_score = max(score for score, _pack_id in positive_alias_scores)
            best = sorted(pack_id for score, pack_id in positive_alias_scores if score == best_score)
            if len(best) == 1:
                return best[0]
            return GENERIC_PACK_ID

        hint_hits = [
            pack.pack_id
            for pack in packs
            if _pack_has_non_ambiguous_hint(pack, normalized)
        ]
        if len(hint_hits) == 1:
            return hint_hits[0]
        return GENERIC_PACK_ID

    def decision_type(self, pack_id: str, type_id: str) -> DecisionTypeSpec:
        pack = self.get(pack_id)
        for item in pack.decision_types:
            if item.id == type_id:
                return item
        raise KeyError(f"unknown decision type for domain pack {pack_id}: {type_id}")


def _score_aliases(pack: DomainPack, normalized_text: str) -> int:
    score = 0
    for alias in pack.aliases:
        if _contains_phrase(normalized_text, alias):
            score += ALIAS_WEIGHT
    return score


def _pack_has_non_ambiguous_hint(pack: DomainPack, normalized_text: str) -> bool:
    for hint in pack.interview.domain_hints:
        if _normalize_text(hint) in AMBIGUOUS_HINTS:
            continue
        if _contains_phrase(normalized_text, hint):
            return True
    return False


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text) is not None


def _normalize_text(text: str) -> str:
    normalized = text.casefold()
    normalized = SEPARATOR_PATTERN.sub(" ", normalized)
    normalized = WHITESPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()
