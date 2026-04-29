from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.document_runtime import NOW
from tests.helpers.domain_document_runtime import build_domain_document_runtime
from tests.helpers.impact_runtime import changed_paths, run_cli, runtime_state_snapshot, tree_hash_snapshot


class DomainPackDocumentExportTests(unittest.TestCase):
    def test_research_plan_export_applies_research_profile_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "research")
            output = ai_dir / "exports" / "documents" / "research-plan.json"
            runtime_before = runtime_state_snapshot(ai_dir)
            tree_before = tree_hash_snapshot(ai_dir)

            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "research-plan",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--domain-pack",
                "research",
                "--now",
                NOW,
                "--output",
                str(output),
            )

            payload = json.loads(result.stdout)
            model = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(output), payload["path"])
            self.assertEqual("research", payload["domain_pack_id"])
            self.assertTrue(payload["domain_pack_applied"])
            self.assertEqual("research", model["metadata"]["domain_pack_id"])
            self.assertEqual("research_protocol", model["metadata"]["document_profile_id"])
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["exports/documents/research-plan.json"], changed_paths(tree_before, tree_hash_snapshot(ai_dir)))

    def test_procurement_comparison_export_applies_procurement_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "procurement")
            output = ai_dir / "exports" / "documents" / "comparison-table.json"

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "comparison-table",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--domain-pack",
                "procurement",
                "--now",
                NOW,
                "--output",
                str(output),
            )

            model = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("procurement", model["metadata"]["domain_pack_id"])
            self.assertEqual("procurement_comparison", model["metadata"]["document_profile_id"])
            self.assertEqual(["comparison"], [section["id"] for section in model["sections"]])

    def test_ambiguous_pack_specific_export_fails_before_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, research_session_id = build_domain_document_runtime(Path(tmp), "research")
            _same_ai_dir, procurement_session_id = build_domain_document_runtime(Path(tmp), "procurement", ai_dir=ai_dir)
            output = ai_dir / "exports" / "documents" / "ambiguous-research-plan.json"

            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "research-plan",
                "--format",
                "json",
                "--session-id",
                research_session_id,
                "--session-id",
                procurement_session_id,
                "--now",
                NOW,
                "--output",
                str(output),
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("domain pack is ambiguous for research-plan", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
