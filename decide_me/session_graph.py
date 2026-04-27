from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.events import SESSION_RELATIONSHIPS, utc_now
from decide_me.store import load_runtime, runtime_paths, transact


ACYCLIC_RELATIONSHIPS = {"derived_from", "refines", "supersedes", "depends_on"}


def _project_graph(bundle: dict[str, Any]) -> dict[str, Any]:
    project_state = bundle.get("project_state", {})
    return project_state.get("graph") or project_state.get("session_graph") or {
        "nodes": [],
        "edges": [],
        "resolved_conflicts": [],
        "inferred_candidates": [],
    }


def build_session_graph(
    bundle: dict[str, Any],
    *,
    include_inferred: bool = False,
    seed_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    sessions = bundle.get("sessions", {})
    graph = _project_graph(bundle)
    edges = sorted(
        [deepcopy(edge) for edge in graph.get("edges", [])],
        key=_edge_sort_key,
    )
    resolved_conflicts = sorted(
        [deepcopy(resolved) for resolved in graph.get("resolved_conflicts", [])],
        key=lambda item: item["conflict_id"],
    )
    explicit_pairs = {
        frozenset((edge["parent_session_id"], edge["child_session_id"]))
        for edge in edges
    }
    return {
        "nodes": [_session_node(session_id, sessions[session_id]) for session_id in sorted(sessions)],
        "edges": edges,
        "inferred_candidates": (
            infer_relationship_candidates(bundle, seed_session_ids=seed_session_ids)
            if include_inferred
            else []
        ),
        "resolved_conflicts": resolved_conflicts,
    }


def infer_relationship_candidates(
    bundle: dict[str, Any],
    *,
    seed_session_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    sessions = bundle.get("sessions", {})
    graph = _project_graph(bundle)
    edges = graph.get("edges", [])
    explicit_pairs = {
        frozenset((edge["parent_session_id"], edge["child_session_id"]))
        for edge in edges
    }
    return _infer_relationship_candidates(
        sessions,
        explicit_pairs,
        seed_session_ids=set(seed_session_ids or []) or None,
    )


def link_session(
    ai_dir: str,
    *,
    parent_session_id: str,
    child_session_id: str,
    relationship: str,
    reason: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    reason = _require_text(reason, "reason")
    evidence_refs = [ref.strip() for ref in (evidence_refs or []) if ref and ref.strip()]
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        _require_session(bundle, parent_session_id)
        _require_session(bundle, child_session_id)
        if parent_session_id == child_session_id:
            raise ValueError("parent_session_id and child_session_id must differ")
        if relationship not in SESSION_RELATIONSHIPS:
            allowed = ", ".join(sorted(SESSION_RELATIONSHIPS))
            raise ValueError(f"relationship must be one of: {allowed}")
        edges = _project_graph(bundle).get("edges", [])
        if _has_duplicate_link(edges, parent_session_id, child_session_id, relationship):
            raise ValueError("duplicate session_linked relationship")
        if relationship in ACYCLIC_RELATIONSHIPS and _would_create_link_cycle(
            edges,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
        ):
            raise ValueError("session_linked would create a session graph cycle")
        return [
            {
                "session_id": child_session_id,
                "event_type": "session_linked",
                "payload": {
                    "parent_session_id": parent_session_id,
                    "child_session_id": child_session_id,
                    "relationship": relationship,
                    "reason": reason,
                    "linked_at": now,
                    "evidence_refs": evidence_refs,
                },
            }
        ]

    events, bundle = transact(ai_dir, builder)
    edge = next(edge for edge in _project_graph(bundle)["edges"] if edge["event_id"] == events[0]["event_id"])
    return {"status": "ok", "edge": edge, "session_graph": _project_graph(bundle)}


def show_session_graph(
    ai_dir: str,
    *,
    session_id: str | None = None,
    include_inferred: bool = False,
) -> dict[str, Any]:
    bundle = load_runtime(runtime_paths(ai_dir))
    if include_inferred:
        graph = _session_graph_with_inferred(ai_dir, bundle, seed_session_ids=[session_id] if session_id else None)
    else:
        graph = deepcopy(_project_graph(bundle))
        graph["inferred_candidates"] = []
    result: dict[str, Any] = {"status": "ok", "session_graph": graph}
    if session_id:
        result["related_sessions"] = related_session_scope(bundle, [session_id])
    return result


def detect_session_conflicts(
    ai_dir: str,
    *,
    session_ids: list[str],
    include_related: bool = False,
) -> dict[str, Any]:
    bundle = load_runtime(runtime_paths(ai_dir))
    if not session_ids:
        raise ValueError("at least one session_id is required")
    for session_id in session_ids:
        _require_session(bundle, session_id)

    related = related_session_scope(bundle, session_ids) if include_related else [
        {
            "session_id": session_id,
            "distance": 0,
            "path": [session_id],
            "relationship_chain": [],
        }
        for session_id in sorted(set(session_ids))
    ]
    related_ids = [item["session_id"] for item in related]
    sessions = [bundle["sessions"][session_id] for session_id in related_ids]
    from decide_me.planner import detect_conflicts

    graph = deepcopy(_project_graph(bundle))
    graph["inferred_candidates"] = infer_relationship_candidates(bundle, seed_session_ids=related_ids)
    semantic_conflicts = detect_conflicts(
        sessions,
        resolved_conflicts=graph["resolved_conflicts"],
        include_resolved=True,
    )
    return {
        "status": "ok",
        "seed_session_ids": sorted(set(session_ids)),
        "related_sessions": related,
        "inferred_relationship_candidates": _filter_inferred_candidates(
            graph["inferred_candidates"],
            set(related_ids),
        ),
        "semantic_conflicts": semantic_conflicts,
        "resolved_conflicts": _filter_resolved_conflicts(graph["resolved_conflicts"], set(related_ids)),
    }


def resolve_session_conflict(
    ai_dir: str,
    *,
    conflict_id: str,
    winning_session_id: str,
    rejected_session_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    conflict_id = _require_text(conflict_id, "conflict_id")
    reason = _require_text(reason, "reason")
    rejected_session_ids = _normalize_session_ids(rejected_session_ids, "rejected_session_ids")
    if winning_session_id in rejected_session_ids:
        raise ValueError("winning_session_id must not be rejected")
    now = utc_now()

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        graph_conflicts = _explicit_graph_conflicts(bundle)
        try:
            conflict = next(item for item in graph_conflicts if item["conflict_id"] == conflict_id)
        except StopIteration as exc:
            raise ValueError(f"unknown unresolved session conflict: {conflict_id}") from exc

        conflict_sessions = set(conflict["session_ids"])
        if winning_session_id not in conflict_sessions:
            raise ValueError("winning_session_id must be in the selected conflict")
        for rejected_session_id in rejected_session_ids:
            if rejected_session_id not in conflict_sessions:
                raise ValueError("rejected_session_ids must be in the selected conflict")
        if not set(rejected_session_ids):
            raise ValueError("at least one rejected session is required")
        return [
            {
                "session_id": winning_session_id,
                "event_type": "semantic_conflict_resolved",
                "payload": {
                    "conflict_id": conflict_id,
                    "winning_session_id": winning_session_id,
                    "rejected_session_ids": rejected_session_ids,
                    "scope": deepcopy(conflict["scope"]),
                    "reason": reason,
                    "resolved_at": now,
                },
            }
        ]

    events, bundle = transact(ai_dir, builder)
    resolved = next(
        item
        for item in _project_graph(bundle)["resolved_conflicts"]
        if item["event_id"] == events[0]["event_id"]
    )
    return {
        "status": "ok",
        "resolution": resolved,
        "session_graph": _project_graph(bundle),
    }


def related_session_scope(bundle: dict[str, Any], seed_session_ids: list[str]) -> list[dict[str, Any]]:
    sessions = bundle.get("sessions", {})
    seeds = sorted(set(seed_session_ids))
    for session_id in seeds:
        _require_session(bundle, session_id)

    adjacency: dict[str, list[tuple[str, dict[str, Any], str]]] = {}
    for edge in _project_graph(bundle).get("edges", []):
        parent = edge["parent_session_id"]
        child = edge["child_session_id"]
        adjacency.setdefault(parent, []).append((child, edge, "parent-to-child"))
        adjacency.setdefault(child, []).append((parent, edge, "child-to-parent"))
    for session_id in adjacency:
        adjacency[session_id].sort(key=lambda item: (item[0], item[1]["relationship"], item[2]))

    queue: list[dict[str, Any]] = [
        {"session_id": session_id, "distance": 0, "path": [session_id], "relationship_chain": []}
        for session_id in seeds
    ]
    visited: dict[str, dict[str, Any]] = {}
    while queue:
        current = queue.pop(0)
        session_id = current["session_id"]
        previous = visited.get(session_id)
        if previous and _scope_sort_key(previous) <= _scope_sort_key(current):
            continue
        visited[session_id] = current
        for next_session_id, edge, direction in adjacency.get(session_id, []):
            if next_session_id not in sessions:
                continue
            if next_session_id in current["path"]:
                continue
            chain_item = {
                "from_session_id": session_id,
                "to_session_id": next_session_id,
                "relationship": edge["relationship"],
                "direction": direction,
            }
            queue.append(
                {
                    "session_id": next_session_id,
                    "distance": current["distance"] + 1,
                    "path": [*current["path"], next_session_id],
                    "relationship_chain": [*current["relationship_chain"], chain_item],
                }
            )
    return sorted(visited.values(), key=_scope_sort_key)


def _explicit_graph_conflicts(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    graph = _project_graph(bundle)
    conflicts: list[dict[str, Any]] = []
    seen_conflict_ids: set[str] = set()
    for component_session_ids in _explicit_components(bundle):
        if len(component_session_ids) < 2:
            continue
        from decide_me.planner import detect_conflicts

        component_conflicts = detect_conflicts(
            [bundle["sessions"][session_id] for session_id in component_session_ids],
            resolved_conflicts=graph["resolved_conflicts"],
        )
        for conflict in component_conflicts:
            if conflict["conflict_id"] in seen_conflict_ids:
                continue
            seen_conflict_ids.add(conflict["conflict_id"])
            conflicts.append(conflict)
    return sorted(conflicts, key=lambda item: item["conflict_id"])


def _explicit_components(bundle: dict[str, Any]) -> list[list[str]]:
    graph = _project_graph(bundle)
    sessions = set(bundle["sessions"])
    adjacency: dict[str, set[str]] = {session_id: set() for session_id in sessions}
    for edge in graph.get("edges", []):
        parent = edge["parent_session_id"]
        child = edge["child_session_id"]
        if parent in sessions and child in sessions:
            adjacency[parent].add(child)
            adjacency[child].add(parent)
    components: list[list[str]] = []
    visited: set[str] = set()
    for session_id in sorted(sessions):
        if session_id in visited:
            continue
        stack = [session_id]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(sorted(adjacency[current] - component, reverse=True))
        visited.update(component)
        if len(component) > 1:
            components.append(sorted(component))
    return components


def _has_duplicate_link(
    edges: list[dict[str, Any]],
    parent_session_id: str,
    child_session_id: str,
    relationship: str,
) -> bool:
    return any(
        edge.get("parent_session_id") == parent_session_id
        and edge.get("child_session_id") == child_session_id
        and edge.get("relationship") == relationship
        for edge in edges
    )


def _would_create_link_cycle(
    edges: list[dict[str, Any]],
    *,
    parent_session_id: str,
    child_session_id: str,
) -> bool:
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("relationship") not in ACYCLIC_RELATIONSHIPS:
            continue
        adjacency.setdefault(edge["parent_session_id"], set()).add(edge["child_session_id"])

    stack = [child_session_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == parent_session_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(sorted(adjacency.get(current, set()), reverse=True))
    return False


def _session_node(session_id: str, session: dict[str, Any]) -> dict[str, Any]:
    close_summary = session["close_summary"]
    return {
        "session_id": session_id,
        "status": session["session"]["lifecycle"]["status"],
        "decision_ids": list(session["session"].get("decision_ids", [])),
        "close_summary_preview": {
            "work_item_title": close_summary.get("work_item_title"),
            "readiness": close_summary.get("readiness"),
            "latest_summary": session["summary"].get("latest_summary"),
        },
    }


def _infer_relationship_candidates(
    sessions: dict[str, dict[str, Any]],
    explicit_pairs: set[frozenset[str]],
    *,
    seed_session_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    session_ids = sorted(sessions)
    for index, left_id in enumerate(session_ids):
        for right_id in session_ids[index + 1 :]:
            if seed_session_ids is not None and left_id not in seed_session_ids and right_id not in seed_session_ids:
                continue
            if frozenset((left_id, right_id)) in explicit_pairs:
                continue
            left = sessions[left_id]
            right = sessions[right_id]
            shared_decisions = sorted(set(left["session"].get("decision_ids", [])) & set(right["session"].get("decision_ids", [])))
            if shared_decisions:
                candidates.append(
                    _candidate(
                        "shared-decision-ids",
                        "derived_from",
                        [left_id, right_id],
                        "Sessions share decision ids.",
                        "medium",
                        {"decision_ids": shared_decisions},
                    )
                )
            candidates.extend(_accepted_answer_candidates(left_id, left, right_id, right))
            candidates.extend(_workstream_candidates(left_id, left, right_id, right))
            candidates.extend(_action_slice_candidates(left_id, left, right_id, right))
    return sorted(candidates, key=lambda item: item["candidate_id"])


def _session_graph_with_inferred(
    ai_dir: str,
    bundle: dict[str, Any],
    *,
    seed_session_ids: list[str] | None,
) -> dict[str, Any]:
    if seed_session_ids:
        return build_session_graph(bundle, include_inferred=True, seed_session_ids=seed_session_ids)

    paths = runtime_paths(ai_dir)
    project_head = bundle["project_state"]["state"].get("project_head")
    cached = _load_graph_cache(paths.session_graph_cache, project_head)
    if cached is not None:
        return cached

    graph = build_session_graph(bundle, include_inferred=True)
    _write_graph_cache(paths.session_graph_cache, project_head, graph)
    return graph


def _load_graph_cache(path: Path, project_head: str | None) -> dict[str, Any] | None:
    if not project_head or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("project_head") != project_head:
        return None
    graph = payload.get("session_graph")
    return deepcopy(graph) if isinstance(graph, dict) else None


def _write_graph_cache(path: Path, project_head: str | None, graph: dict[str, Any]) -> None:
    if not project_head:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {"project_head": project_head, "session_graph": graph}
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)


def _accepted_answer_candidates(
    left_id: str, left: dict[str, Any], right_id: str, right: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    left_answers = _accepted_answers_by_decision(left)
    right_answers = _accepted_answers_by_decision(right)
    for decision_id in sorted(set(left_answers) & set(right_answers)):
        if left_answers[decision_id] == right_answers[decision_id]:
            continue
        candidates.append(
            _candidate(
                "accepted-answer-mismatch",
                "contradicts",
                [left_id, right_id],
                "Accepted answers differ for the same decision.",
                "high",
                {"decision_id": decision_id},
            )
        )
    return candidates


def _workstream_candidates(
    left_id: str, left: dict[str, Any], right_id: str, right: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    left_workstreams = {item["name"]: set(item.get("scope", [])) for item in left["close_summary"]["candidate_workstreams"]}
    right_workstreams = {item["name"]: set(item.get("scope", [])) for item in right["close_summary"]["candidate_workstreams"]}
    for name in sorted(set(left_workstreams) & set(right_workstreams)):
        if left_workstreams[name] == right_workstreams[name]:
            continue
        candidates.append(
            _candidate(
                "workstream-scope-overlap",
                "refines",
                [left_id, right_id],
                "Workstream names overlap with different scopes.",
                "medium",
                {"name": name, "shared_scope": sorted(left_workstreams[name] & right_workstreams[name])},
            )
        )
    return candidates


def _action_slice_candidates(
    left_id: str, left: dict[str, Any], right_id: str, right: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    left_actions = {
        item["name"]: item.get("responsibility")
        for item in left["close_summary"]["candidate_action_slices"]
    }
    right_actions = {
        item["name"]: item.get("responsibility")
        for item in right["close_summary"]["candidate_action_slices"]
    }
    for name in sorted(set(left_actions) & set(right_actions)):
        if left_actions[name] == right_actions[name]:
            continue
        candidates.append(
            _candidate(
                "action-slice-responsibility-mismatch",
                "contradicts",
                [left_id, right_id],
                "Action slice responsibilities differ.",
                "high",
                {"name": name},
            )
        )
    return candidates


def _candidate(
    kind: str,
    relationship: str,
    session_ids: list[str],
    reason: str,
    confidence: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    ordered_session_ids = sorted(session_ids)
    return {
        "candidate_id": _stable_id("I", kind, ordered_session_ids, evidence),
        "kind": kind,
        "suggested_relationship": relationship,
        "session_ids": ordered_session_ids,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
    }


def _accepted_answers_by_decision(session: dict[str, Any]) -> dict[str, str | None]:
    return {
        item["id"]: item.get("accepted_answer")
        for item in session["close_summary"].get("accepted_decisions", [])
    }


def _filter_inferred_candidates(candidates: list[dict[str, Any]], session_ids: set[str]) -> list[dict[str, Any]]:
    return [
        deepcopy(candidate)
        for candidate in candidates
        if set(candidate["session_ids"]) & session_ids
    ]


def _filter_resolved_conflicts(resolved_conflicts: list[dict[str, Any]], session_ids: set[str]) -> list[dict[str, Any]]:
    return [
        deepcopy(resolved)
        for resolved in resolved_conflicts
        if set(resolved["scope"].get("session_ids", [])) & session_ids
    ]


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        edge["parent_session_id"],
        edge["child_session_id"],
        edge["relationship"],
        edge["event_id"],
    )


def _scope_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (item["distance"], "/".join(item["path"]), item["session_id"])


def _stable_id(prefix: str, kind: str, session_ids: list[str], scope: dict[str, Any]) -> str:
    import hashlib
    import json

    material = json.dumps(
        {"kind": kind, "session_ids": sorted(session_ids), "scope": scope},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def _normalize_session_ids(session_ids: list[str], label: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for session_id in session_ids:
        candidate = session_id.strip()
        if not candidate:
            raise ValueError(f"{label} must contain non-empty session ids")
        if candidate in seen:
            raise ValueError(f"{label} contains duplicate session id: {candidate}")
        seen.add(candidate)
        normalized.append(candidate)
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _require_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        return bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()
