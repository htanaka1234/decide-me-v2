from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.protocol import discover_decision
from decide_me.store import bootstrap_runtime, read_event_log, rebuild_and_persist, runtime_paths
from tests.helpers.cli import run_json_cli
from tests.helpers.impact_runtime import runtime_state_snapshot


class Phase12EvidenceSourceStoreIntegrationTests(unittest.TestCase):
    def test_source_store_import_search_link_impact_and_export_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ai_dir, session_id = _build_runtime(tmp_path)
            source_file = tmp_path / "academic-regulation.xml"
            source_text = "学生は指定期間内に履修登録を行う。"
            source_file.write_text(_egov_xml(source_text), encoding="utf-8")

            imported = run_json_cli(
                "import-source",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "academic_regulation",
                "--title",
                "医学部教務規則",
                "--file",
                str(source_file),
                "--effective-from",
                "2026-04-01",
                "--authority",
                "Example University",
                "--version-label",
                "2026年度版",
            )
            source_id = imported["source_document"]["id"]
            self.assertEqual("imported", imported["status"])
            self.assertTrue((ai_dir / "sources" / "documents" / source_id / "original.xml").exists())

            decomposed = run_json_cli(
                "decompose-source",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                source_id,
                "--strategy",
                "egov-law-xml",
            )
            self.assertGreaterEqual(decomposed["unit_count"], 1)

            searched = run_json_cli(
                "search-evidence",
                "--ai-dir",
                str(ai_dir),
                "--query",
                "履修登録",
            )
            self.assertGreaterEqual(searched["count"], 1)
            source_unit_id = searched["results"][0]["source_unit_id"]

            linked = run_json_cli(
                "link-evidence",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--decision-id",
                "D-course-registration",
                "--source-unit-id",
                source_unit_id,
                "--relevance",
                "supports",
                "--quote",
                source_text,
                "--interpretation-note",
                "履修登録期限を制約として扱う。",
            )
            self.assertEqual("linked", linked["status"])

            before = runtime_state_snapshot(ai_dir)
            impact = run_json_cli(
                "show-source-impact",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                source_id,
            )
            self.assertEqual(before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["D-course-registration"], impact["affected_decision_ids"])

            validation = run_json_cli("validate-state", "--ai-dir", str(ai_dir))
            self.assertTrue(validation["ok"])
            source_validation = run_json_cli("validate-sources", "--ai-dir", str(ai_dir))
            self.assertTrue(source_validation["ok"])

            rebuild_and_persist(ai_dir)
            rebuilt_index = run_json_cli("rebuild-evidence-index", "--ai-dir", str(ai_dir))
            self.assertGreaterEqual(rebuilt_index["unit_count"], 1)
            searched_after_rebuild = run_json_cli(
                "search-evidence",
                "--ai-dir",
                str(ai_dir),
                "--query",
                "履修登録",
            )
            self.assertEqual(source_unit_id, searched_after_rebuild["results"][0]["source_unit_id"])

            close_session(str(ai_dir), session_id)
            output = ai_dir / "exports" / "documents" / "decision-brief.json"
            run_json_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "decision-brief",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--output",
                str(output),
            )
            model_text = output.read_text(encoding="utf-8")
            self.assertIn(source_unit_id, model_text)
            self.assertIn("医学部教務規則", model_text)
            self.assertIn(source_text, model_text)

            source_event_payloads = [
                event["payload"]
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] in {"source_document_imported", "normative_units_extracted", "source_version_updated"}
            ]
            self.assertTrue(source_event_payloads)
            self.assertNotIn(source_text, json.dumps(source_event_payloads, ensure_ascii=False))


def _build_runtime(tmp_path: Path) -> tuple[Path, str]:
    ai_dir = tmp_path / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Phase 12 Demo",
        objective="Exercise the evidence source store.",
        current_milestone="Phase 12 source store",
    )
    session = create_session(str(ai_dir), context="Course registration policy")
    session_id = session["session"]["id"]
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": "D-course-registration",
            "title": "締切後履修登録申請を認めるか",
            "priority": "P0",
            "frontier": "now",
            "domain": "legal",
            "resolvable_by": "external",
            "question": "締切後履修登録申請を認める運用にするか。",
        },
    )
    return ai_dir, session_id


def _egov_xml(source_text: str) -> str:
    return f"""
    <Law>
      <LawBody>
        <Article Num="12">
          <ArticleTitle>第十二条</ArticleTitle>
          <Paragraph Num="2">
            <ParagraphNum>2</ParagraphNum>
            <ParagraphSentence><Sentence>{source_text}</Sentence></ParagraphSentence>
          </Paragraph>
        </Article>
      </LawBody>
    </Law>
    """


if __name__ == "__main__":
    unittest.main()
