from __future__ import annotations

from typing import Any, Iterable

from decide_me.taxonomy import replacement_closure, taxonomy_by_id


def empty_suppressed_context() -> dict[str, Any]:
    return {
        "session_ids": [],
        "related_object_ids": [],
        "link_ids": [],
        "hidden_strings": [],
    }


def suppressed_decision_ids(project_state: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    graph = project_state["graph"]
    for resolved in graph.get("resolved_conflicts", []):
        context = resolved.get("suppressed_context", {})
        ids.update(object_id for object_id in context.get("related_object_ids", []) if str(object_id).startswith("D-"))
    return ids


def semantic_suppression_context_for_session(
    session: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    session_id = session["session"]["id"]
    if session_id not in set(resolution.get("rejected_session_ids", [])):
        return empty_suppressed_context()

    scope = resolution.get("scope", {})
    kind = scope.get("kind")
    close_summary = session.get("close_summary") or {}
    context = empty_suppressed_context()

    if kind == "accepted_decision":
        decision_id = scope.get("decision_id")
        if decision_id:
            _add_object_context(context, close_summary, decision_id)
    elif kind == "action":
        action_id = scope.get("action_id")
        if action_id:
            _add_object_context(context, close_summary, action_id)
    elif kind == "session":
        _add_session_context(context, close_summary)

    context = _normalized_context(context)
    if _has_suppressed_targets(context):
        context["session_ids"] = [session_id]
    return context


def apply_semantic_suppression_to_session(
    session: dict[str, Any],
    resolution: dict[str, Any],
    taxonomy_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = semantic_suppression_context_for_session(session, resolution)
    if not _has_suppressed_targets(context):
        return context

    hidden_strings = set(context["hidden_strings"])
    _sanitize_session_bindings_by_context(session, context)
    _sanitize_session_text(session, hidden_strings)
    _sanitize_classification(session, hidden_strings, taxonomy_state)
    _sanitize_close_summary_by_context(session["close_summary"], context)
    return _normalized_context(context)


def merge_suppressed_contexts(contexts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged = empty_suppressed_context()
    for context in contexts:
        for key in merged:
            merged[key].extend(context.get(key, []))
    return _normalized_context(merged)


def has_remaining_suppressed_scope(session: dict[str, Any], resolution: dict[str, Any]) -> bool:
    context = semantic_suppression_context_for_session(session, resolution)
    if resolution.get("scope", {}).get("kind") == "session":
        return bool(context.get("related_object_ids") or context.get("link_ids"))
    return _has_suppressed_targets(context)


def has_suppressed_context_remainders(
    session: dict[str, Any],
    context: dict[str, Any],
    taxonomy_state: dict[str, Any] | None = None,
) -> bool:
    related_object_ids = set(context.get("related_object_ids", []))
    link_ids = set(context.get("link_ids", []))
    hidden_strings = {_normalize_text(value) for value in context.get("hidden_strings", [])}

    if related_object_ids & set(session.get("session", {}).get("related_object_ids", [])):
        return True
    if session.get("working_state", {}).get("active_proposal_id") in related_object_ids:
        return True

    close_summary = session.get("close_summary", {})
    object_ids = close_summary.get("object_ids", {})
    if any(related_object_ids & set(object_ids.get(section, [])) for section in object_ids):
        return True
    if link_ids & set(close_summary.get("link_ids", [])):
        return True

    work_item = close_summary.get("work_item", {})
    text_values = [
        session.get("summary", {}).get("latest_summary"),
        session.get("summary", {}).get("current_question_preview"),
        work_item.get("title"),
        work_item.get("statement"),
        *session.get("classification", {}).get("search_terms", []),
    ]
    if any(_normalize_text(value) in hidden_strings for value in text_values if value):
        return True

    classification = session.get("classification", {})
    return any(
        _tag_ref_matches_hidden(tag_ref, taxonomy_state, hidden_strings)
        for tag_ref in classification.get("assigned_tags", [])
    )


def _add_object_context(context: dict[str, Any], close_summary: dict[str, Any], object_id: str) -> None:
    object_ids = close_summary.get("object_ids", {})
    if any(object_id in object_ids.get(section, []) for section in object_ids):
        context["related_object_ids"].append(object_id)
        work_item = close_summary.get("work_item", {})
        _extend_hidden_strings(context, [work_item.get("title"), work_item.get("statement")])
    if object_id.startswith("D-"):
        for action_id in object_ids.get("actions", []):
            context["related_object_ids"].append(action_id)
    for link_id in close_summary.get("link_ids", []):
        if object_id in link_id:
            context["link_ids"].append(link_id)


def _add_session_context(context: dict[str, Any], close_summary: dict[str, Any]) -> None:
    work_item = close_summary.get("work_item", {})
    _extend_hidden_strings(context, [work_item.get("title"), work_item.get("statement")])
    object_ids = close_summary.get("object_ids", {})
    for section in object_ids:
        context["related_object_ids"].extend(object_ids.get(section, []))
    context["link_ids"].extend(close_summary.get("link_ids", []))


def _sanitize_session_bindings_by_context(session: dict[str, Any], context: dict[str, Any]) -> None:
    related_object_ids = set(context.get("related_object_ids", []))
    hidden_strings = {_normalize_text(value) for value in context.get("hidden_strings", [])}

    session_payload = session.get("session", {})
    session_payload["related_object_ids"] = [
        object_id
        for object_id in session_payload.get("related_object_ids", [])
        if object_id not in related_object_ids
    ]

    summary = session.get("summary", {})
    working_state = session.get("working_state", {})
    preview_is_hidden = _normalize_text(summary.get("current_question_preview")) in hidden_strings
    if working_state.get("active_proposal_id") in related_object_ids or preview_is_hidden:
        summary["current_question_preview"] = None
        working_state["active_question_id"] = None
        working_state["active_proposal_id"] = None


def _sanitize_session_text(session: dict[str, Any], hidden_strings: set[str]) -> None:
    hidden = {_normalize_text(value) for value in hidden_strings}
    for section, key in (
        (session["summary"], "latest_summary"),
        (session["summary"], "current_question_preview"),
    ):
        if _normalize_text(section.get(key)) in hidden:
            section[key] = None

    close_summary = session["close_summary"]
    work_item = close_summary.get("work_item", {})
    fallback_title = _first_visible_text(
        [
            session["session"].get("bound_context_hint"),
            session["session"]["id"],
        ],
        hidden,
    )
    fallback_statement = _first_visible_text(
        [
            session["session"].get("bound_context_hint"),
            fallback_title,
        ],
        hidden,
    )
    if _normalize_text(work_item.get("title")) in hidden:
        work_item["title"] = fallback_title
    if _normalize_text(work_item.get("statement")) in hidden:
        work_item["statement"] = fallback_statement


def _sanitize_classification(
    session: dict[str, Any],
    hidden_strings: set[str],
    taxonomy_state: dict[str, Any] | None,
) -> None:
    hidden = {_normalize_text(value) for value in hidden_strings}
    classification = session.get("classification", {})
    classification["search_terms"] = [
        term for term in classification.get("search_terms", []) if _normalize_text(term) not in hidden
    ]
    classification["assigned_tags"] = [
        tag_ref
        for tag_ref in classification.get("assigned_tags", [])
        if not _tag_ref_matches_hidden(tag_ref, taxonomy_state, hidden)
    ]


def _sanitize_close_summary_by_context(close_summary: dict[str, Any], context: dict[str, Any]) -> None:
    related_object_ids = set(context.get("related_object_ids", []))
    link_ids = set(context.get("link_ids", []))
    object_ids = close_summary.get("object_ids", {})
    for section in object_ids:
        object_ids[section] = [
            object_id for object_id in object_ids.get(section, []) if object_id not in related_object_ids
        ]
    close_summary["link_ids"] = [
        link_id for link_id in close_summary.get("link_ids", []) if link_id not in link_ids
    ]
    close_summary["readiness"] = _close_summary_readiness(close_summary)


def _close_summary_readiness(close_summary: dict[str, Any]) -> str:
    object_ids = close_summary.get("object_ids", {})
    if object_ids.get("blockers"):
        return "blocked"
    if object_ids.get("risks"):
        return "conditional"
    return "ready"


def _tag_ref_matches_hidden(
    tag_ref: Any,
    taxonomy_state: dict[str, Any] | None,
    hidden: set[str],
) -> bool:
    if _normalize_text(tag_ref) in hidden:
        return True
    if not isinstance(tag_ref, str) or not taxonomy_state:
        return False

    nodes_by_id = taxonomy_by_id(taxonomy_state)
    candidate_ids = _related_taxonomy_ids(tag_ref, nodes_by_id, taxonomy_state)
    for node_id in candidate_ids:
        node = nodes_by_id.get(node_id)
        values = [node_id]
        if node:
            values.append(node.get("label"))
            values.extend(node.get("aliases", []))
        if any(_normalize_text(value) in hidden for value in values if value):
            return True
    return False


def _related_taxonomy_ids(
    tag_ref: str,
    nodes_by_id: dict[str, dict[str, Any]],
    taxonomy_state: dict[str, Any],
) -> list[str]:
    related = replacement_closure(taxonomy_state, [tag_ref], include_start=True)
    queue = list(related)
    while queue:
        node_id = queue.pop(0)
        node = nodes_by_id.get(node_id)
        parent_id = node.get("parent_id") if node else None
        if parent_id and parent_id not in related:
            related.append(parent_id)
            queue.append(parent_id)
    return _stable_unique(related)


def _extend_hidden_strings(context: dict[str, Any], values: Iterable[str | None]) -> None:
    context["hidden_strings"].extend(value for value in values if value)


def _normalized_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_ids": _stable_unique(context.get("session_ids", [])),
        "related_object_ids": _stable_unique(context.get("related_object_ids", [])),
        "link_ids": _stable_unique(context.get("link_ids", [])),
        "hidden_strings": _stable_unique(context.get("hidden_strings", [])),
    }


def _has_suppressed_targets(context: dict[str, Any]) -> bool:
    return any(context.get(key) for key in ("related_object_ids", "link_ids", "hidden_strings"))


def _stable_unique(values: Iterable[Any]) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().casefold().split())


def _first_visible_text(candidates: Iterable[str | None], hidden: set[str]) -> str:
    for candidate in candidates:
        if candidate and _normalize_text(candidate) not in hidden:
            return candidate
    return "suppressed-session-context"
