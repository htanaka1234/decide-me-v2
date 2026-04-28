from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime
from tests.helpers.legacy_term_policy import LEGACY_PROJECT_STATE_TERMS


class ObjectLinkProjectionShapeTests(unittest.TestCase):
    def test_bootstrap_persists_v12_object_link_project_state(self) -> None:
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

            self.assertEqual(12, project_state["schema_version"])
            self.assertNotIn("decisions", project_state)
            for legacy_key in LEGACY_PROJECT_STATE_TERMS:
                self.assertNotIn(legacy_key, project_state)
            self.assertNotIn("session" + "_graph", project_state)
            self.assertIn("protocol", project_state)
            self.assertIn("sessions_index", project_state)
            self.assertIn("objects", project_state)
            self.assertIn("links", project_state)
            self.assertIn("graph", project_state)
            self.assertEqual(1, project_state["counts"]["object_total"])
            self.assertEqual(0, project_state["counts"]["link_total"])
            self.assertEqual(12, runtime_index["projection_schema_version"])
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
            self.assertEqual(12, persisted["schema_version"])
            self.assertNotIn("decisions", persisted)
            self.assertIn("protocol", persisted)
            self.assertIn("sessions_index", persisted)
            self.assertIn("objects", persisted)
            self.assertIn("links", persisted)
            self.assertIn("graph", persisted)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_explicit_session_graph_writes_are_no_longer_supported(self) -> None:
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

            project_state = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))

            self.assertNotIn("session" + "_graph", project_state)
            self.assertEqual(
                [{"object_id", "object_type", "layer", "status", "title", "is_frontier", "is_invalidated"}],
                [set(node) for node in project_state["graph"]["nodes"]],
            )
            self.assertEqual([], project_state["graph"]["edges"])
            self.assertIn(parent["session"]["id"], project_state["sessions_index"])
            self.assertIn(child["session"]["id"], project_state["sessions_index"])
            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
