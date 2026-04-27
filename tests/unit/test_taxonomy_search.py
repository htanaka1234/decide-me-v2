from __future__ import annotations

import unittest

from decide_me.projections import default_session_state
from decide_me.search import search_sessions
from decide_me.taxonomy import default_taxonomy_state, expand_filter_ids, taxonomy_nodes


class TaxonomySearchTests(unittest.TestCase):
    def test_expand_filter_ids_follows_descendants_and_replacements(self) -> None:
        taxonomy = default_taxonomy_state(now="2026-04-23T12:00:00Z")
        taxonomy_nodes(taxonomy).extend(
            [
                {
                    "id": "tag:auth",
                    "axis": "tag",
                    "label": "auth",
                    "aliases": ["authentication"],
                    "parent_id": None,
                    "replaced_by": [],
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
                {
                    "id": "tag:magic-links",
                    "axis": "tag",
                    "label": "magic links",
                    "aliases": [],
                    "parent_id": "tag:auth",
                    "replaced_by": [],
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
                {
                    "id": "tag:email-link",
                    "axis": "tag",
                    "label": "email link",
                    "aliases": [],
                    "parent_id": "tag:auth",
                    "replaced_by": ["tag:magic-links"],
                    "status": "replaced",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
            ]
        )

        expanded = set(expand_filter_ids(taxonomy, ["tag:auth"]))
        self.assertIn("tag:magic-links", expanded)
        self.assertIn("tag:email-link", expanded)

    def test_search_matches_alias_and_compatibility_chain(self) -> None:
        taxonomy = default_taxonomy_state(now="2026-04-23T12:00:00Z")
        taxonomy_nodes(taxonomy).extend(
            [
                {
                    "id": "tag:auth",
                    "axis": "tag",
                    "label": "auth",
                    "aliases": ["authentication"],
                    "parent_id": None,
                    "replaced_by": [],
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
                {
                    "id": "tag:magic-links",
                    "axis": "tag",
                    "label": "magic links",
                    "aliases": [],
                    "parent_id": "tag:auth",
                    "replaced_by": [],
                    "status": "active",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
                {
                    "id": "tag:email-link",
                    "axis": "tag",
                    "label": "email link",
                    "aliases": [],
                    "parent_id": "tag:auth",
                    "replaced_by": ["tag:magic-links"],
                    "status": "replaced",
                    "created_at": "2026-04-23T12:00:00Z",
                    "updated_at": "2026-04-23T12:00:00Z",
                },
            ]
        )
        session = default_session_state("S-001", "2026-04-23T12:00:00Z", "Auth discovery")
        session["session"]["lifecycle"]["status"] = "closed"
        session["classification"]["domain"] = "technical"
        session["classification"]["abstraction_level"] = "architecture"
        session["classification"]["assigned_tags"] = ["tag:email-link"]
        session["close_summary"]["work_item"]["title"] = "Auth scope"
        session["close_summary"]["work_item"]["statement"] = "Choose the auth approach"

        results = search_sessions({"S-001": session}, taxonomy, tag_terms=["authentication"])
        self.assertEqual(1, len(results))
        self.assertEqual("S-001", results[0]["session_id"])


if __name__ == "__main__":
    unittest.main()
