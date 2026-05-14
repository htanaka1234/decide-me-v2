from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.events import EVENT_TYPES
from decide_me.store import bootstrap_runtime, read_event_log, runtime_paths, validate_runtime
from tests.helpers.cli import run_cli, run_json_cli
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftPromotionCliTests(unittest.TestCase):
    def test_promote_draft_decision_cli_does_not_expose_no_risk_scaffold(self) -> None:
        result = run_cli("promote-draft-decision", "--help")
        self.assertNotIn("--no-risk-scaffold", result.stdout)

    def test_promote_draft_decision_cli_materializes_canonical_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            session_id = _create_session(ai_dir)
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )

            result = run_json_cli(
                "promote-draft-decision",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--draft-decision-id",
                "DD-001",
                "--session-id",
                session_id,
            )

            self.assertEqual("promoted", result["status"])
            self.assertEqual("proposed", result["decision"]["status"])
            self.assertTrue(result["proposal"]["is_active"])
            self.assertTrue(Path(result["sidecar"]["promotion_log_path"]).exists())
            self.assertTrue({event["event_type"] for event in read_event_log(runtime_paths(ai_dir))}.issubset(EVENT_TYPES))
            self.assertEqual({"ok": True, "issues": []}, run_json_cli("validate-state", "--ai-dir", str(ai_dir)))
            self.assertEqual({"ok": True, "issues": []}, run_json_cli("validate-state", "--ai-dir", str(ai_dir), "--cached"))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_promote_draft_set_requires_bulk_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            session_id = _create_session(ai_dir)
            draft_json = _write_draft_json(Path(tmp), _low_risk_bulk_draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )

            result = run_cli(
                "promote-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--session-id",
                session_id,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("promote-draft-set requires --only-bulk-promotable", result.stderr)

    def test_promote_draft_set_bulk_materializes_single_low_risk_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            session_id = _create_session(ai_dir)
            draft_json = _write_draft_json(Path(tmp), _low_risk_bulk_draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )

            result = run_json_cli(
                "promote-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--session-id",
                session_id,
                "--only-bulk-promotable",
            )

            self.assertEqual("ok", result["status"])
            self.assertEqual(1, result["promoted_count"])
            self.assertEqual("promoted", result["promoted"][0]["status"])

    def test_reconcile_draft_promotions_reports_sidecar_drift_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            session_id = _create_session(ai_dir)
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            run_json_cli(
                "promote-draft-decision",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--draft-decision-id",
                "DD-001",
                "--session-id",
                session_id,
            )
            draft_set_path = ai_dir / "draft-sets" / "DS-20260513-001" / "draft-set.json"
            _set_promoted_decision_ids(draft_set_path, [])
            before_sidecar = draft_set_path.read_bytes()
            before_events = read_event_log(runtime_paths(ai_dir))

            result = run_json_cli(
                "reconcile-draft-promotions",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )

            self.assertEqual("ok", result["status"])
            self.assertEqual(["DD-001"], result["canonical_promoted_decision_ids"])
            self.assertEqual([], result["sidecar_promoted_decision_ids"])
            self.assertEqual(["DD-001"], result["missing_in_sidecar"])
            self.assertEqual([], result["stale_in_sidecar"])
            self.assertFalse(result["repaired"])
            self.assertEqual(before_sidecar, draft_set_path.read_bytes())
            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))

    def test_reconcile_draft_promotions_repair_rebuilds_sidecar_from_canonical_origin(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            session_id = _create_session(ai_dir)
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            run_json_cli(
                "promote-draft-decision",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--draft-decision-id",
                "DD-001",
                "--session-id",
                session_id,
            )
            draft_set_path = ai_dir / "draft-sets" / "DS-20260513-001" / "draft-set.json"
            promotion_log_path = ai_dir / "draft-sets" / "DS-20260513-001" / "promotion-log.jsonl"
            _set_promoted_decision_ids(draft_set_path, [])
            promotion_log_path.write_text("not-json\n", encoding="utf-8")
            before_events = read_event_log(runtime_paths(ai_dir))

            result = run_json_cli(
                "reconcile-draft-promotions",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--repair",
            )

            self.assertTrue(result["repaired"])
            repaired_draft_set = json.loads(draft_set_path.read_text(encoding="utf-8"))
            self.assertEqual(["DD-001"], repaired_draft_set["promotion"]["promoted_decision_ids"])
            log_lines = [json.loads(line) for line in promotion_log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(log_lines))
            self.assertEqual("draft_decision_promoted", log_lines[0]["entry_type"])
            self.assertEqual("DD-001", log_lines[0]["draft_decision_id"])
            self.assertTrue(log_lines[0]["reconstructed"])
            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))

    def test_reconcile_draft_promotions_reports_stale_sidecar_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            draft_set_path = ai_dir / "draft-sets" / "DS-20260513-001" / "draft-set.json"
            _set_promoted_decision_ids(draft_set_path, ["DD-001"])
            before_events = read_event_log(runtime_paths(ai_dir))

            result = run_json_cli(
                "reconcile-draft-promotions",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )

            self.assertEqual([], result["canonical_promoted_decision_ids"])
            self.assertEqual(["DD-001"], result["sidecar_promoted_decision_ids"])
            self.assertEqual([], result["missing_in_sidecar"])
            self.assertEqual(["DD-001"], result["stale_in_sidecar"])
            self.assertFalse(result["repaired"])
            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft promotion CLI.",
        current_milestone="PR3",
    )
    return ai_dir


def _create_session(ai_dir: Path) -> str:
    return run_json_cli(
        "create-session",
        "--ai-dir",
        str(ai_dir),
        "--context",
        "Draft promotion CLI",
    )["session"]["id"]


def _write_draft_json(tmp: Path, payload: dict) -> Path:
    path = tmp / "draft-set.input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _set_promoted_decision_ids(draft_set_path: Path, promoted_decision_ids: list[str]) -> None:
    draft_set = json.loads(draft_set_path.read_text(encoding="utf-8"))
    draft_set.setdefault("promotion", {})["promoted_decision_ids"] = promoted_decision_ids
    draft_set_path.write_text(json.dumps(draft_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        "draft_assumptions",
        "draft_risks",
        "draft_actions",
        "draft_verifications",
        "conflicts",
        "review_queue",
        "promotion",
    ):
        payload.pop(field, None)
    payload["draft_decisions"][0]["alternatives"] = [
        {
            "option": "Store drafts in the canonical event log.",
            "reason_not_recommended": "It would blur accepted and draft state.",
        }
    ]
    return deepcopy(payload)


def _low_risk_bulk_draft_input() -> dict:
    payload = _draft_input()
    draft = payload["draft_decisions"][0]
    draft["risk_tier"] = "low"
    draft["priority"] = "P2"
    draft["human_review"] = {
        "required": False,
        "mode": "bulk",
        "bulk_promotable": True,
        "reason": "Low-risk reversible draft.",
    }
    draft["promotion_recipe"]["acceptance_mode_allowed"] = ["explicit", "ok"]
    draft["promotion_recipe"]["blocked_for_bulk_acceptance"] = False
    payload["promotion"] = {
        "promoted_decision_ids": [],
        "bulk_promotable_ids": ["DD-001"],
        "individual_review_required_ids": [],
    }
    return payload


if __name__ == "__main__":
    unittest.main()
