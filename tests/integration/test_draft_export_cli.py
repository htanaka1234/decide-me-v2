from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, read_event_log, runtime_paths
from tests.helpers.cli import run_cli, run_json_cli
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftExportCliTests(unittest.TestCase):
    def test_review_draft_set_cli_returns_json_and_writes_review_queue_without_event_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            before_events = read_event_log(runtime_paths(ai_dir))
            before_runtime = _runtime_state_snapshot(ai_dir)

            result = run_json_cli(
                "review-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--now",
                "2026-05-13T03:00:00Z",
            )

            review_queue_path = ai_dir / "draft-sets" / "DS-20260513-001" / "review-queue.json"
            self.assertEqual("ok", result["status"])
            self.assertEqual("DS-20260513-001", result["draft_set_id"])
            self.assertTrue(review_queue_path.exists())
            self.assertEqual(result, json.loads(review_queue_path.read_text(encoding="utf-8")))
            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))
            self.assertEqual(before_runtime, _runtime_state_snapshot(ai_dir))

    def test_export_draft_set_cli_writes_four_markdown_files_and_review_queue_json(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)

            result = run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--format",
                "markdown",
                "--now",
                "2026-05-13T03:00:00Z",
            )

            self.assertEqual("ok", result["status"])
            self.assertTrue(Path(result["review_queue_path"]).exists())
            for key in ("preflight", "draft_decisions", "review_queue", "assumptions_risks"):
                path = Path(result["paths"][key])
                self.assertTrue(path.exists(), key)
                body = path.read_text(encoding="utf-8")
                self.assertIn("DRAFT / NOT ACCEPTED", body)
                self.assertIn("<!-- decide-me:generated:start", body)
                self.assertIn("## Human Notes", body)

            preflight = Path(result["paths"]["preflight"]).read_text(encoding="utf-8")
            draft_decisions = Path(result["paths"]["draft_decisions"]).read_text(encoding="utf-8")
            review_queue = Path(result["paths"]["review_queue"]).read_text(encoding="utf-8")
            assumptions_risks = Path(result["paths"]["assumptions_risks"]).read_text(encoding="utf-8")
            self.assertIn("## Goal", preflight)
            self.assertIn("## Source Context", preflight)
            self.assertIn("## Convergence", preflight)
            self.assertIn("## Human Approval Plan", preflight)
            self.assertIn("Reason not recommended", draft_decisions)
            self.assertIn("Evidence Coverage", draft_decisions)
            self.assertIn("## Blocked Items", review_queue)
            self.assertIn("## Individual Review Required", review_queue)
            self.assertIn("## Bulk Materialize Candidates", review_queue)
            self.assertIn("## Must Not Bulk Promote", review_queue)
            self.assertIn("## Draft Assumptions", assumptions_risks)
            self.assertIn("## AI Inference / Missing Evidence", assumptions_risks)

    def test_export_draft_set_preflight_includes_gap_summary_when_projection_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            run_json_cli(
                "project-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )

            result = run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--format",
                "markdown",
            )
            preflight = Path(result["paths"]["preflight"]).read_text(encoding="utf-8")

            self.assertIn("## Gap Diagnostics", preflight)
            self.assertIn("Stop reason", preflight)
            self.assertIn("missing_purpose_layer", preflight)

    def test_export_draft_set_does_not_modify_project_state_or_event_log(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            before_events = read_event_log(runtime_paths(ai_dir))
            before_runtime = _runtime_state_snapshot(ai_dir)

            run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )

            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))
            self.assertEqual(before_runtime, _runtime_state_snapshot(ai_dir))

    def test_export_draft_set_reports_stale_project_head_as_warning(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            create_session(str(ai_dir), context="Change project head before export.")

            result = run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )
            review_queue = json.loads(Path(result["review_queue_path"]).read_text(encoding="utf-8"))

            self.assertTrue(review_queue["stale"])
            self.assertEqual("warning", review_queue["status"])
            self.assertTrue(any("stale project_head" in warning for warning in result["warnings"]))

    def test_markdown_reexport_preserves_human_notes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            result = run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )
            preflight_path = Path(result["paths"]["preflight"])
            body = preflight_path.read_text(encoding="utf-8")
            preflight_path.write_text(body + "- Human note survives.\n", encoding="utf-8")

            run_json_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )

            self.assertIn("- Human note survives.", preflight_path.read_text(encoding="utf-8"))

    def test_export_draft_set_rejects_unknown_draft_set_id(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            result = run_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-999",
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("draft set not found: DS-20260513-999", result.stderr)

    def test_export_draft_set_rejects_unmarked_existing_file_without_force(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            _create_draft(ai_dir, draft_json)
            preflight_path = ai_dir / "draft-sets" / "DS-20260513-001" / "exports" / "preflight.md"
            preflight_path.parent.mkdir(parents=True, exist_ok=True)
            preflight_path.write_text("# Human file\n", encoding="utf-8")

            result = run_cli(
                "export-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("pass --force to overwrite it", result.stderr)


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft export CLI.",
        current_milestone="PR2",
    )
    return ai_dir


def _create_draft(ai_dir: Path, draft_json: Path) -> None:
    run_json_cli(
        "create-draft-set",
        "--ai-dir",
        str(ai_dir),
        "--draft-json",
        str(draft_json),
        "--draft-set-id",
        "DS-20260513-001",
    )


def _write_draft_json(tmp: Path, payload: dict) -> Path:
    path = tmp / "draft-set.input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _draft_input() -> dict:
    payload = minimal_valid_draft_set()
    for field in (
        "schema_version",
        "id",
        "status",
        "mode",
        "created_at",
        "generated_by",
        "source_context",
        "convergence",
        "review_queue",
        "promotion",
    ):
        payload.pop(field, None)
    payload["draft_decisions"][0]["risk_tier"] = "low"
    payload["draft_decisions"][0]["evidence_coverage"]["status"] = "sufficient"
    payload["draft_decisions"][0]["alternatives"] = [
        {
            "option": "Write canonical accepted decisions",
            "reason_not_recommended": "Promotion is explicitly out of PR-2 scope.",
        }
    ]
    payload["draft_decisions"][0]["human_review"] = {
        "required": False,
        "mode": "bulk",
        "bulk_promotable": True,
        "reason": "Low-risk derived export.",
    }
    payload["draft_decisions"][0]["promotion_recipe"]["blocked_for_bulk_acceptance"] = False
    payload["draft_assumptions"] = [
        {
            "id": "DA-001",
            "statement": "Review exports are derived output.",
            "evidence_status": "partial",
            "missing_evidence": ["Manual review acceptance criteria"],
            "invalidates_if_false": "Promotion flow must change.",
            "owner": "maintainer",
        }
    ]
    payload["draft_risks"] = [
        {
            "id": "DR-001",
            "statement": "Draft output could look canonical.",
            "severity": "high",
            "likelihood": "medium",
            "risk_tier": "high",
            "reversibility": "partially_reversible",
            "approval_threshold": "human_review",
        }
    ]
    payload["draft_actions"] = [
        {
            "id": "DACT-001",
            "summary": "Review the draft queue.",
            "linked_decisions": ["DD-001"],
            "verification_refs": ["DV-001"],
        }
    ]
    payload["draft_verifications"] = [
        {
            "id": "DV-001",
            "method": "inspection",
            "result": "pending",
            "target_ids": ["DD-001"],
        }
    ]
    return deepcopy(payload)


def _runtime_state_snapshot(ai_dir: Path) -> dict[str, bytes]:
    paths = [
        ai_dir / "project-state.json",
        ai_dir / "taxonomy-state.json",
        ai_dir / "runtime-index.json",
    ]
    sessions_dir = ai_dir / "sessions"
    if sessions_dir.exists():
        paths.extend(sorted(sessions_dir.glob("*.json")))
    return {str(path.relative_to(ai_dir)): path.read_bytes() for path in paths if path.exists()}


if __name__ == "__main__":
    unittest.main()
