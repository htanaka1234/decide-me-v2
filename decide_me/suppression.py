from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


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


def suppressed_hidden_strings(project_state: dict[str, Any]) -> set[str]:
    hidden: set[str] = set()
    for resolved in project_state.get("session_graph", {}).get("resolved_conflicts", []):
        context = resolved.get("suppressed_context", {})
        hidden.update(_normalize_text(value) for value in context.get("hidden_strings", []))
    return {value for value in hidden if value}


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
    session: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    context = semantic_suppression_context_for_session(session, resolution)
    if not _has_suppressed_targets(context):
        return context

    hidden_strings = set(context["hidden_strings"])
    _sanitize_session_text(session, hidden_strings)
    _sanitize_classification(session, hidden_strings)
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
    return _has_suppressed_targets(context)


def has_suppressed_context_remainders(session: dict[str, Any], context: dict[str, Any]) -> bool:
    decision_ids = set(context.get("decision_ids", []))
    action_slice_names = set(context.get("action_slice_names", []))
    workstream_names = set(context.get("workstream_names", []))
    hidden_strings = {_normalize_text(value) for value in context.get("hidden_strings", [])}

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
        close_summary.get("work_item_title"),
        close_summary.get("work_item_statement"),
        *session.get("classification", {}).get("search_terms", []),
    ]
    return any(_normalize_text(value) in hidden_strings for value in text_values if value)


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


def _sanitize_classification(session: dict[str, Any], hidden_strings: set[str]) -> None:
    hidden = {_normalize_text(value) for value in hidden_strings}
    classification = session.get("classification", {})
    classification["search_terms"] = [
        term for term in classification.get("search_terms", []) if _normalize_text(term) not in hidden
    ]


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
