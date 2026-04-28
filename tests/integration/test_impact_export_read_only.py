from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.impact_runtime import (
    build_impact_runtime,
    changed_paths,
    only_impact_export_paths,
    run_cli,
    runtime_state_snapshot,
    tree_hash_snapshot,
)


class ImpactExportReadOnlyTests(unittest.TestCase):
    def test_export_impact_report_writes_only_impact_markdown_export(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            output = ai_dir / "exports" / "impact" / "CON-001.md"
            runtime_before = runtime_state_snapshot(ai_dir)
            tree_before = tree_hash_snapshot(ai_dir)

            result = run_cli(
                "export-impact-report",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "CON-001",
                "--change-kind",
                "changed",
                "--max-depth",
                "4",
                "--output",
                str(output),
            )

            payload = json.loads(result.stdout)
            report = output.read_text(encoding="utf-8")
            changed = changed_paths(tree_before, tree_hash_snapshot(ai_dir))

            self.assertEqual(str(output), payload["path"])
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["exports/impact/CON-001.md"], changed)
            self.assertTrue(only_impact_export_paths(changed))
            self.assertIn("# Impact Report: CON-001", report)
            self.assertIn("This report is read-only.", report)
            self.assertIn("| DEC-001 | decision | strategy | accepted | high | decision_review_required |", report)
            self.assertIn("| VER-001 | verification | verification | active | medium | verification_review_required |", report)

    def test_export_impact_report_rejects_output_outside_impact_exports(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ai_dir = build_impact_runtime(root)
            output = root / "outside.md"
            runtime_before = runtime_state_snapshot(ai_dir)
            tree_before = tree_hash_snapshot(ai_dir)

            result = run_cli(
                "export-impact-report",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "CON-001",
                "--change-kind",
                "changed",
                "--output",
                str(output),
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("exports/impact", result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual(tree_before, tree_hash_snapshot(ai_dir))


if __name__ == "__main__":
    unittest.main()
