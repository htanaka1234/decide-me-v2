from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime


class GraphProjectionFromObjectLinksTests(unittest.TestCase):
    def test_rebuild_projects_decision_stack_graph_from_objects_and_links(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 6-1.",
                current_milestone="Phase 6-1",
            )
            session = create_session(str(ai_dir), context="Decision stack graph contract")
            session_id = session["session"]["id"]

            transact(
                ai_dir,
                lambda _bundle: [
                    {
                        "event_id": "E-evidence",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object(
                                "O-evidence",
                                "evidence",
                                "E-evidence",
                                metadata={"layer": "review"},
                            )
                        },
                    },
                    {
                        "event_id": "E-action",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-action", "action", "E-action")
                        },
                    },
                    {
                        "event_id": "E-assumption",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-assumption", "assumption", "E-assumption")
                        },
                    },
                    {
                        "event_id": "E-criterion",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-criterion", "criterion", "E-criterion")
                        },
                    },
                    {
                        "event_id": "E-option",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-option", "option", "E-option")
                        },
                    },
                    {
                        "event_id": "E-artifact",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-artifact", "artifact", "E-artifact")
                        },
                    },
                    {
                        "event_id": "E-decision",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("D-decision", "decision", "E-decision")
                        },
                    },
                    {
                        "event_id": "E-link",
                        "session_id": session_id,
                        "event_type": "object_linked",
                        "payload": {
                            "link": _link(
                                "L-action-derived-from-evidence",
                                "O-action",
                                "derived_from",
                                "O-evidence",
                                "E-link",
                            )
                        },
                    },
                ],
            )

            rebuilt = rebuild_and_persist(ai_dir)
            project_state = rebuilt["project_state"]
            nodes = {node["object_id"]: node for node in project_state["graph"]["nodes"]}
            edges = {edge["link_id"]: edge for edge in project_state["graph"]["edges"]}

            self.assertEqual("purpose", nodes["O-project-objective"]["layer"])
            self.assertEqual("review", nodes["O-evidence"]["layer"])
            self.assertEqual("execution", nodes["O-action"]["layer"])
            self.assertEqual("constraint", nodes["O-assumption"]["layer"])
            self.assertEqual("principle", nodes["O-criterion"]["layer"])
            self.assertEqual("strategy", nodes["O-option"]["layer"])
            self.assertEqual("design", nodes["O-artifact"]["layer"])
            self.assertEqual("strategy", nodes["D-decision"]["layer"])
            self.assertEqual(
                {
                    "link_id": "L-action-derived-from-evidence",
                    "source_object_id": "O-action",
                    "relation": "derived_from",
                    "target_object_id": "O-evidence",
                    "source_layer": "execution",
                    "target_layer": "review",
                },
                edges["L-action-derived-from-evidence"],
            )
            self.assertEqual([], validate_runtime(ai_dir))
            self.assertEqual(
                project_state,
                json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8")),
            )


def _object(
    object_id: str,
    object_type: str,
    event_id: str,
    *,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Projected into the decision stack graph.",
        "status": "unresolved" if object_type == "decision" else "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata or {},
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Projected from object/link runtime state.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
