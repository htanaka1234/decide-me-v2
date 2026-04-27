from __future__ import annotations

from typing import Any, Iterable


def classify_session(
    ai_dir: str,
    session_id: str,
    *,
    domain: str | None = None,
    abstraction_level: str | None = None,
    candidate_terms: Iterable[str] = (),
    source_refs: Iterable[str] = (),
    reason: str = "classification-updated",
) -> dict[str, Any]:
    raise ValueError("session classification writes are unsupported by the Phase 5-3 event model")
