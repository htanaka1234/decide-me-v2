from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.store import bootstrap_runtime, read_event_log, runtime_paths
from tests.helpers.cli import run_cli, run_json_cli
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class AutopilotDraftCliTests(unittest.TestCase):
    def test_autopilot_draft_cli_creates_sidecar_projection_and_exports(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _write_seed(Path(tmp), _seed_payload())

            result = run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--seed-draft-json",
                str(seed),
                "--now",
                "2026-05-13T03:00:00Z",
                "--force",
            )

            self.assertEqual("ok", result["status"])
            self.assertTrue(Path(result["draft_set_path"]).exists())
            self.assertTrue(Path(result["projection_path"]).exists())
            for path in result["exports"].values():
                self.assertTrue(Path(path).exists())

    def test_autopilot_draft_cli_does_not_create_canonical_events(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _write_seed(Path(tmp), _seed_payload())
            before_events = read_event_log(runtime_paths(ai_dir))
            before_project_state = (ai_dir / "project-state.json").read_bytes()
            before_runtime_index = (ai_dir / "runtime-index.json").read_bytes()

            run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--seed-draft-json",
                str(seed),
                "--no-export",
            )

            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))
            self.assertEqual(before_project_state, (ai_dir / "project-state.json").read_bytes())
            self.assertEqual(before_runtime_index, (ai_dir / "runtime-index.json").read_bytes())

    def test_project_draft_set_cli_writes_projection_only(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _write_seed(Path(tmp), _seed_payload())
            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(seed),
                "--draft-set-id",
                "DS-20260513-001",
            )

            result = run_json_cli(
                "project-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
                "--now",
                "2026-05-13T03:00:00Z",
            )

            self.assertEqual("ok", result["status"])
            self.assertTrue((ai_dir / "draft-sets" / "DS-20260513-001" / "draft-projection.json").exists())
            self.assertFalse((ai_dir / "draft-sets" / "DS-20260513-001" / "review-queue.json").exists())
            self.assertFalse((ai_dir / "draft-sets" / "DS-20260513-001" / "exports").exists())

    def test_autopilot_draft_cli_reports_stop_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _write_seed(Path(tmp), _seed_payload())

            result = run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--seed-draft-json",
                str(seed),
                "--no-export",
            )

            self.assertIn("stop_reason", result["convergence"])
            self.assertFalse(result["canonical_events_created"])

    def test_autopilot_draft_cli_respects_max_iterations(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            result = run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--goal",
                "Create a reviewable draft set.",
                "--max-iterations",
                "1",
                "--no-export",
            )

            self.assertLessEqual(result["convergence"]["iterations"], 1)

    def test_autopilot_draft_cli_respects_max_draft_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _seed_payload()
            seed["draft_decisions"] = [seed["draft_decisions"][0]]
            seed_path = _write_seed(Path(tmp), seed)

            result = run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--seed-draft-json",
                str(seed_path),
                "--max-draft-decisions",
                "1",
                "--no-export",
            )
            draft_set = json.loads(Path(result["draft_set_path"]).read_text(encoding="utf-8"))

            self.assertLessEqual(len(draft_set["draft_decisions"]), 1)

    def test_autopilot_draft_cli_seed_json_priority(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            seed = _seed_payload()
            seed["goal"]["title"] = "Seed goal wins"
            seed_path = _write_seed(Path(tmp), seed)

            result = run_json_cli(
                "autopilot-draft",
                "--ai-dir",
                str(ai_dir),
                "--seed-draft-json",
                str(seed_path),
                "--goal",
                "Goal argument should not replace seed",
                "--no-export",
            )
            draft_set = json.loads(Path(result["draft_set_path"]).read_text(encoding="utf-8"))

            self.assertEqual("Seed goal wins", draft_set["goal"]["title"])

    def test_cli_help_includes_autopilot_draft_after_pr5(self) -> None:
        result = run_cli("--help", cwd=Path(__file__).resolve().parents[2])

        self.assertIn("autopilot-draft", result.stdout + result.stderr)
        self.assertIn("project-draft-set", result.stdout + result.stderr)


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise autopilot draft CLI.",
        current_milestone="PR5",
    )
    return ai_dir


def _write_seed(tmp: Path, payload: dict) -> Path:
    path = tmp / "draft-set.input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _seed_payload() -> dict:
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
    base = payload["draft_decisions"][0]
    base["priority"] = "P2"
    base["layer"] = "purpose"
    base["risk_tier"] = "low"
    base["alternatives"] = [
        {
            "option": "Skip diagnostics",
            "reason_not_recommended": "Reviewers would miss gaps.",
        }
    ]
    base["evidence_coverage"]["status"] = "sufficient"
    base["evidence_coverage"]["missing"] = []
    base["human_review"] = {
        "required": False,
        "mode": "bulk",
        "bulk_promotable": True,
        "reason": "Low-risk test seed.",
    }
    base["promotion_recipe"]["blocked_for_bulk_acceptance"] = False
    for draft_id, layer in (("DD-002", "constraint"), ("DD-003", "verification"), ("DD-004", "review")):
        draft = deepcopy(base)
        draft["id"] = draft_id
        draft["layer"] = layer
        draft["question"] = f"How should {layer} be handled?"
        payload["draft_decisions"].append(draft)
    return payload


if __name__ == "__main__":
    unittest.main()
