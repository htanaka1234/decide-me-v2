from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from decide_me.events import utc_now
from decide_me.store import transact
from decide_me.taxonomy import ensure_term_path, find_nodes, stable_unique


DOMAIN_VALUES = {"product", "technical", "data", "ux", "ops", "legal", "other"}
SOURCE_REF_VALUES = {"accepted_decisions", "latest_summary", "close_summary", "evidence_refs"}


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
    now = utc_now()
    terms = stable_unique(term.strip() for term in candidate_terms if term and term.strip())
    sources = stable_unique(source.strip() for source in source_refs if source and source.strip())

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"cannot classify closed session {session_id}")
        classification = deepcopy(session["classification"])

        if domain is not None and domain not in DOMAIN_VALUES:
            raise ValueError(f"invalid domain: {domain}")
        if domain is not None:
            classification["domain"] = domain
        if abstraction_level is not None:
            classification["abstraction_level"] = abstraction_level

        additions: list[dict[str, Any]] = []
        created_tag_refs: list[str] = []
        assigned = list(classification.get("assigned_tags", []))
        search_terms = list(classification.get("search_terms", []))
        existing_sources = list(classification.get("source_refs", []))

        for source in sources:
            if source not in SOURCE_REF_VALUES:
                raise ValueError(f"invalid source_ref: {source}")
            if source not in existing_sources:
                existing_sources.append(source)

        for term in terms:
            if term not in search_terms:
                search_terms.append(term)
            matched = find_nodes(bundle["taxonomy_state"], term, axis="tag")
            if not matched:
                _, created = ensure_term_path(bundle["taxonomy_state"], term, axis="tag", now=now)
                additions.extend(created)
                matched = [node["id"] for node in created[-1:]]
                created_tag_refs.extend(node["id"] for node in created)
            for tag_ref in matched:
                if tag_ref not in assigned:
                    assigned.append(tag_ref)

        classification["assigned_tags"] = stable_unique(assigned)
        classification["search_terms"] = stable_unique(search_terms)
        classification["source_refs"] = stable_unique(existing_sources)
        classification["updated_at"] = now
        changed = classification != session["classification"] or bool(additions)
        if not changed:
            return []

        events: list[dict[str, Any]] = []
        if additions:
            events.append(
                {
                    "session_id": session_id,
                    "event_type": "taxonomy_extended",
                    "payload": {"nodes": additions},
                }
            )
        events.append(
            {
                "session_id": session_id,
                "event_type": "classification_updated",
                "payload": {"classification": classification, "reason": reason},
            }
        )
        return events

    _, bundle = transact(ai_dir, builder)
    session = bundle["sessions"][session_id]
    created = [
        node["id"]
        for node in bundle["taxonomy_state"]["nodes"]
        if node["axis"] == "tag" and node["created_at"] == session["classification"]["updated_at"]
    ]
    return {
        "status": "ok",
        "session_id": session_id,
        "reason": reason,
        "classification": session["classification"],
        "created_tag_refs": created,
    }

def _require_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        return bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc
