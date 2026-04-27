from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from decide_me.taxonomy import replacement_closure, taxonomy_by_id


SUMMARY_DECISION_SECTIONS = (
    "accepted_decisions",
    "deferred_decisions",
    "unresolved_blockers",
    "unresolved_risks",
)


def empty_suppressed_context() -> dict[str, Any]:
    return {
        "session_ids": [],
        "decision_ids": [],
        "action_slice_names": [],
        "workstream_names": [],
        "hidden_strings": [],
    }


def suppressed_decision_ids(project_state: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for resolved in project_state.get("session_graph", {}).get("resolved_conflicts", []):
        context = resolved.get("suppressed_context", {})
        ids.update(context.get("decision_ids", []))
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
            _add_decision_context(context, close_summary, decision_id)
    elif kind == "action_slice":
        name = scope.get("name")
        if name:
            _add_action_slice_context(context, close_summary, name)
    elif kind == "workstream":
        name = scope.get("name")
        if name:
            _add_workstream_context(context, close_summary, name)
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
        return bool(
            context.get("decision_ids")
            or context.get("action_slice_names")
            or context.get("workstream_names")
        )
    return _has_suppressed_targets(context)


def has_suppressed_context_remainders(
    session: dict[str, Any],
    context: dict[str, Any],
    taxonomy_state: dict[str, Any] | None = None,
) -> bool:
    decision_ids = set(context.get("decision_ids", []))
    action_slice_names = set(context.get("action_slice_names", []))
    workstream_names = set(context.get("workstream_names", []))
    hidden_strings = {_normalize_text(value) for value in context.get("hidden_strings", [])}

    if decision_ids & set(session.get("session", {}).get("decision_ids", [])):
        return True
    if session.get("summary", {}).get("active_decision_id") in decision_ids:
        return True
    proposal = session.get("working_state", {}).get("active_proposal", {})
    if proposal.get("target_id") in decision_ids:
        return True

    close_summary = session.get("close_summary", {})
    for section in SUMMARY_DECISION_SECTIONS:
        if any(item.get("id") in decision_ids for item in close_summary.get(section, [])):
            return True
    for action_slice in close_summary.get("candidate_action_slices", []):
        if action_slice.get("decision_id") in decision_ids or action_slice.get("name") in action_slice_names:
            return True
    for workstream in close_summary.get("candidate_workstreams", []):
        if workstream.get("name") in workstream_names:
            return True
        if decision_ids & set(workstream.get("scope", [])):
            return True
        if decision_ids & set(workstream.get("implementation_ready_scope", [])):
            return True

    text_values = [
        session.get("summary", {}).get("latest_summary"),
        session.get("summary", {}).get("current_question_preview"),
        session.get("working_state", {}).get("current_question"),
        proposal.get("question"),
        proposal.get("recommendation"),
        proposal.get("why"),
        proposal.get("if_not"),
        close_summary.get("work_item_title"),
        close_summary.get("work_item_statement"),
        *session.get("classification", {}).get("search_terms", []),
    ]
    if any(_normalize_text(value) in hidden_strings for value in text_values if value):
        return True

    classification = session.get("classification", {})
    return any(
        _tag_ref_matches_hidden(tag_ref, taxonomy_state, hidden_strings)
        for tag_ref in classification.get("assigned_tags", [])
    )


def _add_decision_context(context: dict[str, Any], close_summary: dict[str, Any], decision_id: str) -> None:
    found = False
    for section in SUMMARY_DECISION_SECTIONS:
        for item in close_summary.get(section, []):
            if item.get("id") == decision_id:
                found = True
                _extend_hidden_strings(context, _item_hidden_strings(item))

    for action_slice in close_summary.get("candidate_action_slices", []):
        if action_slice.get("decision_id") == decision_id:
            found = True
            context["action_slice_names"].append(action_slice.get("name"))
            _extend_hidden_strings(context, _item_hidden_strings(action_slice))

    for workstream in close_summary.get("candidate_workstreams", []):
        if decision_id in set(workstream.get("scope", [])) or decision_id in set(
            workstream.get("implementation_ready_scope", [])
        ):
            found = True
            _extend_hidden_strings(context, _item_hidden_strings(workstream))

    if found:
        context["decision_ids"].append(decision_id)


def _add_action_slice_context(context: dict[str, Any], close_summary: dict[str, Any], name: str) -> None:
    for action_slice in close_summary.get("candidate_action_slices", []):
        if action_slice.get("name") != name:
            continue
        context["action_slice_names"].append(name)
        if action_slice.get("decision_id"):
            context["decision_ids"].append(action_slice["decision_id"])
        _extend_hidden_strings(context, _item_hidden_strings(action_slice))
        decision_id = action_slice.get("decision_id")
        if decision_id:
            for section in SUMMARY_DECISION_SECTIONS:
                for item in close_summary.get(section, []):
                    if item.get("id") == decision_id:
                        _extend_hidden_strings(context, _item_hidden_strings(item))


def _add_workstream_context(context: dict[str, Any], close_summary: dict[str, Any], name: str) -> None:
    for workstream in close_summary.get("candidate_workstreams", []):
        if workstream.get("name") == name:
            context["workstream_names"].append(name)
            _extend_hidden_strings(context, _item_hidden_strings(workstream))


def _add_session_context(context: dict[str, Any], close_summary: dict[str, Any]) -> None:
    _extend_hidden_strings(
        context,
        [
            close_summary.get("work_item_title"),
            close_summary.get("work_item_statement"),
        ],
    )
    for section in SUMMARY_DECISION_SECTIONS:
        for item in close_summary.get(section, []):
            if item.get("id"):
                context["decision_ids"].append(item["id"])
            _extend_hidden_strings(context, _item_hidden_strings(item))
    for action_slice in close_summary.get("candidate_action_slices", []):
        if action_slice.get("name"):
            context["action_slice_names"].append(action_slice["name"])
        if action_slice.get("decision_id"):
            context["decision_ids"].append(action_slice["decision_id"])
        _extend_hidden_strings(context, _item_hidden_strings(action_slice))
    for workstream in close_summary.get("candidate_workstreams", []):
        if workstream.get("name"):
            context["workstream_names"].append(workstream["name"])
        _extend_hidden_strings(context, _item_hidden_strings(workstream))


def _sanitize_session_bindings_by_context(session: dict[str, Any], context: dict[str, Any]) -> None:
    decision_ids = set(context.get("decision_ids", []))
    if not decision_ids:
        return

    session_payload = session.get("session", {})
    session_payload["decision_ids"] = [
        decision_id
        for decision_id in session_payload.get("decision_ids", [])
        if decision_id not in decision_ids
    ]

    summary = session.get("summary", {})
    working_state = session.get("working_state", {})
    if summary.get("active_decision_id") in decision_ids:
        summary["active_decision_id"] = None
        summary["current_question_preview"] = None
        working_state["current_question_id"] = None
        working_state["current_question"] = None

    proposal = working_state.get("active_proposal", {})
    if proposal.get("target_id") in decision_ids:
        proposal["is_active"] = False
        proposal["inactive_reason"] = proposal.get("inactive_reason") or "semantic-conflict-resolved"
        proposal["target_type"] = None
        proposal["target_id"] = None
        proposal["question_id"] = None
        proposal["question"] = None
        proposal["recommendation"] = None
        proposal["why"] = None
        proposal["if_not"] = None


def _sanitize_session_text(session: dict[str, Any], hidden_strings: set[str]) -> None:
    hidden = {_normalize_text(value) for value in hidden_strings}
    for section, key in (
        (session["summary"], "latest_summary"),
        (session["summary"], "current_question_preview"),
        (session["working_state"], "current_question"),
    ):
        if _normalize_text(section.get(key)) in hidden:
            section[key] = None

    close_summary = session["close_summary"]
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
            close_summary.get("goal"),
            fallback_title,
        ],
        hidden,
    )
    if _normalize_text(close_summary.get("work_item_title")) in hidden:
        close_summary["work_item_title"] = fallback_title
    if _normalize_text(close_summary.get("work_item_statement")) in hidden:
        close_summary["work_item_statement"] = fallback_statement


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


