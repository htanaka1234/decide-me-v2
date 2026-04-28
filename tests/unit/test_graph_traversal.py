from __future__ import annotations

import unittest

from decide_me.constants import (
    INFLUENCE_FORWARD_RELATIONS,
    INFLUENCE_REVERSED_RELATIONS,
    LINK_RELATIONS,
)
from decide_me.graph_traversal import (
    ancestor_ids,
    bounded_subgraph,
    build_graph_index,
    descendants,
    descendants_with_paths,
    descendant_ids,
    direct_downstream,
    direct_downstream_ids,
    direct_upstream,
    direct_upstream_ids,
    objects_by_layer,
)


class GraphTraversalTests(unittest.TestCase):
    def test_influence_relation_sets_cover_link_relations_without_overlap(self) -> None:
        self.assertEqual(LINK_RELATIONS, INFLUENCE_FORWARD_RELATIONS | INFLUENCE_REVERSED_RELATIONS)
        self.assertEqual(set(), INFLUENCE_FORWARD_RELATIONS & INFLUENCE_REVERSED_RELATIONS)

    def test_default_direction_is_influence(self) -> None:
        index = build_graph_index(_chain_project_state())

        self.assertEqual(["D-decision", "A-action", "V-verification"], descendant_ids(index, "O-root"))
        self.assertEqual(["D-decision", "O-root"], ancestor_ids(index, "A-action"))

    def test_raw_direction_follows_link_source_to_target_when_explicit(self) -> None:
        index = build_graph_index(
            _project_state(
                nodes=[_node("O-source", "purpose"), _node("O-target", "strategy")],
                edges=[_edge("L-raw", "O-source", "depends_on", "O-target")],
            )
        )

        self.assertEqual(["O-target"], direct_downstream_ids(index, "O-source", direction="raw"))
        self.assertEqual(["O-source"], direct_upstream_ids(index, "O-target", direction="raw"))
        self.assertEqual(["O-source"], direct_downstream_ids(index, "O-target"))
        self.assertEqual([], direct_downstream_ids(index, "O-source"))

    def test_influence_direction_reverses_dependency_like_relations(self) -> None:
        for relation in sorted(INFLUENCE_REVERSED_RELATIONS):
            with self.subTest(relation=relation):
                index = build_graph_index(
                    _project_state(
                        nodes=[_node("O-source", "execution"), _node("O-target", "strategy")],
                        edges=[_edge(f"L-{relation}", "O-source", relation, "O-target")],
                    )
                )

                self.assertEqual(["O-source"], direct_downstream_ids(index, "O-target"))
                self.assertEqual(["O-target"], direct_upstream_ids(index, "O-source"))
                self.assertEqual([], direct_downstream_ids(index, "O-source"))

    def test_influence_direction_keeps_forward_relations_forward(self) -> None:
        for relation in sorted(INFLUENCE_FORWARD_RELATIONS):
            with self.subTest(relation=relation):
                index = build_graph_index(
                    _project_state(
                        nodes=[_node("O-source", "constraint"), _node("O-target", "strategy")],
                        edges=[_edge(f"L-{relation}", "O-source", relation, "O-target")],
                    )
                )

                self.assertEqual(["O-target"], direct_downstream_ids(index, "O-source"))
                self.assertEqual(["O-source"], direct_upstream_ids(index, "O-target"))
                self.assertEqual([], direct_downstream_ids(index, "O-target"))

    def test_direct_downstream_returns_edge_context(self) -> None:
        index = build_graph_index(_chain_project_state())

        item = direct_downstream(index, "D-decision")[0]

        self.assertEqual(
            {
                "object_id": "A-action",
                "layer": "execution",
                "via_link_id": "L-2-action-addresses-decision",
                "relation": "addresses",
                "distance": 1,
            },
            item,
        )

    def test_direct_traversal_preserves_multiple_edge_contexts_to_same_object(self) -> None:
        index = build_graph_index(
            _project_state(
                nodes=[_node("D-decision", "strategy"), _node("A-action", "execution")],
                edges=[
                    _edge("L-1-action-addresses-decision", "A-action", "addresses", "D-decision"),
                    _edge("L-2-action-requires-decision", "A-action", "requires", "D-decision"),
                ],
            )
        )

        items = direct_downstream(index, "D-decision")

        self.assertEqual(["A-action", "A-action"], [item["object_id"] for item in items])
        self.assertEqual(
            ["L-1-action-addresses-decision", "L-2-action-requires-decision"],
            [item["via_link_id"] for item in items],
        )

    def test_breadth_first_ancestors_descendants_and_max_depth(self) -> None:
        index = build_graph_index(_chain_project_state())

        self.assertEqual(
            ["D-decision", "A-action", "V-verification"],
            descendant_ids(index, "O-root"),
        )
        self.assertEqual(
            ["A-action", "V-verification"],
            descendant_ids(index, "D-decision"),
        )
        self.assertEqual(
            ["D-decision", "O-root"],
            ancestor_ids(index, "A-action"),
        )
        self.assertEqual(["D-decision"], descendant_ids(index, "O-root", max_depth=1))
        self.assertEqual([], descendant_ids(index, "O-root", max_depth=0))

        self.assertEqual(
            [
                ("D-decision", "L-1-decision-depends-root", 1),
                ("A-action", "L-2-action-addresses-decision", 2),
                ("V-verification", "L-3-verification-requires-action", 3),
            ],
            [(item["object_id"], item["via_link_id"], item["distance"]) for item in descendants(index, "O-root")],
        )

    def test_descendants_with_paths_returns_path_evidence_without_changing_descendants_shape(self) -> None:
        index = build_graph_index(_chain_project_state())

        items = descendants_with_paths(index, "O-root")

        self.assertEqual(
            {
                "object_id": "A-action",
                "layer": "execution",
                "via_link_id": "L-2-action-addresses-decision",
                "relation": "addresses",
                "distance": 2,
                "path": {
                    "node_ids": ["O-root", "D-decision", "A-action"],
                    "link_ids": ["L-1-decision-depends-root", "L-2-action-addresses-decision"],
                },
            },
            items[1],
        )
        self.assertNotIn("path", descendants(index, "O-root")[0])

    def test_descendants_with_paths_respects_max_depth_and_preserves_duplicate_target_paths(self) -> None:
        index = build_graph_index(
            _project_state(
                nodes=[_node("D-decision", "strategy"), _node("A-action", "execution")],
                edges=[
                    _edge("L-1-action-addresses-decision", "A-action", "addresses", "D-decision"),
                    _edge("L-2-action-requires-decision", "A-action", "requires", "D-decision"),
                ],
            )
        )

        self.assertEqual([], descendants_with_paths(index, "D-decision", max_depth=0))
        items = descendants_with_paths(index, "D-decision", max_depth=1)

        self.assertEqual(["A-action", "A-action"], [item["object_id"] for item in items])
        self.assertEqual(
            [
                ["L-1-action-addresses-decision"],
                ["L-2-action-requires-decision"],
            ],
            [item["path"]["link_ids"] for item in items],
        )

    def test_relation_filter_is_boundary_and_layer_filter_is_return_only(self) -> None:
        index = build_graph_index(_chain_project_state())

        self.assertEqual(
            ["D-decision"],
            descendant_ids(index, "O-root", relations={"depends_on"}),
        )
        self.assertEqual(
            ["D-decision"],
            descendant_ids(index, "O-root", layers={"strategy"}),
        )
        self.assertEqual(
            ["A-action"],
            descendant_ids(index, "O-root", layers={"execution"}),
        )
        self.assertEqual(
            ["V-verification"],
            descendant_ids(index, "O-root", layers={"verification"}),
        )

    def test_cycle_does_not_loop_or_return_seed_from_transitive_walk(self) -> None:
        index = build_graph_index(
            _project_state(
                nodes=[
                    _node("O-root", "purpose"),
                    _node("D-decision", "strategy"),
                    _node("A-action", "execution"),
                ],
                edges=[
                    _edge("L-1-decision-depends-root", "D-decision", "depends_on", "O-root"),
                    _edge("L-2-action-addresses-decision", "A-action", "addresses", "D-decision"),
                    _edge("L-3-root-depends-action", "O-root", "depends_on", "A-action"),
                ],
            )
        )

        self.assertEqual(["D-decision", "A-action"], descendant_ids(index, "O-root"))
        self.assertEqual(
            ["D-decision", "A-action"],
            [item["object_id"] for item in descendants_with_paths(index, "O-root")],
        )

    def test_unknown_inputs_fail_clearly(self) -> None:
        index = build_graph_index(_chain_project_state())

        with self.assertRaisesRegex(ValueError, "unknown object_id"):
            descendants(index, "O-missing")
        with self.assertRaisesRegex(ValueError, "direction"):
            descendants(index, "O-root", direction="sideways")
        with self.assertRaisesRegex(ValueError, "unknown relation filter"):
            descendants(index, "O-root", relations={"duplicates"})
        with self.assertRaisesRegex(ValueError, "unknown layer filter"):
            descendants(index, "O-root", layers={"unknown"})
        with self.assertRaisesRegex(ValueError, "max_depth"):
            descendants(index, "O-root", max_depth=-1)
        with self.assertRaisesRegex(ValueError, "unknown layer"):
            objects_by_layer(_chain_project_state(), "unknown")

    def test_build_index_rejects_malformed_graph(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate graph node"):
            build_graph_index(
                _project_state(
                    nodes=[_node("O-root", "purpose"), _node("O-root", "strategy")],
                    edges=[],
                )
            )

        with self.assertRaisesRegex(ValueError, "duplicate graph edge"):
            build_graph_index(
                _project_state(
                    nodes=[_node("O-root", "purpose"), _node("D-decision", "strategy")],
                    edges=[
                        _edge("L-1", "O-root", "supports", "D-decision"),
                        _edge("L-1", "D-decision", "supports", "O-root"),
                    ],
                )
            )

        with self.assertRaisesRegex(ValueError, "references missing object"):
            build_graph_index(
                _project_state(
                    nodes=[_node("O-root", "purpose")],
                    edges=[_edge("L-1", "O-root", "supports", "O-missing")],
                )
            )

    def test_objects_by_layer_returns_node_payloads_and_excludes_invalidated_by_default(self) -> None:
        project_state = _project_state(
            nodes=[
                _node("A-active", "execution"),
                _node("A-invalidated", "execution", is_invalidated=True),
                _node("D-decision", "strategy"),
            ],
            edges=[],
        )

        self.assertEqual(["A-active"], [node["object_id"] for node in objects_by_layer(project_state, "execution")])
        self.assertEqual(
            ["A-active", "A-invalidated"],
            [
                node["object_id"]
                for node in objects_by_layer(project_state, "execution", include_invalidated=True)
            ],
        )

    def test_bounded_subgraph_returns_seed_with_bounded_upstream_and_downstream_context(self) -> None:
        index = build_graph_index(_chain_project_state())

        subgraph = bounded_subgraph(index, "D-decision", upstream_depth=1, downstream_depth=2)

        self.assertEqual("D-decision", subgraph["root_object_id"])
        self.assertEqual(
            ["A-action", "D-decision", "O-root", "V-verification"],
            [node["object_id"] for node in subgraph["nodes"]],
        )
        self.assertEqual(
            [
                "L-1-decision-depends-root",
                "L-2-action-addresses-decision",
                "L-3-verification-requires-action",
            ],
            [edge["link_id"] for edge in subgraph["edges"]],
        )

        shallow = bounded_subgraph(index, "D-decision", upstream_depth=0, downstream_depth=1)
        self.assertEqual(["A-action", "D-decision"], [node["object_id"] for node in shallow["nodes"]])
        self.assertEqual(["L-2-action-addresses-decision"], [edge["link_id"] for edge in shallow["edges"]])

        with self.assertRaisesRegex(ValueError, "max_depth"):
            bounded_subgraph(index, "D-decision", upstream_depth=-1)

    def test_bounded_subgraph_layer_filter_keeps_bridge_path_nodes_and_edges(self) -> None:
        index = build_graph_index(_chain_project_state())

        subgraph = bounded_subgraph(index, "O-root", layers={"execution"}, downstream_depth=2)

        self.assertEqual("O-root", subgraph["root_object_id"])
        self.assertEqual(
            ["A-action", "D-decision", "O-root"],
            [node["object_id"] for node in subgraph["nodes"]],
        )
        self.assertEqual(
            ["L-1-decision-depends-root", "L-2-action-addresses-decision"],
            [edge["link_id"] for edge in subgraph["edges"]],
        )
        self.assertEqual(["A-action"], descendant_ids(index, "O-root", layers={"execution"}))

    def test_bounded_subgraph_layer_filter_omits_unreached_layer_targets_and_bridges(self) -> None:
        index = build_graph_index(_chain_project_state())

        subgraph = bounded_subgraph(index, "O-root", layers={"verification"}, downstream_depth=2)

        self.assertEqual(["O-root"], [node["object_id"] for node in subgraph["nodes"]])
        self.assertEqual([], subgraph["edges"])


def _chain_project_state() -> dict:
    return _project_state(
        nodes=[
            _node("O-root", "purpose"),
            _node("D-decision", "strategy"),
            _node("A-action", "execution"),
            _node("V-verification", "verification"),
        ],
        edges=[
            _edge("L-1-decision-depends-root", "D-decision", "depends_on", "O-root"),
            _edge("L-2-action-addresses-decision", "A-action", "addresses", "D-decision"),
            _edge("L-3-verification-requires-action", "V-verification", "requires", "A-action"),
        ],
    )


def _project_state(*, nodes: list[dict], edges: list[dict]) -> dict:
    return {"graph": {"nodes": nodes, "edges": edges}}


def _node(object_id: str, layer: str, *, is_invalidated: bool = False) -> dict:
    return {
        "object_id": object_id,
        "object_type": "decision",
        "layer": layer,
        "status": "invalidated" if is_invalidated else "active",
        "title": object_id,
        "is_frontier": False,
        "is_invalidated": is_invalidated,
    }


def _edge(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "link_id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "source_layer": "strategy",
        "target_layer": "strategy",
    }


if __name__ == "__main__":
    unittest.main()
