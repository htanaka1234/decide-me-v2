from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from typing import Any, Iterable

from decide_me.constants import (
    DECISION_STACK_LAYER_ORDER,
    DECISION_STACK_LAYERS,
    GRAPH_TRAVERSAL_DIRECTIONS,
    INFLUENCE_FORWARD_RELATIONS,
    INFLUENCE_REVERSED_RELATIONS,
    LINK_RELATIONS,
)


AdjacencyItem = dict[str, Any]
GraphIndex = dict[str, Any]


def build_graph_index(project_state: dict[str, Any]) -> GraphIndex:
    graph = _require_graph(project_state)
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_id: dict[str, dict[str, Any]] = {}

    for node in graph["nodes"]:
        node_payload = _require_dict(node, "project_state.graph.nodes[]")
        object_id = _require_string(node_payload, "object_id", "project_state.graph.nodes[]")
        if object_id in nodes_by_id:
            raise ValueError(f"duplicate graph node object_id: {object_id}")
        layer = _require_string(node_payload, "layer", f"graph node {object_id}")
        if layer not in DECISION_STACK_LAYERS:
            raise ValueError(f"graph node {object_id} has unknown layer: {layer}")
        nodes_by_id[object_id] = deepcopy(node_payload)

    adjacency = _empty_adjacency(nodes_by_id)
    for edge in graph["edges"]:
        edge_payload = _require_dict(edge, "project_state.graph.edges[]")
        link_id = _require_string(edge_payload, "link_id", "project_state.graph.edges[]")
        if link_id in edges_by_id:
            raise ValueError(f"duplicate graph edge link_id: {link_id}")
        source_id = _require_string(edge_payload, "source_object_id", f"graph edge {link_id}")
        target_id = _require_string(edge_payload, "target_object_id", f"graph edge {link_id}")
        relation = _require_string(edge_payload, "relation", f"graph edge {link_id}")
        if relation not in LINK_RELATIONS:
            raise ValueError(f"graph edge {link_id} has unknown relation: {relation}")
        if source_id not in nodes_by_id:
            raise ValueError(f"graph edge {link_id} source_object_id references missing object: {source_id}")
        if target_id not in nodes_by_id:
            raise ValueError(f"graph edge {link_id} target_object_id references missing object: {target_id}")

        copied_edge = deepcopy(edge_payload)
        edges_by_id[link_id] = copied_edge
        _append_oriented_edge(adjacency, "raw", copied_edge, source_id, target_id)
        if relation in INFLUENCE_REVERSED_RELATIONS:
            _append_oriented_edge(adjacency, "influence", copied_edge, target_id, source_id)
        elif relation in INFLUENCE_FORWARD_RELATIONS:
            _append_oriented_edge(adjacency, "influence", copied_edge, source_id, target_id)
        else:
            raise ValueError(f"graph edge {link_id} relation lacks influence traversal direction: {relation}")

    for direction_adjacency in adjacency.values():
        for side in ("downstream", "upstream"):
            for items in direction_adjacency[side].values():
                items.sort(key=lambda item: (item["edge"]["link_id"], item["object_id"]))

    layers: dict[str, list[str]] = {layer: [] for layer in DECISION_STACK_LAYER_ORDER}
    for object_id, node in nodes_by_id.items():
        layers[node["layer"]].append(object_id)
    for object_ids in layers.values():
        object_ids.sort()

    return {
        "nodes_by_id": nodes_by_id,
        "edges_by_id": edges_by_id,
        "adjacency": adjacency,
        "raw_downstream": adjacency["raw"]["downstream"],
        "raw_upstream": adjacency["raw"]["upstream"],
        "influence_downstream": adjacency["influence"]["downstream"],
        "influence_upstream": adjacency["influence"]["upstream"],
        "layers": layers,
    }


