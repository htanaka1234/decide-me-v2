from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator

from decide_me.lifecycle import close_session, create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.document_runtime import NOW, build_document_runtime, build_two_session_document_runtime
from tests.helpers.impact_runtime import changed_paths, run_cli, runtime_state_snapshot, tree_hash_snapshot
from tests.helpers.typed_metadata import metadata_for_object_type


class DocumentCompilerCliTests(unittest.TestCase):
    def test_export_document_cli_generates_all_markdown_documents(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
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
                    output = ai_dir / "exports" / "documents" / f"{document_type}.md"
                    domain_pack_args = _domain_pack_args_for_document_type(document_type)
                    result = run_cli(
                        "export-document",
                        "--ai-dir",
                        str(ai_dir),
                        "--type",
                        document_type,
                        "--format",
                        "markdown",
                        "--session-id",
                        session_id,
                        *domain_pack_args,
                        "--now",
                        NOW,
                        "--output",
                        str(output),
                    )
                    payload = json.loads(result.stdout)
                    body = output.read_text(encoding="utf-8")
                    self.assertEqual(str(output), payload["path"])
                    self.assertIn("<!-- decide-me:generated:start", body)
                    self.assertIn(f"document_type={document_type}", body)
                    self.assertIn("## Human Notes", body)

            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))

    def test_json_and_csv_exports_are_supported_outputs(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "document-model.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
            json_output = ai_dir / "exports" / "documents" / "decision-brief.json"
            csv_output = ai_dir / "exports" / "documents" / "comparison-table.csv"

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "decision-brief",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--now",
                NOW,
                "--output",
                str(json_output),
            )
            model = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual([], list(validator.iter_errors(model)))
            self.assertEqual("decision-brief", model["document_type"])

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "comparison-table",
                "--format",
                "csv",
                "--session-id",
                session_id,
                "--domain-pack",
                "procurement",
                "--now",
                NOW,
                "--output",
                str(csv_output),
            )
            csv_body = csv_output.read_text(encoding="utf-8")
            self.assertTrue(csv_body.startswith("Option,Recommended By,Criteria Fit"))
            self.assertIn("PRO-001", csv_body)

            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "decision-brief",
                "--format",
                "csv",
                "--session-id",
                session_id,
                "--output",
                str(ai_dir / "exports" / "documents" / "bad.csv"),
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("CSV export is supported only", result.stderr)

    def test_markdown_reexport_preserves_human_notes_and_changes_only_export_path(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
            output = ai_dir / "exports" / "documents" / "risk-register.md"
            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "risk-register",
                "--format",
                "markdown",
                "--session-id",
                session_id,
                "--now",
                NOW,
                "--output",
                str(output),
            )
            output.write_text(output.read_text(encoding="utf-8") + "Keep this note.\n", encoding="utf-8")
            runtime_before = runtime_state_snapshot(ai_dir)
            tree_before = tree_hash_snapshot(ai_dir)

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "risk-register",
                "--format",
                "markdown",
                "--session-id",
                session_id,
                "--now",
                NOW,
                "--output",
                str(output),
            )

            changed = changed_paths(tree_before, tree_hash_snapshot(ai_dir))
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["exports/documents/risk-register.md"], changed)
            self.assertIn("Keep this note.", output.read_text(encoding="utf-8"))

    def test_session_id_export_is_scoped_to_selected_closed_session(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, first_session_id, _second_session_id = build_two_session_document_runtime(Path(tmp))
            output = ai_dir / "exports" / "documents" / "decision-brief.json"

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "decision-brief",
                "--format",
                "json",
                "--session-id",
                first_session_id,
                "--now",
                NOW,
                "--output",
                str(output),
            )

            model = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([first_session_id], model["source"]["session_ids"])
            self.assertIn("OBJ-001", model["source"]["object_ids"])
            self.assertNotIn("OBJ-002", model["source"]["object_ids"])
            self.assertNotIn("DEC-002", model["source"]["object_ids"])

    def test_object_id_export_narrows_scope_and_rejects_unknown_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
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
                "--object-id",
                "OPT-001",
                "--now",
                NOW,
                "--output",
                str(output),
            )
            model = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("OPT-001", model["source"]["object_ids"])
            self.assertNotIn("RSK-002", model["source"]["object_ids"])

            bad_output = ai_dir / "exports" / "documents" / "unknown-object.json"
            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "comparison-table",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--object-id",
                "MISSING-001",
                "--output",
                str(bad_output),
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("unknown object_id: MISSING-001", result.stderr)
            self.assertFalse(bad_output.exists())

    def test_object_id_outside_selected_session_scope_fails_before_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, first_session_id, _second_session_id = build_two_session_document_runtime(Path(tmp))
            output = ai_dir / "exports" / "documents" / "outside-scope.json"

            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "decision-brief",
                "--format",
                "json",
                "--session-id",
                first_session_id,
                "--object-id",
                "OBJ-002",
                "--output",
                str(output),
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("object_id is outside selected session scope: OBJ-002", result.stderr)
            self.assertFalse(output.exists())

    def test_action_plan_object_id_export_is_scoped_and_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = build_document_runtime(Path(tmp))
            output = ai_dir / "exports" / "documents" / "action-plan-scoped.json"
            runtime_before = runtime_state_snapshot(ai_dir)
            tree_before = tree_hash_snapshot(ai_dir)

            run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "action-plan",
                "--format",
                "json",
                "--session-id",
                session_id,
                "--object-id",
                "ACT-001",
                "--now",
                NOW,
                "--output",
                str(output),
            )

            model = json.loads(output.read_text(encoding="utf-8"))
            changed = changed_paths(tree_before, tree_hash_snapshot(ai_dir))
            self.assertEqual(runtime_before, runtime_state_snapshot(ai_dir))
            self.assertEqual(["exports/documents/action-plan-scoped.json"], changed)
            self.assertIn("ACT-001", model["source"]["object_ids"])
            self.assertIn("DEC-001", model["source"]["object_ids"])
            self.assertNotIn("RSK-002", model["source"]["object_ids"])

    def test_action_plan_export_fails_on_unresolved_conflicts_before_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_ids = _build_conflict_runtime(Path(tmp))
            output = ai_dir / "exports" / "documents" / "action-plan.md"

            result = run_cli(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "action-plan",
                "--format",
                "markdown",
                "--session-id",
                session_ids[0],
                "--session-id",
                session_ids[1],
                "--output",
                str(output),
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("unresolved session conflicts", result.stderr)
            self.assertFalse(output.exists())


def _build_conflict_runtime(tmp: Path) -> tuple[Path, list[str]]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Conflict fixture.",
        current_milestone="Phase 8",
    )
    first = create_session(str(ai_dir), context="First answer")
    first_id = first["session"]["id"]
    transact(ai_dir, lambda _bundle: _first_conflict_events(first_id))
    rebuild_and_persist(ai_dir)
    close_session(str(ai_dir), first_id)

    second = create_session(str(ai_dir), context="Second answer")
    second_id = second["session"]["id"]
    transact(ai_dir, lambda _bundle: _second_conflict_events(second_id))
    rebuild_and_persist(ai_dir)
    close_session(str(ai_dir), second_id)
    return ai_dir, [first_id, second_id]


