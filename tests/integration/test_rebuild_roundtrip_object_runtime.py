from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.runtime_flow import (
    complete_ok_runtime,
    delete_derived_projection_files,
    object_runtime_snapshot,
    rebuild_cli,
    validate_cli,
)


class RebuildRoundtripObjectRuntimeTests(unittest.TestCase):
    def test_rebuild_recreates_objects_links_and_session_close_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            result = complete_ok_runtime(ai_dir, Path(tmp))
            session_id = result["session_id"]
            before = object_runtime_snapshot(ai_dir, session_id)

            delete_derived_projection_files(ai_dir)
            rebuild_cli(ai_dir)
            validation = validate_cli(ai_dir)
            after = object_runtime_snapshot(ai_dir, session_id)

            self.assertTrue(validation["ok"])
            self.assertEqual([], validation["issues"])
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