def direct_downstream(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "raw",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[str]:
    return _direct(index, object_id, "downstream", direction=direction, relations=relations, layers=layers)


def direct_upstream(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "raw",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[str]:
    return _direct(index, object_id, "upstream", direction=direction, relations=relations, layers=layers)


def descendants(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "raw",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[str]:
    object_ids, _edge_ids = _walk(
        index,
        object_id,
        "downstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    return object_ids


def ancestors(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "raw",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[str]:
    object_ids, _edge_ids = _walk(
        index,
        object_id,
        "upstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    return object_ids


def objects_by_layer(
    index: GraphIndex,
    *,
    layers: str | Iterable[str] | None = None,
) -> dict[str, list[str]]:
    _require_index(index)
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    return {
        layer: list(index["layers"].get(layer, []))
        for layer in DECISION_STACK_LAYER_ORDER
        if layer_filter is None or layer in layer_filter
    }


def bounded_subgraph(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "raw",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = 1,
) -> dict[str, list[dict[str, Any]]]:
    _validate_object_id(index, object_id)
    downstream_ids, downstream_edge_ids = _walk(
        index,
        object_id,
        "downstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    upstream_ids, upstream_edge_ids = _walk(
        index,
        object_id,
        "upstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    node_ids = {object_id, *downstream_ids, *upstream_ids}
    edge_ids = set(downstream_edge_ids) | set(upstream_edge_ids)
    return {
        "nodes": [deepcopy(index["nodes_by_id"][node_id]) for node_id in sorted(node_ids)],
        "edges": [deepcopy(index["edges_by_id"][edge_id]) for edge_id in sorted(edge_ids)],
    }


def _direct(
    index: GraphIndex,
    object_id: str,
    side: str,
    *,
    direction: str,
    relations: str | Iterable[str] | None,
    layers: str | Iterable[str] | None,
) -> list[str]:
    _validate_object_id(index, object_id)
    direction = _validate_direction(direction)
    relation_filter = _normalize_filter(relations, LINK_RELATIONS, "relation")
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    return _stable_object_ids(
        item["object_id"]
        for item in _filtered_adjacency_items(index, object_id, side, direction, relation_filter, layer_filter)
    )


def _walk(
    index: GraphIndex,
    object_id: str,
    side: str,
    *,
    direction: str,
    relations: str | Iterable[str] | None,
    layers: str | Iterable[str] | None,
    max_depth: int | None,
) -> tuple[list[str], list[str]]:
    _validate_object_id(index, object_id)
    direction = _validate_direction(direction)
    relation_filter = _normalize_filter(relations, LINK_RELATIONS, "relation")
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    if max_depth is not None and max_depth < 0:
        raise ValueError("max_depth must be greater than or equal to 0")

    queue: deque[tuple[str, int]] = deque([(object_id, 0)])
    visited = {object_id}
    ordered_object_ids: list[str] = []
    ordered_edge_ids: list[str] = []
    seen_edge_ids: set[str] = set()

    while queue:
        current_id, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for item in _filtered_adjacency_items(index, current_id, side, direction, relation_filter, layer_filter):
            edge_id = item["edge"]["link_id"]
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                ordered_edge_ids.append(edge_id)
            next_id = item["object_id"]
            if next_id in visited:
                continue
            visited.add(next_id)
            ordered_object_ids.append(next_id)
            queue.append((next_id, depth + 1))

    return ordered_object_ids, ordered_edge_ids


def _filtered_adjacency_items(
    index: GraphIndex,
    object_id: str,
    side: str,
    direction: str,
    relation_filter: set[str] | None,
    layer_filter: set[str] | None,
) -> list[AdjacencyItem]:
    items = index["adjacency"][direction][side].get(object_id, [])
    selected: list[AdjacencyItem] = []
    for item in items:
        edge = item["edge"]
        if relation_filter is not None and edge["relation"] not in relation_filter:
            continue
        neighbor = index["nodes_by_id"][item["object_id"]]
        if layer_filter is not None and neighbor["layer"] not in layer_filter:
            continue
        selected.append(item)
    return selected


def _append_oriented_edge(
    adjacency: dict[str, dict[str, dict[str, list[AdjacencyItem]]]],
    direction: str,
    edge: dict[str, Any],
    source_id: str,
    target_id: str,
) -> None:
    adjacency[direction]["downstream"][source_id].append({"object_id": target_id, "edge": edge})
    adjacency[direction]["upstream"][target_id].append({"object_id": source_id, "edge": edge})


def _empty_adjacency(nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, list[AdjacencyItem]]]]:
    return {
        direction: {
            "downstream": defaultdict(list, {object_id: [] for object_id in nodes_by_id}),
            "upstream": defaultdict(list, {object_id: [] for object_id in nodes_by_id}),
        }
        for direction in GRAPH_TRAVERSAL_DIRECTIONS
    }


def _require_graph(project_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    graph = project_state.get("graph")
    if not isinstance(graph, dict):
        raise ValueError("project_state.graph must be an object")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        raise ValueError("project_state.graph.nodes must be a list")
    if not isinstance(edges, list):
        raise ValueError("project_state.graph.edges must be a list")
    return {"nodes": nodes, "edges": edges}


def _require_index(index: GraphIndex) -> None:
    for key in ("nodes_by_id", "edges_by_id", "adjacency", "layers"):
        if key not in index:
            raise ValueError(f"graph index is missing {key}")


def _validate_object_id(index: GraphIndex, object_id: str) -> None:
    _require_index(index)
    if object_id not in index["nodes_by_id"]:
        raise ValueError(f"unknown object_id: {object_id}")


def _validate_direction(direction: str) -> str:
    if direction not in GRAPH_TRAVERSAL_DIRECTIONS:
        allowed = ", ".join(sorted(GRAPH_TRAVERSAL_DIRECTIONS))
        raise ValueError(f"direction must be one of: {allowed}")
    return direction


def _normalize_filter(value: str | Iterable[str] | None, allowed: set[str], label: str) -> set[str] | None:
    if value is None:
        return None
    selected = {value} if isinstance(value, str) else set(value)
    unknown = sorted(selected - allowed)
    if unknown:
        raise ValueError(f"unknown {label} filter: {', '.join(unknown)}")
    return selected


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def _stable_object_ids(object_ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for object_id in object_ids:
        if object_id in seen:
            continue
        seen.add(object_id)
        ordered.append(object_id)
    return ordered
