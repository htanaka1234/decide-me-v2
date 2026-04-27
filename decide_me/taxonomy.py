from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Any, Iterable

from decide_me.events import utc_now


TAG_PATH_PATTERN = re.compile(r"\s*(?:/|>|::)\s*")


def normalize_text(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())


def stable_unique(items: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    ordered: list[Any] = []
    for item in items:
        marker = json.dumps(item, ensure_ascii=True, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(item)
    return ordered


def split_tag_path(term: str) -> list[str]:
    parts = [part.strip() for part in TAG_PATH_PATTERN.split(term) if part.strip()]
    return parts or [term.strip()]


def taxonomy_nodes(taxonomy_state: dict[str, Any]) -> list[dict[str, Any]]:
    return taxonomy_state.setdefault("nodes", [])


def taxonomy_by_id(taxonomy_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in taxonomy_nodes(taxonomy_state) if node.get("id")}


def taxonomy_children(taxonomy_state: dict[str, Any]) -> dict[str | None, list[str]]:
    grouped: dict[str | None, list[str]] = defaultdict(list)
    for node in taxonomy_nodes(taxonomy_state):
        grouped[node.get("parent_id")].append(node["id"])
    return grouped


def default_taxonomy_state(now: str | None = None, last_event_id: str | None = None) -> dict[str, Any]:
    now = now or utc_now()
    nodes = [
        _node("AXIS-domain", "domain", "Domain", None, now),
        _node("domain:product", "domain", "product", "AXIS-domain", now),
        _node("domain:technical", "domain", "technical", "AXIS-domain", now, aliases=["engineering"]),
        _node("domain:data", "domain", "data", "AXIS-domain", now),
        _node("domain:ux", "domain", "ux", "AXIS-domain", now, aliases=["design"]),
        _node("domain:ops", "domain", "ops", "AXIS-domain", now, aliases=["operations"]),
        _node("domain:legal", "domain", "legal", "AXIS-domain", now),
        _node("domain:other", "domain", "other", "AXIS-domain", now),
        _node("AXIS-abstraction_level", "abstraction_level", "Abstraction Level", None, now),
        _node("level:strategy", "abstraction_level", "strategy", "AXIS-abstraction_level", now),
        _node(
            "level:architecture",
            "abstraction_level",
            "architecture",
            "AXIS-abstraction_level",
            now,
            aliases=["system"],
        ),
        _node("level:workflow", "abstraction_level", "workflow", "AXIS-abstraction_level", now),
        _node(
            "level:implementation",
            "abstraction_level",
            "implementation",
            "AXIS-abstraction_level",
            now,
            aliases=["code"],
        ),
    ]
    nodes = sorted(nodes, key=lambda node: node["id"])
    return {
        "schema_version": 3,
        "state": {"updated_at": now, "last_event_id": last_event_id},
        "required_axes": ["domain", "abstraction_level"],
        "nodes": nodes,
    }


def _node(
    node_id: str,
    axis: str,
    label: str,
    parent_id: str | None,
    now: str,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "axis": axis,
        "label": label,
        "aliases": aliases or [],
        "parent_id": parent_id,
        "replaced_by": [],
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def find_nodes(taxonomy_state: dict[str, Any], term: str, axis: str | None = None) -> list[str]:
    normalized = normalize_text(term)
    matches: list[str] = []
    for node in taxonomy_nodes(taxonomy_state):
        if axis and node.get("axis") != axis:
            continue
        labels = [node.get("id"), node.get("label"), *node.get("aliases", [])]
        if normalized in {normalize_text(label) for label in labels if label}:
            matches.append(node["id"])
    return stable_unique(matches)


def replacement_closure(
    taxonomy_state: dict[str, Any], start_ids: Iterable[str], include_start: bool = True
) -> list[str]:
    seeds = list(start_ids)
    nodes_by_id = taxonomy_by_id(taxonomy_state)
    queue = deque(seeds)
    visited: set[str] = set()
    ordered: list[str] = []

    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if include_start or node_id not in seeds:
            ordered.append(node_id)
        node = nodes_by_id.get(node_id)
        if node:
            queue.extend(node.get("replaced_by", []))

    return ordered


def descendant_closure(
    taxonomy_state: dict[str, Any], start_ids: Iterable[str], include_start: bool = True
) -> list[str]:
    seeds = list(start_ids)
    children = taxonomy_children(taxonomy_state)
    queue = deque(seeds)
    visited: set[str] = set()
    ordered: list[str] = []

    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if include_start or node_id not in seeds:
            ordered.append(node_id)
        queue.extend(children.get(node_id, []))

    return ordered


def expand_filter_ids(taxonomy_state: dict[str, Any], seed_ids: Iterable[str]) -> list[str]:
    descendants = descendant_closure(taxonomy_state, seed_ids, include_start=True)
    replacements = replacement_closure(taxonomy_state, descendants, include_start=True)
    return stable_unique(descendant_closure(taxonomy_state, replacements, include_start=True))


def ensure_term_path(
    taxonomy_state: dict[str, Any], term: str, axis: str | None = None, now: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    now = now or utc_now()
    parts = split_tag_path(term)
    nodes = taxonomy_nodes(taxonomy_state)
    created: list[dict[str, Any]] = []
    parent_id: str | None = None
    current_id: str | None = None

    for index, part in enumerate(parts):
        candidates = find_nodes(taxonomy_state, part, axis if index == 0 else None)
        existing_id = None
        for candidate in candidates:
            node = taxonomy_by_id(taxonomy_state).get(candidate)
            if node and node.get("parent_id") == parent_id:
                existing_id = candidate
                break

        if existing_id is None:
            node_id = f"tag:{normalize_text(part).replace(' ', '-')}"
            suffix = 1
            while any(node["id"] == node_id for node in nodes):
                suffix += 1
                node_id = f"tag:{normalize_text(part).replace(' ', '-')}-{suffix}"
            node = _node(node_id, axis or "tag", part, parent_id, now)
            nodes.append(node)
            created.append(node)
            existing_id = node_id

        current_id = existing_id
        parent_id = current_id

    if current_id is None:
        raise RuntimeError(f"failed to ensure taxonomy term: {term}")
    return current_id, created


def resolved_tag_refs(session_state: dict[str, Any], taxonomy_state: dict[str, Any]) -> list[str]:
    classification = session_state.get("classification", {})
    refs = list(classification.get("assigned_tags", []))
    replacements = replacement_closure(taxonomy_state, refs, include_start=False)
    return stable_unique([*refs, *replacements])


def resolved_tag_nodes(session_state: dict[str, Any], taxonomy_state: dict[str, Any]) -> list[dict[str, Any]]:
    nodes_by_id = taxonomy_by_id(taxonomy_state)
    return [
        nodes_by_id[tag_ref]
        for tag_ref in resolved_tag_refs(session_state, taxonomy_state)
        if tag_ref in nodes_by_id
    ]
