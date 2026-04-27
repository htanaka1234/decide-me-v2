from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime


class ObjectEventProjectionIntegrationTests(unittest.TestCase):
    def test_runtime_persists_and_rebuilds_object_event_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 5-3.",
                current_milestone="Phase 5-3",
            )
            session = create_session(str(ai_dir), context="Object event test")
            session_id = session["session"]["id"]

            def builder(_bundle: dict) -> list[dict]:
                return [
                    {
                        "event_id": "E-object-decision",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {"object": _object("O-decision", "E-object-decision")},
                    },
                    {
                        "event_id": "E-object-evidence",
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {
                            "object": _object("O-evidence", "E-object-evidence", object_type="evidence")
                        },
                    },
                    {
                        "event_id": "E-link",
                        "session_id": session_id,
                        "event_type": "object_linked",
                        "payload": {"link": _link("L-evidence-supports-decision", "E-link")},
                    },
                    {
                        "session_id": session_id,
                        "event_type": "object_updated",
                        "payload": {
                            "object_id": "O-decision",
                            "patch": {"metadata": {"priority": "P0"}},
                        },
                    },
                    {
                        "session_id": session_id,
                        "event_type": "object_status_changed",
                        "payload": {"object_id": "O-decision", "status": "accepted"},
                    },
                    {
                        "session_id": session_id,
                        "event_type": "object_unlinked",
                        "payload": {"link_id": "L-evidence-supports-decision"},
                    },
                ]

            transact(ai_dir, builder)
            project_state = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))
            by_id = {item["id"]: item for item in project_state["objects"]}

            self.assertEqual("accepted", by_id["O-decision"]["status"])
            self.assertEqual("P0", by_id["O-decision"]["metadata"]["priority"])
            self.assertNotIn("L-evidence-supports-decision", {link["id"] for link in project_state["links"]})
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual(rebuilt["project_state"], json.loads((ai_dir / "project-state.json").read_text()))


def _object(object_id: str, event_id: str, *, object_type: str = "decision") -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Body",
        "status": "active" if object_type != "decision" else "unresolved",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": {},
    }


def _link(link_id: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": "O-evidence",
        "relation": "supports",
        "target_object_id": "O-decision",
        "rationale": "Evidence supports the decision.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
