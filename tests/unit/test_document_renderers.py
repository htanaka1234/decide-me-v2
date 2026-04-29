from __future__ import annotations

import json
import unittest

from decide_me.documents.merge import merge_managed_content
from decide_me.documents.render_csv import render_csv_document
from decide_me.documents.render_json import render_json_document
from decide_me.documents.render_markdown import render_markdown_document


class DocumentRendererTests(unittest.TestCase):
    def test_markdown_renderer_escapes_table_cells_and_empty_blocks(self) -> None:
        rendered = render_markdown_document(_model())

        self.assertIn("# Risk Register", rendered)
        self.assertIn("| RSK-001 | A\\|B line break |", rendered)
        self.assertIn("> **warning:** Check this.", rendered)
        self.assertIn("- none recorded", rendered)

    def test_json_renderer_outputs_stable_model_json(self) -> None:
        rendered = render_json_document(_model())

        payload = json.loads(rendered)
        self.assertEqual("risk-register", payload["document_type"])
        self.assertIn('\n  "document_id": "DOC-20260429-risk-register"', rendered)

    def test_csv_renderer_uses_risk_table(self) -> None:
        rendered = render_csv_document(_model())

        self.assertEqual('Risk ID,Statement\nRSK-001,"A|B\nline break"\n', rendered)

    def test_managed_region_merge_preserves_human_notes(self) -> None:
        existing = (
            "<!-- decide-me:generated:start document_type=risk-register project_head=old -->\n"
            "old generated\n"
            "<!-- decide-me:generated:end -->\n"
            "\n"
            "## Human Notes\n"
            "Keep this.\n"
        )

        merged, warnings = merge_managed_content(
            existing,
            "new generated\n",
            document_type="risk-register",
            project_head="new",
        )

        self.assertIn("new generated", merged)
        self.assertNotIn("old generated", merged)
        self.assertIn("Keep this.", merged)
        self.assertEqual(1, len(warnings))

    def test_managed_region_rejects_unmarked_existing_file_without_force(self) -> None:
        with self.assertRaisesRegex(ValueError, "without decide-me markers"):
            merge_managed_content(
                "hand written",
                "generated",
                document_type="risk-register",
                project_head="H",
            )

    def test_managed_region_rejects_document_type_mismatch(self) -> None:
        existing = (
            "<!-- decide-me:generated:start document_type=decision-brief project_head=H -->\n"
            "old\n"
            "<!-- decide-me:generated:end -->\n"
        )

        with self.assertRaisesRegex(ValueError, "type mismatch"):
            merge_managed_content(
                existing,
                "generated",
                document_type="risk-register",
                project_head="H",
                force=True,
            )


def _model() -> dict:
    return {
        "schema_version": 1,
        "document_id": "DOC-20260429-risk-register",
        "document_type": "risk-register",
        "audience": "human",
        "generated_at": "2026-04-29T00:00:00Z",
        "project_head": "H-test",
        "source": {
            "session_ids": ["S-001"],
            "object_ids": ["RSK-001"],
            "link_ids": ["L-001"],
            "diagnostic_types": ["risk_register"],
        },
        "title": "Risk Register",
        "sections": [
            {
                "id": "risks",
                "title": "Risks",
                "order": 10,
                "blocks": [
                    {
                        "type": "table",
                        "columns": ["Risk ID", "Statement"],
                        "rows": [["RSK-001", "A|B\nline break"]],
                    },
                    {"type": "callout", "severity": "warning", "text": "Check this."},
                    {"type": "list", "items": []},
                ],
                "source_object_ids": ["RSK-001"],
                "source_link_ids": ["L-001"],
            }
        ],
        "warnings": [],
        "metadata": {},
    }


if __name__ == "__main__":
    unittest.main()
