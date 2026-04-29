from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.documents.compiler import compile_document
from tests.helpers.document_runtime import NOW, build_document_runtime, build_two_session_document_runtime
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

    def test_session_scope_excludes_other_closed_session_objects(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, first_session_id, _second_session_id = build_two_session_document_runtime(Path(tmp))

            model = compile_document(
                ai_dir,
                document_type="decision-brief",
                session_ids=[first_session_id],
                now=NOW,
            )

            self.assertIn("OBJ-001", model["source"]["object_ids"])
            self.assertNotIn("OBJ-002", model["source"]["object_ids"])
            purpose = _section(model, "purpose-principles-constraints")
            rendered_ids = [row[0] for row in purpose["blocks"][0]["rows"]]
            self.assertIn("OBJ-001", rendered_ids)
            self.assertNotIn("OBJ-002", rendered_ids)

    def test_risk_register_respects_include_invalidated(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))

            default_model = compile_document(
                ai_dir,
                document_type="risk-register",
                session_ids=[session_id],
                now=NOW,
            )
            inclusive_model = compile_document(
                ai_dir,
                document_type="risk-register",
                session_ids=[session_id],
                include_invalidated=True,
                now=NOW,
            )

            self.assertIn("RSK-001", default_model["source"]["object_ids"])
            self.assertNotIn("RSK-002", default_model["source"]["object_ids"])
            self.assertIn("RSK-002", inclusive_model["source"]["object_ids"])

    def test_comparison_table_sources_include_rendered_related_objects_and_links(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))

            model = compile_document(
                ai_dir,
                document_type="comparison-table",
                session_ids=[session_id],
                now=NOW,
            )

            comparison = _section(model, "comparison")
            self.assertTrue(
                {
                    "OPT-001",
                    "PRO-001",
                    "DEC-001",
                    "CRI-001",
                    "EVI-001",
                    "EVI-002",
                    "RSK-001",
                    "CON-001",
                }.issubset(set(comparison["source_object_ids"]))
            )
            self.assertTrue(
                {
                    "L-PRO-001-recommends-OPT-001",
                    "L-PRO-001-addresses-DEC-001",
                    "L-DEC-001-accepts-PRO-001",
                    "L-CRI-001-supports-OPT-001",
                    "L-EVI-001-supports-DEC-001",
                    "L-EVI-002-supports-DEC-001",
                    "L-RSK-001-challenges-DEC-001",
                    "L-CON-001-constrains-OPT-001",
                }.issubset(set(comparison["source_link_ids"]))
            )
            self.assertTrue(set(comparison["source_object_ids"]).issubset(set(model["source"]["object_ids"])))
            self.assertTrue(set(comparison["source_link_ids"]).issubset(set(model["source"]["link_ids"])))

    def test_risk_register_sources_include_rendered_related_and_gate_objects(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))

            model = compile_document(
                ai_dir,
                document_type="risk-register",
                session_ids=[session_id],
                now=NOW,
            )

            risks = _section(model, "risks")
            self.assertTrue(
                {"RSK-001", "ACT-001", "DEC-001", "EVI-001", "ASM-001"}.issubset(
                    set(risks["source_object_ids"])
                )
            )
            self.assertTrue(
                {"L-ACT-001-mitigates-RSK-001", "L-RSK-001-challenges-DEC-001"}.issubset(
                    set(risks["source_link_ids"])
                )
            )


def _section(model: dict, section_id: str) -> dict:
    return next(section for section in model["sections"] if section["id"] == section_id)


if __name__ == "__main__":
    unittest.main()
