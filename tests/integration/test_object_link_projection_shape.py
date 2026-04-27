from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime


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
            self.assertNotIn("protocol", project_state)
            self.assertNotIn("default_bundles", project_state)
            self.assertNotIn("session_graph", project_state)
            self.assertIn("objects", project_state)
            self.assertIn("links", project_state)
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
            self.assertIn("objects", persisted)
            self.assertIn("links", persisted)
            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
