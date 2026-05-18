from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.store import bootstrap_runtime, read_event_log, runtime_paths, validate_runtime
from tests.helpers.cli import run_cli, run_json_cli
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftSetCliTests(unittest.TestCase):
    def test_create_show_list_cli_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())

            created = run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            shown = run_json_cli(
                "show-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-001",
            )
            listed = run_json_cli("list-draft-sets", "--ai-dir", str(ai_dir))

            self.assertEqual("created", created["status"])
            self.assertEqual("DS-20260513-001", created["draft_set_id"])
            self.assertEqual("DS-20260513-001", shown["draft_set"]["id"])
            self.assertEqual(2, shown["draft_set"]["schema_version"])
            self.assertIn("exploration_contract", shown["draft_set"])
            self.assertEqual(
                {"max_draft_decisions": 20, "max_iterations": 0},
                shown["draft_set"]["exploration_contract"]["budgets"],
            )
            self.assertFalse(shown["runtime_status"]["is_stale"])
            self.assertEqual(1, listed["count"])
            self.assertEqual("DS-20260513-001", listed["draft_sets"][0]["id"])

    def test_create_show_list_do_not_mutate_event_log(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            before_events = read_event_log(runtime_paths(ai_dir))

            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            run_json_cli("show-draft-set", "--ai-dir", str(ai_dir), "--draft-set-id", "DS-20260513-001")
            run_json_cli("list-draft-sets", "--ai-dir", str(ai_dir))

            after_events = read_event_log(runtime_paths(ai_dir))
            self.assertEqual(before_events, after_events)

    def test_create_show_list_do_not_mutate_project_state_or_runtime_index(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = _write_draft_json(Path(tmp), _draft_input())
            before_project_state = (ai_dir / "project-state.json").read_bytes()
            before_taxonomy_state = (ai_dir / "taxonomy-state.json").read_bytes()
            before_runtime_index = (ai_dir / "runtime-index.json").read_bytes()

            run_json_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                "--draft-set-id",
                "DS-20260513-001",
            )
            run_json_cli("show-draft-set", "--ai-dir", str(ai_dir), "--draft-set-id", "DS-20260513-001")
            run_json_cli("list-draft-sets", "--ai-dir", str(ai_dir))

            self.assertEqual(before_project_state, (ai_dir / "project-state.json").read_bytes())
            self.assertEqual(before_taxonomy_state, (ai_dir / "taxonomy-state.json").read_bytes())
            self.assertEqual(before_runtime_index, (ai_dir / "runtime-index.json").read_bytes())

    def test_create_rejects_invalid_json(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            draft_json = Path(tmp) / "draft-set.input.json"
            draft_json.write_text("{", encoding="utf-8")

            result = run_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("draft-json contains malformed JSON", result.stderr)

    def test_create_rejects_invalid_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["draft_decisions"][0]["status"] = "accepted"
            draft_json = _write_draft_json(Path(tmp), payload)

            result = run_cli(
                "create-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-json",
                str(draft_json),
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("draft_decisions[0].status must be one of: draft, recommended", result.stderr)

    def test_show_missing_draft_set_returns_nonzero(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            result = run_cli(
                "show-draft-set",
                "--ai-dir",
                str(ai_dir),
                "--draft-set-id",
                "DS-20260513-999",
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("draft set not found: DS-20260513-999", result.stderr)

    def test_list_empty_returns_count_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            result = run_json_cli("list-draft-sets", "--ai-dir", str(ai_dir))

            self.assertEqual({"status": "ok", "count": 0, "draft_sets": []}, result)

    def test_validate_state_still_passes_after_create_draft_set(self) -> None:
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

            cached = run_json_cli("validate-state", "--ai-dir", str(ai_dir), "--cached")
            full = run_json_cli("validate-state", "--ai-dir", str(ai_dir), "--full")

            self.assertEqual({"ok": True, "issues": []}, cached)
            self.assertEqual({"ok": True, "issues": []}, full)
            self.assertEqual([], validate_runtime(ai_dir))


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft set CLI.",
        current_milestone="PR1",
    )
    return ai_dir


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
        "exploration_contract",
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
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()