def _sanitize_close_summary_by_context(close_summary: dict[str, Any], context: dict[str, Any]) -> None:
    decision_ids = set(context.get("decision_ids", []))
    action_slice_names = set(context.get("action_slice_names", []))
    workstream_names = set(context.get("workstream_names", []))

    if decision_ids:
        for section in SUMMARY_DECISION_SECTIONS:
            close_summary[section] = [
                item for item in close_summary.get(section, []) if item.get("id") not in decision_ids
            ]

    close_summary["candidate_action_slices"] = [
        item
        for item in close_summary.get("candidate_action_slices", [])
        if item.get("decision_id") not in decision_ids and item.get("name") not in action_slice_names
    ]

    accepted_ids = {item["id"] for item in close_summary.get("accepted_decisions", [])}
    workstreams: list[dict[str, Any]] = []
    for workstream in close_summary.get("candidate_workstreams", []):
        if workstream.get("name") in workstream_names:
            continue
        updated = deepcopy(workstream)
        if decision_ids:
            updated["scope"] = [item for item in updated.get("scope", []) if item not in decision_ids]
            updated["implementation_ready_scope"] = [
                item for item in updated.get("implementation_ready_scope", []) if item not in decision_ids
            ]
        if not updated.get("scope"):
            continue
        updated["accepted_count"] = len([item for item in updated.get("scope", []) if item in accepted_ids])
        _refresh_workstream_summary(updated)
        workstreams.append(updated)
    close_summary["candidate_workstreams"] = workstreams
    _refresh_close_summary_evidence_and_readiness(close_summary)


