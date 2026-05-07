from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.events import EventValidationError, build_event
from decide_me.sources.decompose import decompose_document
from decide_me.sources.model import (
    SourceValidationError,
    document_dir,
    source_document_id,
    source_paths,
    source_unit_id,
    validate_normative_unit,
    validate_source_document,
)
from tests.helpers.schema_validation import load_schema


class Phase12SourceStoreUnitTests(unittest.TestCase):
    def test_source_ids_are_deterministic_and_hash_based(self) -> None:
        first = source_document_id(
            "academic_regulation",
            "医学部教務規則",
            "2026年度版",
            "sha256:" + "a" * 64,
        )
        second = source_document_id(
            "academic_regulation",
            "医学部教務規則",
            "2026年度版",
            "sha256:" + "a" * 64,
        )
        changed = source_document_id(
            "academic_regulation",
            "医学部教務規則",
            "2026年度版",
            "sha256:" + "b" * 64,
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertTrue(first.startswith("SRC-"))

        unit_id = source_unit_id(first, "article-12-paragraph-2", "sha256:" + "c" * 64)
        self.assertEqual(f"NU-{first}-article-12-paragraph-2-cccccccc", unit_id)

    def test_source_document_paths_reject_invalid_ids_before_path_join(self) -> None:
        with self.assertRaisesRegex(SourceValidationError, "source_document_id must match"):
            document_dir(".ai/decide-me", "../SRC-outside")

    def test_source_schemas_accept_valid_contracts(self) -> None:
        document = _source_document()
        unit = _normative_unit(document["id"])

        validate_source_document(document)
        validate_normative_unit(unit)
        Draft202012Validator(load_schema("source-document.schema.json")).validate(document)
        Draft202012Validator(load_schema("normative-unit.schema.json")).validate(unit)
        Draft202012Validator(load_schema("source-registry.schema.json")).validate(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "id": document["id"],
                        "title": document["title"],
                        "document_type": document["document_type"],
                        "content_hash": document["content_hash"],
                        "metadata_path": "documents/SRC-test/metadata.yaml",
                    }
                ],
            }
        )

    def test_egov_xml_decomposition_extracts_citation_units(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            source_id = "SRC-egov"
            doc_dir = source_paths(ai_dir)["documents"] / source_id
            doc_dir.mkdir(parents=True)
            original = doc_dir / "original.xml"
            original.write_text(
                """
                <Law>
                  <LawBody>
                    <Article Num="1">
                      <ArticleTitle>第一条</ArticleTitle>
                      <Paragraph Num="1">
                        <ParagraphNum>1</ParagraphNum>
                        <ParagraphSentence><Sentence>学生は指定期間内に履修登録を行う。</Sentence></ParagraphSentence>
                        <Item Num="1">
                          <ItemTitle>一</ItemTitle>
                          <ItemSentence><Sentence>例外申請は教務委員会が審査する。</Sentence></ItemSentence>
                        </Item>
                      </Paragraph>
                    </Article>
                  </LawBody>
                </Law>
                """,
                encoding="utf-8",
            )
            metadata = _source_document(source_id=source_id, original_path="documents/SRC-egov/original.xml")

            units, parser_version, flags = decompose_document(ai_dir, metadata, strategy="egov-law-xml")

            self.assertEqual("egov_law_xml_v1", parser_version)
            self.assertIn("xml_structure_used", flags)
            self.assertGreaterEqual(len(units), 3)
            self.assertTrue(any(unit["path"].get("article") == "第一条" for unit in units))
            self.assertTrue(any("履修登録" in unit["text_exact"] for unit in units))

    def test_japanese_regulation_text_decomposition_handles_common_headings(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            source_id = "SRC-text"
            doc_dir = source_paths(ai_dir)["documents"] / source_id
            doc_dir.mkdir(parents=True)
            original = doc_dir / "original.txt"
            original.write_text(
                "第1章 総則\n第1条 学生は指定期間内に履修登録を行う。\n2 締切後申請は別に定める。\n一 教務委員会が認めた場合\n別表第1 履修登録期間\n",
                encoding="utf-8",
            )
            metadata = _source_document(source_id=source_id, original_path="documents/SRC-text/original.txt", source_format="text")

            units, parser_version, flags = decompose_document(ai_dir, metadata, strategy="japanese-regulation-text")

            self.assertEqual("japanese_regulation_text_v1", parser_version)
            self.assertIn("text_heading_rules_used", flags)
            self.assertTrue(any(unit["unit_type"] == "article" for unit in units))
            self.assertTrue(any(unit["unit_type"] == "paragraph" for unit in units))
            self.assertTrue(any(unit["unit_type"] == "appendix_table" for unit in units))

    def test_pdf_decomposition_is_explicitly_unsupported(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            source_id = "SRC-pdf"
            doc_dir = source_paths(ai_dir)["documents"] / source_id
            doc_dir.mkdir(parents=True)
            (doc_dir / "original.pdf").write_bytes(b"%PDF")
            metadata = _source_document(source_id=source_id, original_path="documents/SRC-pdf/original.pdf", source_format="pdf")

            with self.assertRaisesRegex(ValueError, "PDF decomposition is unsupported"):
                decompose_document(ai_dir, metadata, strategy="auto")

    def test_source_audit_events_reject_source_text_payloads(self) -> None:
        event = build_event(
            tx_id="T-source",
            tx_index=1,
            tx_size=1,
            session_id="SYSTEM",
            event_type="source_document_imported",
            payload={
                "source_document_id": "SRC-test",
                "retrieved_at": "2026-05-01T00:00:00Z",
                "content_hash": "sha256:" + "a" * 64,
                "import_method": "local_file",
                "format": "xml",
                "snapshot_path": "documents/SRC-test/original.xml",
            },
            timestamp="2026-05-01T00:00:00Z",
        )
        self.assertEqual("source_document_imported", event["event_type"])

        with self.assertRaisesRegex(EventValidationError, "unsupported fields: text_exact"):
            build_event(
                tx_id="T-source",
                tx_index=1,
                tx_size=1,
                session_id="SYSTEM",
                event_type="source_document_imported",
                payload={
                    "source_document_id": "SRC-test",
                    "retrieved_at": "2026-05-01T00:00:00Z",
                    "content_hash": "sha256:" + "a" * 64,
                    "import_method": "local_file",
                    "text_exact": "学生は指定期間内に履修登録を行う。",
                },
                timestamp="2026-05-01T00:00:00Z",
            )

    def test_evidence_linked_audit_event_accepts_id_only_payload(self) -> None:
        event = build_event(
            tx_id="T-link",
            tx_index=1,
            tx_size=1,
            session_id="S-001",
            event_type="evidence_linked_to_object",
            payload={
                "evidence_object_id": "O-evidence-NU-SRC-test-unit-aaaaaaaa",
                "target_object_id": "D-001",
                "source_document_id": "SRC-test",
                "source_unit_id": "NU-SRC-test-unit-aaaaaaaa",
                "source_unit_hash": "sha256:" + "a" * 64,
                "relevance": "supports",
                "linked_at": "2026-05-01T00:00:00Z",
            },
            timestamp="2026-05-01T00:00:00Z",
        )

        self.assertEqual("evidence_linked_to_object", event["event_type"])


def _source_document(
    *,
    source_id: str = "SRC-test",
    original_path: str = "documents/SRC-test/original.xml",
    source_format: str = "xml",
) -> dict:
    return {
        "id": source_id,
        "title": "医学部教務規則",
        "authority": "Example University",
        "document_type": "academic_regulation",
        "source_uri": "fixtures/source.xml",
        "version_label": "2026年度版",
        "effective_from": "2026-04-01",
        "effective_to": None,
        "retrieved_at": "2026-05-01T00:00:00Z",
        "content_hash": "sha256:" + "a" * 64,
        "format": source_format,
        "canonical": True,
        "original_path": original_path,
        "text_path": f"documents/{source_id}/text.txt",
        "units_path": f"documents/{source_id}/units.jsonl",
        "unit_count": 0,
    }


def _normative_unit(source_id: str) -> dict:
    return {
        "id": f"NU-{source_id}-article-12-{'b' * 8}",
        "source_document_id": source_id,
        "order": 1,
        "unit_type": "article",
        "path": {"article": "第12条"},
        "citation": "医学部教務規則 第12条",
        "text_exact": "学生は指定期間内に履修登録を行う。",
        "text_normalized": "学生は指定期間内に履修登録を行う。",
        "content_hash": "sha256:" + "b" * 64,
        "anchors": {"page": None, "xpath": None},
        "effective_from": "2026-04-01",
        "effective_to": None,
    }


if __name__ == "__main__":
    unittest.main()