def _domain_pack_args_for_document_type(document_type: str) -> tuple[str, ...]:
    pack_id = {
        "review-memo": "research",
        "research-plan": "research",
        "comparison-table": "procurement",
    }.get(document_type)
    if pack_id is None:
        return ()
    return ("--domain-pack", pack_id)


def _first_conflict_events(session_id: str) -> list[dict]:
    return [
        _object_event(session_id, "E-D-001", "D-001", "decision", "accepted", {"priority": "P0", "frontier": "now"}),
        _object_event(session_id, "E-P-001", "P-001", "proposal", "accepted", {}),
        _object_event(session_id, "E-O-001", "O-001", "option", "active", {}),
        _link_event(session_id, "E-L-P1-D", "L-P-001-addresses-D-001", "P-001", "addresses", "D-001"),
        _link_event(session_id, "E-L-P1-O1", "L-P-001-recommends-O-001", "P-001", "recommends", "O-001"),
        _link_event(session_id, "E-L-D-P1", "L-D-001-accepts-P-001", "D-001", "accepts", "P-001"),
    ]


def _second_conflict_events(session_id: str) -> list[dict]:
    return [
        _object_event(session_id, "E-P-002", "P-002", "proposal", "accepted", {}),
        _object_event(session_id, "E-O-002", "O-002", "option", "active", {}),
        _link_event(session_id, "E-L-P2-D", "L-P-002-addresses-D-001", "P-002", "addresses", "D-001"),
        _link_event(session_id, "E-L-P2-O2", "L-P-002-recommends-O-002", "P-002", "recommends", "O-002"),
        _link_event(session_id, "E-L-D-P2", "L-D-001-accepts-P-002", "D-001", "accepts", "P-002"),
    ]


def _object_event(
    session_id: str,
    event_id: str,
    object_id: str,
    object_type: str,
    status: str,
    metadata: dict,
) -> dict:
    typed_metadata = metadata_for_object_type(object_type)
    typed_metadata.update(metadata)
    return {
        "event_id": event_id,
        "session_id": session_id,
        "event_type": "object_recorded",
        "payload": {
            "object": {
                "id": object_id,
                "type": object_type,
                "title": object_id,
                "body": object_id,
                "status": status,
                "created_at": NOW,
                "updated_at": None,
                "source_event_ids": [event_id],
                "metadata": typed_metadata,
            }
        },
    }


def _link_event(
    session_id: str,
    event_id: str,
    link_id: str,
    source: str,
    relation: str,
    target: str,
) -> dict:
    return {
        "event_id": event_id,
        "session_id": session_id,
        "event_type": "object_linked",
        "payload": {
            "link": {
                "id": link_id,
                "source_object_id": source,
                "relation": relation,
                "target_object_id": target,
                "rationale": "Conflict fixture link.",
                "created_at": NOW,
                "source_event_ids": [event_id],
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
