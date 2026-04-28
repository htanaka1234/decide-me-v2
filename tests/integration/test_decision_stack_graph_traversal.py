from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.graph_traversal import ancestor_ids, build_graph_index, descendant_ids, descendants
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime
from tests.helpers.typed_metadata import metadata_for_object_type


class DecisionStackGraphTraversalIntegrationTests(unittest.TestCase):
    def test_traversal_uses_project_state_graph_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 6-2.",
                current_milestone="Phase 6-2",
            )
            session = create_session(str(ai_dir), context="Decision stack graph traversal")
            session_id = session["session"]["id"]

            transact(ai_dir, lambda _bundle: _events(session_id))
            rebuilt = rebuild_and_persist(ai_dir)
            project_state = rebuilt["project_state"]

            self.assertEqual([], validate_runtime(ai_dir))
            self.assertIn("D-auth", {obj["id"] for obj in project_state["objects"]})
            self.assertIn("L-action-addresses-decision", {link["id"] for link in project_state["links"]})

            graph_only_state = json.loads(json.dumps(project_state))
            graph_only_state["objects"] = []
            graph_only_state["links"] = []
            index = build_graph_index(graph_only_state)

            self.assertEqual(
                ["D-auth", "A-implement-auth", "V-auth-flow"],
                descendant_ids(index, "O-project-objective"),
            )
            self.assertEqual(
                ["D-auth", "O-privacy", "O-project-objective"],
                ancestor_ids(index, "A-implement-auth"),
            )
            self.assertEqual(
                ["D-auth"],
                descendant_ids(
                    index,
                    "O-project-objective",
                    layers={"strategy"},
                ),
            )
            self.assertEqual(
                ["A-implement-auth"],
                descendant_ids(
                    index,
                    "O-project-objective",
                    layers={"execution"},
                ),
            )
            self.assertEqual(
                ["D-auth"],
                descendant_ids(
                    index,
                    "O-project-objective",
                    relations={"depends_on"},
                ),
            )
            items = descendants(index, "O-project-objective")
            self.assertEqual(
                ("D-auth", "L-decision-depends-objective", "depends_on", 1),
                (
                    items[0]["object_id"],
                    items[0]["via_link_id"],
                    items[0]["relation"],
                    items[0]["distance"],
                ),
            )


def _events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-constraint",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("O-privacy", "constraint", "E-constraint")},
        },
        {
            "event_id": "E-decision",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("D-auth", "decision", "E-decision")},
        },
        {
            "event_id": "E-action",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("A-implement-auth", "action", "E-action")},
        },
        {
            "event_id": "E-verification",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("V-auth-flow", "verification", "E-verification")},
        },
        {
            "event_id": "E-link-decision-objective",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-decision-depends-objective",
                    "D-auth",
                    "depends_on",
                    "O-project-objective",
                    "E-link-decision-objective",
                )
            },
        },
        {
            "event_id": "E-link-constraint-decision",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-constraint-constrains-decision",
                    "O-privacy",
                    "constrains",
                    "D-auth",
                    "E-link-constraint-decision",
                )
            },
        },
        {
            "event_id": "E-link-action-decision",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-action-addresses-decision",
                    "A-implement-auth",
                    "addresses",
                    "D-auth",
                    "E-link-action-decision",
                )
            },
        },
        {
            "event_id": "E-link-verification-action",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-verification-requires-action",
                    "V-auth-flow",
                    "requires",
                    "A-implement-auth",
                    "E-link-verification-action",
                )
            },
        },
    ]


def _object(object_id: str, object_type: str, event_id: str) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Traversal integration object.",
        "status": "unresolved" if object_type == "decision" else "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata_for_object_type(object_type),
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Traversal integration link.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
