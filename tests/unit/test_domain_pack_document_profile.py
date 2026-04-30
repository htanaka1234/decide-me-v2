from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from decide_me.documents.compiler import compile_document
from decide_me.store import rebuild_and_persist, runtime_paths
from tests.helpers.domain_document_runtime import build_domain_document_runtime
from tests.helpers.document_runtime import NOW, build_document_runtime


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

    def test_omitted_pack_uses_generic_profile_when_single_session_pack_lacks_document_type(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_domain_document_runtime(Path(tmp), "research")

            model = compile_document(
                ai_dir,
                document_type="decision-brief",
                session_ids=[session_id],
                now=NOW,
            )

        self.assertEqual("generic", model["metadata"]["domain_pack_id"])
        self.assertEqual("generic_decision_brief", model["metadata"]["document_profile_id"])

    def test_single_session_pack_without_document_type_rejects_pack_specific_documents(self) -> None:
        cases = (
            ("procurement", "research-plan"),
            ("research", "comparison-table"),
        )
        for pack_id, document_type in cases:
            with self.subTest(pack_id=pack_id, document_type=document_type), TemporaryDirectory() as tmp:
                ai_dir, session_id = build_domain_document_runtime(Path(tmp), pack_id)

                with self.assertRaisesRegex(
                    ValueError,
                    f"domain pack {pack_id} does not define document type {document_type}",
                ):
                    compile_document(
                        ai_dir,
                        document_type=document_type,
                        session_ids=[session_id],
                        now=NOW,
                    )

    def test_explicit_generic_session_rejects_pack_specific_documents_without_generic_profile(self) -> None:
        cases = ("research-plan", "comparison-table")
        for document_type in cases:
            with self.subTest(document_type=document_type), TemporaryDirectory() as tmp:
                ai_dir, session_id = build_document_runtime(Path(tmp))

                with self.assertRaisesRegex(
                    ValueError,
                    f"domain pack generic does not define document type {document_type}",
                ):
                    compile_document(
                        ai_dir,
                        document_type=document_type,
                        session_ids=[session_id],
                        now=NOW,
                    )

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

    def test_generic_pack_applies_review_memo_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))

            model = compile_document(
                ai_dir,
                document_type="review-memo",
                session_ids=[session_id],
                now=NOW,
            )

        self.assertEqual("generic", model["metadata"]["domain_pack_id"])
        self.assertEqual("generic_review_memo", model["metadata"]["document_profile_id"])

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

    def test_session_pack_metadata_mismatch_fails_profile_selection(self) -> None:
        cases = (
            ("domain_pack_version", "9.9.9", "domain_pack_version mismatch"),
            ("domain_pack_digest", "DP-000000000000", "domain_pack_digest mismatch"),
        )
        for key, value, message in cases:
            with self.subTest(key=key), TemporaryDirectory() as tmp:
                ai_dir, session_id = build_domain_document_runtime(Path(tmp), "research")
                _mutate_session_created_classification(
                    ai_dir,
                    session_id,
                    lambda classification, key=key, value=value: classification.__setitem__(key, value),
                )

                with self.assertRaisesRegex(ValueError, message):
                    compile_document(
                        ai_dir,
                        document_type="research-plan",
                        session_ids=[session_id],
                        now=NOW,
                    )


def _section(model: dict[str, Any], section_id: str) -> dict[str, Any]:
    return next(section for section in model["sections"] if section["id"] == section_id)


def _mutate_session_created_classification(
    ai_dir: Path,
    session_id: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    paths = runtime_paths(ai_dir)
    session_events_dir = paths.session_events_dir / session_id
    found = False
    for path in sorted(session_events_dir.glob("*.jsonl")):
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        changed = False
        for event in events:
            if event.get("event_type") != "session_created":
                continue
            classification = event["payload"]["session"]["classification"]
            mutate(classification)
            found = True
            changed = True
        if changed:
            path.write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
    if not found:
        raise AssertionError(f"session_created event not found for {session_id}")
    rebuild_and_persist(ai_dir)


if __name__ == "__main__":
    unittest.main()
