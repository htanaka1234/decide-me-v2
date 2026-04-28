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
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    return _direct(index, object_id, "downstream", direction=direction, relations=relations, layers=layers)


def direct_upstream(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    return _direct(index, object_id, "upstream", direction=direction, relations=relations, layers=layers)


def descendants(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[dict[str, Any]]:
    items, _edge_ids = _walk(
        index,
        object_id,
        "downstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    return items


def ancestors(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[dict[str, Any]]:
    items, _edge_ids = _walk(
        index,
        object_id,
        "upstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    return items


def direct_downstream_ids(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[str]:
    return _stable_object_ids(
        item["object_id"]
        for item in direct_downstream(index, object_id, direction=direction, relations=relations, layers=layers)
    )


def direct_upstream_ids(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> list[str]:
    return _stable_object_ids(
        item["object_id"]
        for item in direct_upstream(index, object_id, direction=direction, relations=relations, layers=layers)
    )


def descendant_ids(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[str]:
    return _stable_object_ids(
        item["object_id"]
        for item in descendants(
            index,
            object_id,
            direction=direction,
            relations=relations,
            layers=layers,
            max_depth=max_depth,
        )
    )


def ancestor_ids(
    index: GraphIndex,
    object_id: str,
    *,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> list[str]:
    return _stable_object_ids(
        item["object_id"]
        for item in ancestors(
            index,
            object_id,
            direction=direction,
            relations=relations,
            layers=layers,
            max_depth=max_depth,
        )
    )


def objects_by_layer(
    project_state: dict[str, Any],
    layer: str,
    *,
    include_invalidated: bool = False,
) -> list[dict[str, Any]]:
    if layer not in DECISION_STACK_LAYERS:
        raise ValueError(f"unknown layer: {layer}")
    graph = _require_graph(project_state)
    nodes = []
    for node in graph["nodes"]:
        node_payload = _require_dict(node, "project_state.graph.nodes[]")
        if node_payload.get("layer") != layer:
            continue
        if not include_invalidated and node_payload.get("is_invalidated") is True:
            continue
        nodes.append(deepcopy(node_payload))
    return sorted(nodes, key=lambda item: item["object_id"])


def bounded_subgraph(
    index: GraphIndex,
    object_id: str,
    *,
    upstream_depth: int = 1,
    downstream_depth: int = 2,
    direction: str = "influence",
    relations: str | Iterable[str] | None = None,
    layers: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    _validate_object_id(index, object_id)
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    downstream_records, downstream_edge_ids = _walk_records(
        index,
        object_id,
        "downstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=downstream_depth,
    )
    upstream_records, upstream_edge_ids = _walk_records(
        index,
        object_id,
        "upstream",
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=upstream_depth,
    )
    node_ids, edge_ids = _bounded_subgraph_ids(
        index,
        object_id,
        [*downstream_records, *upstream_records],
        [*downstream_edge_ids, *upstream_edge_ids],
        layer_filter,
    )
    return {
        "root_object_id": object_id,
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
) -> list[dict[str, Any]]:
    _validate_object_id(index, object_id)
    direction = _validate_direction(direction)
    relation_filter = _normalize_filter(relations, LINK_RELATIONS, "relation")
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    return [
        _context_item(index, item, distance=1)
        for item in _filtered_adjacency_items(index, object_id, side, direction, relation_filter)
        if _matches_layer(index, item["object_id"], layer_filter)
    ]


def _walk(
    index: GraphIndex,
    object_id: str,
    side: str,
    *,
    direction: str,
    relations: str | Iterable[str] | None,
    layers: str | Iterable[str] | None,
    max_depth: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    records, ordered_edge_ids = _walk_records(
        index,
        object_id,
        side,
        direction=direction,
        relations=relations,
        layers=layers,
        max_depth=max_depth,
    )
    return [record["item"] for record in records], ordered_edge_ids


def _walk_records(
    index: GraphIndex,
    object_id: str,
    side: str,
    *,
    direction: str,
    relations: str | Iterable[str] | None,
    layers: str | Iterable[str] | None,
    max_depth: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    _validate_object_id(index, object_id)
    direction = _validate_direction(direction)
    relation_filter = _normalize_filter(relations, LINK_RELATIONS, "relation")
    layer_filter = _normalize_filter(layers, DECISION_STACK_LAYERS, "layer")
    if max_depth is not None and max_depth < 0:
        raise ValueError("max_depth must be greater than or equal to 0")

    queue: deque[tuple[str, int, list[str], list[str]]] = deque([(object_id, 0, [object_id], [])])
    visited = {object_id}
    records: list[dict[str, Any]] = []
    ordered_edge_ids: list[str] = []
    seen_edge_ids: set[str] = set()

    while queue:
        current_id, depth, path_node_ids, path_edge_ids = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for item in _filtered_adjacency_items(index, current_id, side, direction, relation_filter):
            edge_id = item["edge"]["link_id"]
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                ordered_edge_ids.append(edge_id)
            next_id = item["object_id"]
            distance = depth + 1
            next_path_node_ids = [*path_node_ids, next_id]
            next_path_edge_ids = [*path_edge_ids, edge_id]
            if next_id != object_id and _matches_layer(index, next_id, layer_filter):
                records.append(
                    {
                        "item": _context_item(index, item, distance=distance),
                        "path_node_ids": next_path_node_ids,
                        "path_edge_ids": next_path_edge_ids,
                    }
                )
            if next_id in visited:
                continue
            visited.add(next_id)
            queue.append((next_id, distance, next_path_node_ids, next_path_edge_ids))

    return records, ordered_edge_ids


def _bounded_subgraph_ids(
    index: GraphIndex,
    root_object_id: str,
    records: list[dict[str, Any]],
    ordered_edge_ids: list[str],
    layer_filter: set[str] | None,
) -> tuple[set[str], set[str]]:
    node_ids = {root_object_id}
    edge_ids: set[str] = set()
    if layer_filter is None:
        for record in records:
            node_ids.update(record["path_node_ids"])
        edge_ids = {
            edge_id
            for edge_id in ordered_edge_ids
            if _edge_endpoints_are_included(index["edges_by_id"][edge_id], node_ids)
        }
        return node_ids, edge_ids

    for record in records:
        node_ids.update(record["path_node_ids"])
        edge_ids.update(record["path_edge_ids"])
    return node_ids, edge_ids


def _filtered_adjacency_items(
    index: GraphIndex,
    object_id: str,
    side: str,
    direction: str,
    relation_filter: set[str] | None,
) -> list[AdjacencyItem]:
    items = index["adjacency"][direction][side].get(object_id, [])
    selected: list[AdjacencyItem] = []
    for item in items:
        edge = item["edge"]
        if relation_filter is not None and edge["relation"] not in relation_filter:
            continue
        selected.append(item)
    return selected


def _context_item(index: GraphIndex, item: AdjacencyItem, *, distance: int) -> dict[str, Any]:
    object_id = item["object_id"]
    node = index["nodes_by_id"][object_id]
    edge = item["edge"]
    return {
        "object_id": object_id,
        "layer": node["layer"],
        "via_link_id": edge["link_id"],
        "relation": edge["relation"],
        "distance": distance,
    }


def _matches_layer(index: GraphIndex, object_id: str, layer_filter: set[str] | None) -> bool:
    if layer_filter is None:
        return True
    return index["nodes_by_id"][object_id]["layer"] in layer_filter


def _edge_endpoints_are_included(edge: dict[str, Any], node_ids: set[str]) -> bool:
    return edge["source_object_id"] in node_ids and edge["target_object_id"] in node_ids


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
