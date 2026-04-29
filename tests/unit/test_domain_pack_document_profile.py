from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from decide_me.documents.compiler import compile_document
from tests.helpers.domain_document_runtime import build_domain_document_runtime
from tests.helpers.document_runtime import NOW


class DomainPackDocumentProfileTests(unittest.TestCase):
    def test_explicit_research_pack_applies_research_plan_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "research")

            model = compile_document(
                ai_dir,
                document_type="research-plan",
                session_ids=[session_id],
                domain_pack_id="research",
                now=NOW,
            )

        self.assertEqual("research", model["metadata"]["domain_pack_id"])
        self.assertEqual("research_protocol", model["metadata"]["document_profile_id"])
        self.assertTrue(model["metadata"]["domain_pack_digest"].startswith("DP-"))
        self.assertEqual(
            [
                "objective",
                "research-question-decision-targets",
                "evidence-base",
                "analysis-verification-plan",
                "risks-and-mitigations",
                "source-traceability",
            ],
            [section["id"] for section in model["sections"][:6]],
        )
        decision_rows = _section(model, "research-question-decision-targets")["blocks"][0]["rows"]
        self.assertEqual("primary_endpoint", decision_rows[0][4])

    def test_omitted_pack_uses_single_session_pack_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "procurement")

            model = compile_document(
                ai_dir,
                document_type="comparison-table",
                session_ids=[session_id],
                now=NOW,
            )

        self.assertEqual("procurement", model["metadata"]["domain_pack_id"])
        self.assertEqual("procurement_comparison", model["metadata"]["document_profile_id"])
        self.assertEqual(["comparison"], [section["id"] for section in model["sections"]])

    def test_mixed_scope_uses_generic_profile_when_available(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, research_session_id = build_domain_document_runtime(Path(tmp), "research")
            _same_ai_dir, procurement_session_id = build_domain_document_runtime(Path(tmp), "procurement", ai_dir=ai_dir)

            model = compile_document(
                ai_dir,
                document_type="decision-brief",
                session_ids=[research_session_id, procurement_session_id],
                now=NOW,
            )

        self.assertEqual("generic", model["metadata"]["domain_pack_id"])
        self.assertEqual("generic_decision_brief", model["metadata"]["document_profile_id"])

    def test_pack_specific_mixed_scope_requires_explicit_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, research_session_id = build_domain_document_runtime(Path(tmp), "research")
            _same_ai_dir, procurement_session_id = build_domain_document_runtime(Path(tmp), "procurement", ai_dir=ai_dir)

            with self.assertRaisesRegex(ValueError, "domain pack is ambiguous for research-plan"):
                compile_document(
                    ai_dir,
                    document_type="research-plan",
                    session_ids=[research_session_id, procurement_session_id],
                    now=NOW,
                )

    def test_explicit_pack_must_define_requested_document_type(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "research")

            with self.assertRaisesRegex(ValueError, "domain pack research does not define document type comparison-table"):
                compile_document(
                    ai_dir,
                    document_type="comparison-table",
                    session_ids=[session_id],
                    domain_pack_id="research",
                    now=NOW,
                )


def _section(model: dict[str, Any], section_id: str) -> dict[str, Any]:
    return next(section for section in model["sections"] if section["id"] == section_id)


if __name__ == "__main__":
    unittest.main()
