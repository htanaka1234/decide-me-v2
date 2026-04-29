from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.documents.compiler import compile_document
from tests.helpers.document_runtime import NOW, build_document_runtime
from tests.helpers.impact_runtime import event_hash_snapshot, runtime_state_snapshot


class DocumentBuilderTests(unittest.TestCase):
    def test_all_document_builders_emit_schema_valid_models_without_runtime_writes(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "document-model.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
            events_before = event_hash_snapshot(ai_dir)
            runtime_before = runtime_state_snapshot(ai_dir)

            for document_type in (
                "decision-brief",
                "action-plan",
                "risk-register",
                "review-memo",
                "research-plan",
                "comparison-table",
            ):
                with self.subTest(document_type=document_type):
                    model = compile_document(
                        ai_dir,
                        document_type=document_type,
                        session_ids=[session_id],
                        now=NOW,
                    )
                    self.assertEqual([], list(validator.iter_errors(model)))
                    self.assertEqual(document_type, model["document_type"])
                    self.assertTrue(model["source"]["object_ids"])
                    self.assertTrue(model["sections"])

            self.assertEqual(events_before, event_hash_snapshot(ai_dir))
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))

    def test_review_memo_contains_phase7_diagnostics(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))

            model = compile_document(
                ai_dir,
                document_type="review-memo",
                session_ids=[session_id],
                now=NOW,
            )

            section_ids = [section["id"] for section in model["sections"]]
            self.assertIn("required-decisions", section_ids)
            self.assertIn("stale-inputs", section_ids)
            self.assertIn("verification-gaps", section_ids)
            self.assertIn("revisit-due", section_ids)
            self.assertIn("safety_gates", model["source"]["diagnostic_types"])
            self.assertIn("stale_evidence", model["source"]["diagnostic_types"])


if __name__ == "__main__":
    unittest.main()
