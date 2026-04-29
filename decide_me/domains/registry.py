from __future__ import annotations

import re
from dataclasses import dataclass

from decide_me.domains.model import DecisionTypeSpec, DomainPack


GENERIC_PACK_ID = "generic"
ALIAS_WEIGHT = 3
HINT_WEIGHT = 1


@dataclass(frozen=True)
class DomainRegistry:
    packs: dict[str, DomainPack]

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

        scores = [
            (_score_pack(pack, normalized), pack.pack_id)
            for pack in self.list()
            if pack.pack_id != GENERIC_PACK_ID
        ]
        positive_scores = [(score, pack_id) for score, pack_id in scores if score > 0]
        if not positive_scores:
            return GENERIC_PACK_ID

        best_score = max(score for score, _pack_id in positive_scores)
        best = sorted(pack_id for score, pack_id in positive_scores if score == best_score)
        if len(best) != 1:
            return GENERIC_PACK_ID
        return best[0]

    def decision_type(self, pack_id: str, type_id: str) -> DecisionTypeSpec:
        pack = self.get(pack_id)
        for item in pack.decision_types:
            if item.id == type_id:
                return item
        raise KeyError(f"unknown decision type for domain pack {pack_id}: {type_id}")


def _score_pack(pack: DomainPack, normalized_text: str) -> int:
    score = 0
    for alias in pack.aliases:
        if _contains_phrase(normalized_text, alias):
            score += ALIAS_WEIGHT
    for hint in pack.interview.domain_hints:
        if _contains_phrase(normalized_text, hint):
            score += HINT_WEIGHT
    return score


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text) is not None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()
