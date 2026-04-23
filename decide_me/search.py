from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from decide_me.projections import effective_session_status
from decide_me.taxonomy import (
    expand_filter_ids,
    find_nodes,
    normalize_text,
    resolved_tag_refs,
    taxonomy_by_id,
)


def build_search_blob(session_state: dict[str, Any], taxonomy_state: dict[str, Any]) -> str:
    summary = session_state.get("summary", {})
    classification = session_state.get("classification", {})
    close_summary = session_state.get("close_summary", {})
    nodes_by_id = taxonomy_by_id(taxonomy_state)

    pieces = [
        close_summary.get("work_item_title") or "",
        close_summary.get("work_item_statement") or "",
        close_summary.get("goal") or "",
        summary.get("latest_summary") or "",
        summary.get("current_question_preview") or "",
        " ".join(classification.get("search_terms", [])),
    ]
    for tag_ref in resolved_tag_refs(session_state, taxonomy_state):
        node = nodes_by_id.get(tag_ref)
        if not node:
            continue
        pieces.append(node.get("label") or "")
        pieces.extend(node.get("aliases", []))

    return "\n".join(piece for piece in pieces if piece)


def session_list_entry(
    session_state: dict[str, Any], taxonomy_state: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    session = deepcopy(session_state)
    status = effective_session_status(session, now=now)
    summary = session["summary"]
    close_summary = session["close_summary"]
    classification = session["classification"]

    headline = (
        close_summary.get("work_item_title")
        if status == "closed"
        else summary.get("current_question_preview") or summary.get("latest_summary")
    )
    detail = (
        close_summary.get("goal")
        if status == "closed"
        else summary.get("latest_summary") or session["working_state"].get("current_question")
    )

    return {
        "session_id": session["session"]["id"],
        "status": status,
        "domain": classification.get("domain"),
        "abstraction_level": classification.get("abstraction_level"),
        "last_seen_at": session["session"].get("last_seen_at"),
        "headline": headline,
        "detail": detail,
        "top_tags": _top_tags(session, taxonomy_state),
        "active_decision_id": summary.get("active_decision_id"),
    }


def search_sessions(
    sessions: dict[str, dict[str, Any]],
    taxonomy_state: dict[str, Any],
    *,
    query: str | None = None,
    statuses: list[str] | None = None,
    domains: list[str] | None = None,
    abstraction_levels: list[str] | None = None,
    tag_terms: list[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    statuses = statuses or []
    domains = domains or []
    abstraction_levels = abstraction_levels or []
    tag_terms = tag_terms or []

    matches: list[dict[str, Any]] = []
    for session_state in sessions.values():
        entry = session_list_entry(session_state, taxonomy_state, now=now)
        if statuses and entry["status"] not in statuses:
            continue
        if domains and entry["domain"] not in domains:
            continue
        if abstraction_levels and entry["abstraction_level"] not in abstraction_levels:
            continue
        if query and normalize_text(query) not in normalize_text(build_search_blob(session_state, taxonomy_state)):
            continue
        if tag_terms and not _matches_tags(session_state, taxonomy_state, tag_terms):
            continue
        matches.append(entry)

    return sorted(matches, key=lambda item: item.get("last_seen_at") or "", reverse=True)


def _matches_tags(
    session_state: dict[str, Any], taxonomy_state: dict[str, Any], tag_terms: list[str]
) -> bool:
    session_tags = set(resolved_tag_refs(session_state, taxonomy_state))
    for term in tag_terms:
        matched_ids = find_nodes(taxonomy_state, term)
        if not matched_ids:
            continue
        expanded = set(expand_filter_ids(taxonomy_state, matched_ids))
        if session_tags & expanded:
            return True
    return False


def _top_tags(session_state: dict[str, Any], taxonomy_state: dict[str, Any], limit: int = 3) -> list[str]:
    nodes_by_id = taxonomy_by_id(taxonomy_state)
    labels: list[str] = []
    for tag_ref in resolved_tag_refs(session_state, taxonomy_state):
        node = nodes_by_id.get(tag_ref)
        if node and node.get("label"):
            labels.append(node["label"])
        if len(labels) >= limit:
            break
    return labels
