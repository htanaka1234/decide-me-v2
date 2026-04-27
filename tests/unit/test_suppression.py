from __future__ import annotations

import unittest

from decide_me.projections import default_session_state
from decide_me.suppression import apply_semantic_suppression_to_session, has_suppressed_context_remainders
from decide_me.taxonomy import default_taxonomy_state, taxonomy_nodes


def _suppressed_context() -> dict[str, list[str]]:
    return {
        "session_ids": ["S-loser"],
        "related_object_ids": ["D-hidden", "P-hidden"],
        "action_slice_names": [],
        "workstream_names": [],
        "hidden_strings": ["Hidden Tag"],
    }


class SuppressionTests(unittest.TestCase):
    def test_remainders_detect_decision_binding_active_state_and_proposal(self) -> None:
        context = _suppressed_context()

        with self.subTest("decision binding"):
            session = default_session_state("S-loser", "2026-04-23T12:00:00Z", "Loser")
            session["session"]["related_object_ids"] = ["D-hidden"]
            self.assertTrue(has_suppressed_context_remainders(session, context))

        with self.subTest("active proposal"):
            session = default_session_state("S-loser", "2026-04-23T12:00:00Z", "Loser")
            session["working_state"]["active_proposal_id"] = "P-hidden"
            self.assertTrue(has_suppressed_context_remainders(session, context))

    def test_remainders_detect_hidden_taxonomy_tag_alias(self) -> None:
        taxonomy = default_taxonomy_state(now="2026-04-23T12:00:00Z")
        taxonomy_nodes(taxonomy).append(
            {
                "id": "tag:hidden",
                "axis": "tag",
                "label": "hidden",
                "aliases": ["Hidden Tag"],
                "parent_id": None,
                "replaced_by": [],
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": "2026-04-23T12:00:00Z",
            }
        )
        session = default_session_state("S-loser", "2026-04-23T12:00:00Z", "Loser")
        session["classification"]["assigned_tags"] = ["tag:hidden"]

        self.assertTrue(has_suppressed_context_remainders(session, _suppressed_context(), taxonomy))

    def test_apply_suppression_removes_bindings_question_state_proposal_and_tags(self) -> None:
        taxonomy = default_taxonomy_state(now="2026-04-23T12:00:00Z")
        taxonomy_nodes(taxonomy).append(
            {
                "id": "tag:hidden",
                "axis": "tag",
                "label": "Hidden Tag",
                "aliases": [],
                "parent_id": None,
                "replaced_by": [],
                "status": "active",
                "created_at": "2026-04-23T12:00:00Z",
                "updated_at": "2026-04-23T12:00:00Z",
            }
        )
        session = default_session_state("S-loser", "2026-04-23T12:00:00Z", "Loser")
        session["session"]["related_object_ids"] = ["D-hidden", "D-visible", "P-hidden"]
        session["summary"]["current_question_preview"] = "Hidden Tag"
        session["working_state"]["active_question_id"] = "Q-hidden"
        session["working_state"]["active_proposal_id"] = "P-hidden"
        session["classification"]["search_terms"] = ["Hidden Tag", "visible"]
        session["classification"]["assigned_tags"] = ["tag:hidden"]
        session["close_summary"]["accepted_decisions"] = [{"id": "D-hidden", "title": "Hidden Tag"}]

        resolution = {
            "winning_session_id": "S-winner",
            "rejected_session_ids": ["S-loser"],
            "scope": {
                "kind": "accepted_decision",
                "decision_id": "D-hidden",
                "session_ids": ["S-winner", "S-loser"],
            },
        }

        context = apply_semantic_suppression_to_session(session, resolution, taxonomy)

        self.assertEqual(["D-visible", "P-hidden"], session["session"]["related_object_ids"])
        self.assertIsNone(session["summary"]["current_question_preview"])
        self.assertIsNone(session["working_state"]["active_question_id"])
        self.assertIsNone(session["working_state"]["active_proposal_id"])
        self.assertEqual(["visible"], session["classification"]["search_terms"])
        self.assertEqual([], session["classification"]["assigned_tags"])
        self.assertFalse(has_suppressed_context_remainders(session, context, taxonomy))


if __name__ == "__main__":
    unittest.main()