def _refresh_workstream_summary(workstream: dict[str, Any]) -> None:
    domain = str(workstream.get("name") or "workstream").removesuffix("-workstream")
    implementation_ready_scope = workstream.get("implementation_ready_scope", [])
    if implementation_ready_scope:
        workstream["summary"] = (
            f"Advance {domain} decisions for the current milestone. "
            f"{len(implementation_ready_scope)} implementation-ready slice(s) are already grounded."
        )
    else:
        workstream["summary"] = f"Advance {domain} decisions for the current milestone."


def _refresh_close_summary_evidence_and_readiness(close_summary: dict[str, Any]) -> None:
    visible_evidence_refs: list[str] = []
    for item in close_summary.get("accepted_decisions", []):
        visible_evidence_refs.extend(item.get("evidence_refs", []))
    for item in close_summary.get("candidate_action_slices", []):
        visible_evidence_refs.extend(item.get("evidence_refs", []))
    close_summary["evidence_refs"] = _stable_unique(visible_evidence_refs)
    close_summary["readiness"] = _close_summary_readiness(close_summary)


def _close_summary_readiness(close_summary: dict[str, Any]) -> str:
    if close_summary.get("unresolved_blockers"):
        return "blocked"
    if close_summary.get("unresolved_risks"):
        return "conditional"
    return "ready"


def _item_hidden_strings(item: dict[str, Any]) -> list[str]:
    values = [
        item.get("title"),
        item.get("name"),
        item.get("summary"),
        item.get("accepted_answer"),
        item.get("next_step"),
    ]
    return [str(value).strip() for value in values if value and str(value).strip()]


def _extend_hidden_strings(context: dict[str, Any], values: Iterable[str]) -> None:
    context["hidden_strings"].extend(value for value in values if value)


def _normalized_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_ids": _stable_unique(context.get("session_ids", [])),
        "decision_ids": _stable_unique(context.get("decision_ids", [])),
        "action_slice_names": _stable_unique(context.get("action_slice_names", [])),
        "workstream_names": _stable_unique(context.get("workstream_names", [])),
        "hidden_strings": _stable_unique(context.get("hidden_strings", [])),
    }


def _has_suppressed_targets(context: dict[str, Any]) -> bool:
    return any(
        context.get(key)
        for key in ("decision_ids", "action_slice_names", "workstream_names", "hidden_strings")
    )


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
