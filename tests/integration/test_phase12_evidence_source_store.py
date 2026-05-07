from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.events import new_event_id, utc_now
from decide_me.lifecycle import close_session, create_session
from decide_me.protocol import discover_decision
from decide_me.store import bootstrap_runtime, load_runtime, read_event_log, rebuild_and_persist, runtime_paths, transact
from tests.helpers.cli import run_cli, run_json_cli
from tests.helpers.impact_runtime import runtime_state_snapshot
from tests.helpers.typed_metadata import assumption_metadata


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

            bad_quote = run_cli(
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
                "原文にない引用",
                check=False,
            )
            self.assertNotEqual(0, bad_quote.returncode)
            self.assertIn("quote must be contained in source unit text", bad_quote.stderr)

            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-course-exception",
                    "title": "例外申請プロセスを設けるか",
                    "priority": "P1",
                    "frontier": "later",
                    "domain": "legal",
                    "resolvable_by": "external",
                    "question": "締切後申請の例外プロセスを別に設けるか。",
                },
            )
            second_link = run_json_cli(
                "link-evidence",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--decision-id",
                "D-course-exception",
                "--source-unit-id",
                source_unit_id,
                "--relevance",
                "constrains",
                "--quote",
                "指定期間内",
                "--interpretation-note",
                "例外プロセス設計の制約として扱う。",
            )
            self.assertEqual("linked", second_link["status"])
            self.assertNotEqual(linked["link_id"], second_link["link_id"])
            repeated_second_link = run_json_cli(
                "link-evidence",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--decision-id",
                "D-course-exception",
                "--source-unit-id",
                source_unit_id,
                "--relevance",
                "constrains",
                "--quote",
                "指定期間内",
                "--interpretation-note",
                "例外プロセス設計の制約として扱う。",
            )
            self.assertEqual("exists", repeated_second_link["status"])
            self.assertEqual(second_link["link_id"], repeated_second_link["link_id"])

            evidence_register = run_json_cli("show-evidence-register", "--ai-dir", str(ai_dir))
            source_store_links = evidence_register["items"][0]["source_store_links"]
            quotes_by_target = {item["target_object_id"]: item["quote"] for item in source_store_links}
            self.assertEqual(source_text, quotes_by_target["D-course-registration"])
            self.assertEqual("指定期間内", quotes_by_target["D-course-exception"])
            bundle = load_runtime(runtime_paths(ai_dir))
            evidence_objects = [
                obj
                for obj in bundle["project_state"]["objects"]
                if obj["id"] == linked["evidence_object_id"]
            ]
            self.assertEqual(1, len(evidence_objects))
            self.assertNotIn("quote", evidence_objects[0]["metadata"])
            self.assertNotIn("interpretation_note", evidence_objects[0]["metadata"])

            before = runtime_state_snapshot(ai_dir)
            impact = run_json_cli(
                "show-source-impact",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                source_id,
            )
            self.assertEqual(before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["D-course-exception", "D-course-registration"], impact["affected_decision_ids"])

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

    def test_source_impact_traverses_downstream_and_previous_versions(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ai_dir, session_id = _build_runtime(tmp_path)
            source_file = tmp_path / "academic-regulation-v1.txt"
            source_file.write_text(
                "第1条 学生は指定期間内に履修登録を行う。\n",
                encoding="utf-8",
            )

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
            )
            source_id = imported["source_document"]["id"]
            run_json_cli(
                "decompose-source",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                source_id,
                "--strategy",
                "japanese-regulation-text",
            )
            searched = run_json_cli(
                "search-evidence",
                "--ai-dir",
                str(ai_dir),
                "--query",
                "履修登録",
            )
            source_unit_id = searched["results"][0]["source_unit_id"]

            _record_assumption_constraining_decision(ai_dir, session_id)
            run_json_cli(
                "link-evidence",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "A-registration-window",
                "--source-unit-id",
                source_unit_id,
                "--relevance",
                "supports",
                "--quote",
                "履修登録を行う",
            )

            impact = run_json_cli(
                "show-source-impact",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                source_id,
            )
            self.assertEqual(["A-registration-window"], [item["object_id"] for item in impact["affected_objects"]])
            self.assertEqual(["D-course-registration"], impact["affected_decision_ids"])
            self.assertEqual(["D-course-registration"], [item["decision_id"] for item in impact["downstream_affected_decisions"]])

            updated_source_file = tmp_path / "academic-regulation-v2.txt"
            updated_source_file.write_text(
                "第1条 学生は指定期間内に履修登録を行う。例外は別に定める。\n",
                encoding="utf-8",
            )
            imported_v2 = run_json_cli(
                "import-source",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "academic_regulation",
                "--title",
                "医学部教務規則",
                "--file",
                str(updated_source_file),
                "--effective-from",
                "2026-04-01",
                "--previous-source-id",
                source_id,
            )
            new_source_id = imported_v2["source_document"]["id"]
            version_events = [
                event
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "source_version_updated"
                and event["payload"]["source_document_id"] == new_source_id
            ]
            self.assertEqual(source_id, version_events[-1]["payload"]["previous_source_document_id"])

            previous_impact = run_json_cli(
                "show-source-impact",
                "--ai-dir",
                str(ai_dir),
                "--source-id",
                new_source_id,
                "--include-previous-version-links",
            )
            self.assertEqual([source_id], previous_impact["included_previous_source_document_ids"])
            self.assertEqual(["D-course-registration"], previous_impact["affected_decision_ids"])


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


def _record_assumption_constraining_decision(ai_dir: Path, session_id: str) -> None:
    now = utc_now()
    assumption_event_id = new_event_id()
    link_event_id = new_event_id()

    def builder(_bundle: dict) -> list[dict]:
        return [
            {
                "event_id": assumption_event_id,
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {
                    "object": {
                        "id": "A-registration-window",
                        "type": "assumption",
                        "title": "履修登録期間は固定されている",
                        "body": "Source-derived assumption for impact traversal.",
                        "status": "active",
                        "created_at": now,
                        "updated_at": None,
                        "source_event_ids": [assumption_event_id],
                        "metadata": assumption_metadata(
                            statement="履修登録期間は固定されている。",
                            confidence="medium",
                        ),
                    }
                },
            },
            {
                "event_id": link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {
                    "link": {
                        "id": "L-A-registration-window-constrains-D-course-registration",
                        "source_object_id": "A-registration-window",
                        "relation": "constrains",
                        "target_object_id": "D-course-registration",
                        "rationale": "履修登録期間が decision を制約する。",
                        "created_at": now,
                        "source_event_ids": [link_event_id],
                    }
                },
            },
        ]

    transact(ai_dir, builder)


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
