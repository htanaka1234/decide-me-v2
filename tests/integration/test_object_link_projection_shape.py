from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.session_graph import link_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime
from decide_me.store import transact


class ObjectLinkProjectionShapeTests(unittest.TestCase):
    def test_bootstrap_persists_v10_object_link_project_state(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"

            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 5-2.",
                current_milestone="Phase 5-2",
            )
            project_state = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))
            runtime_index = json.loads((ai_dir / "runtime-index.json").read_text(encoding="utf-8"))

            self.assertEqual(10, project_state["schema_version"])
            self.assertNotIn("decisions", project_state)
            self.assertNotIn("default_bundles", project_state)
            self.assertNotIn("session_graph", project_state)
            self.assertIn("protocol", project_state)
            self.assertIn("sessions_index", project_state)
            self.assertIn("objects", project_state)
            self.assertIn("links", project_state)
            self.assertIn("graph", project_state)
            self.assertEqual(1, project_state["counts"]["object_total"])
            self.assertEqual(0, project_state["counts"]["link_total"])
            self.assertEqual(10, runtime_index["projection_schema_version"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_rebuild_regenerates_object_link_project_state(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 5-2.",
                current_milestone="Phase 5-2",
            )
            (ai_dir / "project-state.json").unlink()

            rebuilt = rebuild_and_persist(ai_dir)
            persisted = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))

            self.assertEqual(rebuilt["project_state"], persisted)
            self.assertEqual(10, persisted["schema_version"])
            self.assertNotIn("decisions", persisted)
            self.assertIn("protocol", persisted)
            self.assertIn("sessions_index", persisted)
            self.assertIn("objects", persisted)
            self.assertIn("links", persisted)
            self.assertIn("graph", persisted)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_session_linked_persists_graph_edge(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 5-2.",
                current_milestone="Phase 5-2",
            )
            parent = create_session(str(ai_dir), context="Parent")
            child = create_session(str(ai_dir), context="Child")

            link_session(
                str(ai_dir),
                parent_session_id=parent["session"]["id"],
                child_session_id=child["session"]["id"],
                relationship="refines",
                reason="Child refines parent.",
            )
            project_state = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))

            self.assertNotIn("session_graph", project_state)
            self.assertEqual(1, len(project_state["graph"]["edges"]))
            self.assertEqual("refines", project_state["graph"]["edges"][0]["relationship"])
            self.assertIn(parent["session"]["id"], project_state["sessions_index"])
            self.assertIn(child["session"]["id"], project_state["sessions_index"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_semantic_conflict_resolution_persists_graph_resolution(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 5-2.",
                current_milestone="Phase 5-2",
            )
            winner = create_session(str(ai_dir), context="Winner")
            loser = create_session(str(ai_dir), context="Loser")
            winner_id = winner["session"]["id"]
            loser_id = loser["session"]["id"]

            def builder(_bundle: dict) -> list[dict]:
                return [
                    {
                        "session_id": winner_id,
                        "event_type": "semantic_conflict_resolved",
                        "payload": {
                            "conflict_id": "C-test",
                            "winning_session_id": winner_id,
                            "rejected_session_ids": [loser_id],
                            "scope": {"kind": "session", "session_ids": [winner_id, loser_id]},
                            "reason": "Keep winner.",
                            "resolved_at": "2026-04-23T12:06:00Z",
                        },
                    }
                ]

            transact(ai_dir, builder)
            project_state = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))

            self.assertNotIn("session_graph", project_state)
            self.assertEqual(1, len(project_state["graph"]["resolved_conflicts"]))
            self.assertEqual("C-test", project_state["graph"]["resolved_conflicts"][0]["conflict_id"])
            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
