from __future__ import annotations

import unittest

from decide_me.constants import (
    DECISION_STACK_LAYER_ORDER,
    INFLUENCE_FORWARD_RELATIONS,
    INFLUENCE_REVERSED_RELATIONS,
    LINK_RELATIONS,
)
from decide_me.graph_traversal import (
    ancestors,
    bounded_subgraph,
    build_graph_index,
    descendants,
    direct_downstream,
    direct_upstream,
    objects_by_layer,
)


class GraphTraversalTests(unittest.TestCase):
    def test_influence_relation_sets_cover_link_relations_without_overlap(self) -> None:
        self.assertEqual(LINK_RELATIONS, INFLUENCE_FORWARD_RELATIONS | INFLUENCE_REVERSED_RELATIONS)
        self.assertEqual(set(), INFLUENCE_FORWARD_RELATIONS & INFLUENCE_REVERSED_RELATIONS)

    def test_raw_direction_follows_link_source_to_target(self) -> None:
        index = build_graph_index(
            _project_state(
                nodes=[_node("O-source", "purpose"), _node("O-target", "strategy")],
                edges=[_edge("L-raw", "O-source", "depends_on", "O-target")],
            )
        )

        self.assertEqual(["O-target"], direct_downstream(index, "O-source"))
        self.assertEqual(["O-source"], direct_upstream(index, "O-target"))
        self.assertEqual([], direct_downstream(index, "O-target"))

    def test_influence_direction_reverses_dependency_like_relations(self) -> None:
        for relation in sorted(INFLUENCE_REVERSED_RELATIONS):
            with self.subTest(relation=relation):
                index = build_graph_index(
                    _project_state(
                        nodes=[_node("O-source", "execution"), _node("O-target", "strategy")],
                        edges=[_edge(f"L-{relation}", "O-source", relation, "O-target")],
                    )
                )

                self.assertEqual(["O-source"], direct_downstream(index, "O-target", direction="influence"))
                self.assertEqual(["O-target"], direct_upstream(index, "O-source", direction="influence"))
                self.assertEqual([], direct_downstream(index, "O-source", direction="influence"))

    def test_influence_direction_keeps_forward_relations_forward(self) -> None:
        for relation in sorted(INFLUENCE_FORWARD_RELATIONS):
            with self.subTest(relation=relation):
                index = build_graph_index(
                    _project_state(
                        nodes=[_node("O-source", "constraint"), _node("O-target", "strategy")],
                        edges=[_edge(f"L-{relation}", "O-source", relation, "O-target")],
                    )
                )

                self.assertEqual(["O-target"], direct_downstream(index, "O-source", direction="influence"))
                self.assertEqual(["O-source"], direct_upstream(index, "O-target", direction="influence"))
                self.assertEqual([], direct_downstream(index, "O-target", direction="influence"))

    def test_breadth_first_ancestors_descendants_and_max_depth(self) -> None:
        index = build_graph_index(_chain_project_state())

        self.assertEqual(
            ["D-decision", "A-action", "V-verification"],
            descendants(index, "O-root", direction="influence"),
        )
        self.assertEqual(
            ["A-action", "V-verification"],
            descendants(index, "D-decision", direction="influence"),
        )
        self.assertEqual(
            ["D-decision", "O-root"],
            ancestors(index, "A-action", direction="influence"),
        )
        self.assertEqual(["D-decision"], descendants(index, "O-root", direction="influence", max_depth=1))
        self.assertEqual([], descendants(index, "O-root", direction="influence", max_depth=0))

    def test_relation_and_layer_filters_are_traversal_boundaries(self) -> None:
        index = build_graph_index(_chain_project_state())

        self.assertEqual(
            ["D-decision"],
            descendants(index, "O-root", direction="influence", relations={"depends_on"}),
        )
        self.assertEqual(
            ["D-decision"],
            descendants(index, "O-root", direction="influence", layers={"strategy"}),
        )
        self.assertEqual(
            [],
            descendants(index, "O-root", direction="influence", layers={"execution"}),
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

        self.assertEqual(["D-decision", "A-action"], descendants(index, "O-root", direction="influence"))

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

    def test_objects_by_layer_returns_stable_layer_buckets(self) -> None:
        index = build_graph_index(_chain_project_state())

        grouped = objects_by_layer(index)

        self.assertEqual(list(DECISION_STACK_LAYER_ORDER), list(grouped))
        self.assertEqual(["O-root"], grouped["purpose"])
        self.assertEqual(["D-decision"], grouped["strategy"])
        self.assertEqual(["A-action"], grouped["execution"])
        self.assertEqual(["V-verification"], grouped["verification"])
        self.assertEqual({"strategy": ["D-decision"]}, objects_by_layer(index, layers={"strategy"}))

    def test_bounded_subgraph_returns_seed_with_bounded_upstream_and_downstream_context(self) -> None:
        index = build_graph_index(_chain_project_state())

        subgraph = bounded_subgraph(index, "A-action", direction="influence", max_depth=1)

        self.assertEqual(
            ["A-action", "D-decision", "V-verification"],
            [node["object_id"] for node in subgraph["nodes"]],
        )
        self.assertEqual(
            ["L-2-action-addresses-decision", "L-3-verification-requires-action"],
            [edge["link_id"] for edge in subgraph["edges"]],
        )

        filtered = bounded_subgraph(index, "O-root", direction="influence", layers={"execution"}, max_depth=2)
        self.assertEqual(["O-root"], [node["object_id"] for node in filtered["nodes"]])
        self.assertEqual([], filtered["edges"])


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


def _node(object_id: str, layer: str) -> dict:
    return {
        "object_id": object_id,
        "object_type": "decision",
        "layer": layer,
        "status": "active",
        "title": object_id,
        "is_frontier": False,
        "is_invalidated": False,
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
