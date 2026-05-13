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
