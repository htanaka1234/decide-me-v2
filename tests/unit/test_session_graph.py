from __future__ import annotations

import unittest

from decide_me.projections import default_project_state, default_session_state
from decide_me.session_graph import build_session_graph, related_session_scope


class SessionGraphTests(unittest.TestCase):
    def test_related_session_scope_is_deterministic(self) -> None:
        bundle = _graph_bundle()

        scope = related_session_scope(bundle, ["S-child"])

        self.assertEqual(["S-child", "S-grandchild", "S-parent"], [item["session_id"] for item in scope])
        self.assertEqual([0, 1, 1], [item["distance"] for item in scope])
        parent = next(item for item in scope if item["session_id"] == "S-parent")
        self.assertEqual(["S-child", "S-parent"], parent["path"])
        self.assertEqual("child-to-parent", parent["relationship_chain"][0]["direction"])

    def test_inferred_candidates_are_stable_and_do_not_duplicate_explicit_edges(self) -> None:
        bundle = _graph_bundle()
        parent = bundle["sessions"]["S-parent"]
        child = bundle["sessions"]["S-child"]
        parent["session"]["decision_ids"] = ["D-shared"]
        child["session"]["decision_ids"] = ["D-shared"]

        graph = build_session_graph(bundle)

        candidate_pairs = {tuple(candidate["session_ids"]) for candidate in graph["inferred_candidates"]}
        self.assertNotIn(("S-child", "S-parent"), candidate_pairs)


def _graph_bundle() -> dict:
    project_state = default_project_state()
    project_state["graph"]["edges"] = [
        {
            "parent_session_id": "S-parent",
            "child_session_id": "S-child",
            "relationship": "refines",
            "reason": "Child refines parent.",
            "linked_at": "2026-04-23T12:00:00Z",
            "evidence_refs": [],
            "event_id": "E-link-1",
        },
        {
            "parent_session_id": "S-child",
            "child_session_id": "S-grandchild",
            "relationship": "derived_from",
            "reason": "Grandchild follows child.",
            "linked_at": "2026-04-23T12:01:00Z",
            "evidence_refs": [],
            "event_id": "E-link-2",
        },
    ]
    return {
        "project_state": project_state,
        "taxonomy_state": {},
        "sessions": {
            "S-child": default_session_state("S-child", "2026-04-23T12:00:00Z"),
            "S-grandchild": default_session_state("S-grandchild", "2026-04-23T12:00:00Z"),
            "S-parent": default_session_state("S-parent", "2026-04-23T12:00:00Z"),
        },
    }


if __name__ == "__main__":
    unittest.main()
