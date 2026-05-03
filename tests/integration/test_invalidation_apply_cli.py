from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.helpers.impact_runtime import (
    build_impact_runtime,
    changed_paths,
    event_hash_snapshot,
    run_cli,
    run_json_cli,
    runtime_state_snapshot,
)


class InvalidationApplyCliTests(unittest.TestCase):
    def test_apply_candidate_without_approve_is_dry_run_and_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            candidate = _candidate(ai_dir, "add_verification")
            before_events = event_hash_snapshot(ai_dir)
            before_runtime = runtime_state_snapshot(ai_dir)

            result = run_json_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--max-depth",
                "1",
                "--include-low-severity",
                "--candidate-id",
                candidate["candidate_id"],
            )

            self.assertEqual("dry_run", result["status"])
            self.assertFalse(result["approved"])
            self.assertEqual(candidate["candidate_id"], result["candidate_id"])
            self.assertEqual(["E-043f3fe15492-01", "E-043f3fe15492-02"], _event_ids(result["proposed_events"]))
            self.assertEqual(before_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_runtime, runtime_state_snapshot(ai_dir))

    def test_apply_candidate_requires_reason_and_safety_approval_when_gate_needs_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            session_id = _open_session_id(ai_dir)
            candidate = _candidate(ai_dir, "add_verification")
            before = runtime_state_snapshot(ai_dir)

            missing_reason = run_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--max-depth",
                "1",
                "--include-low-severity",
                "--candidate-id",
                candidate["candidate_id"],
                "--session-id",
                session_id,
                "--approve",
                check=False,
            )
            missing_approval = run_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--max-depth",
                "1",
                "--include-low-severity",
                "--candidate-id",
                candidate["candidate_id"],
                "--session-id",
                session_id,
                "--approve",
                "--reason",
                "Add verification after invalidation.",
                check=False,
            )

            self.assertNotEqual(0, missing_reason.returncode)
            self.assertIn("reason is required", missing_reason.stderr)
            self.assertNotEqual(0, missing_approval.returncode)
            self.assertIn("safety approval artifact is required", missing_approval.stderr)
            self.assertEqual(before, runtime_state_snapshot(ai_dir))

    def test_apply_candidate_with_approval_writes_transaction_events(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            session_id = _open_session_id(ai_dir)
            candidate = _candidate(ai_dir, "add_verification")
            approval = run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "ACT-001",
                "--approved-by",
                "tester",
                "--reason",
                "Approve verification add for invalidation apply.",
            )
            before = runtime_state_snapshot(ai_dir)

            result = run_json_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--max-depth",
                "1",
                "--include-low-severity",
                "--candidate-id",
                candidate["candidate_id"],
                "--session-id",
                session_id,
                "--approve",
                "--actor",
                "tester",
                "--reason",
                "Add verification after invalidation.",
                "--safety-approval-id",
                approval["approval_artifact_ids"][0],
            )
            changed = changed_paths(before, runtime_state_snapshot(ai_dir))
            project_state = (ai_dir / "project-state.json").read_text(encoding="utf-8")

        self.assertEqual("applied", result["status"])
        self.assertTrue(result["approved"])
        self.assertEqual(["E-043f3fe15492-01", "E-043f3fe15492-02"], result["event_ids"])
        self.assertTrue(any(path.startswith("events/") for path in changed))
        self.assertIn("VER-043f3fe15492", project_state)
        self.assertIn("L-VER-043f3fe15492-verifies-ACT-001", project_state)

    def test_apply_rejects_manual_or_stale_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            manual = _candidate(ai_dir, "revise")
            missing = run_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--candidate-id",
                manual["candidate_id"],
                "--approve",
                "--reason",
                "Try to apply a manual candidate.",
                check=False,
            )
            stale = run_cli(
                "apply-invalidation-candidate",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "DEC-001",
                "--change-kind",
                "invalidated",
                "--candidate-id",
                "IC-000000000000",
                "--approve",
                "--reason",
                "Try to apply a stale candidate.",
                check=False,
            )

        self.assertNotEqual(0, missing.returncode)
        self.assertIn("cannot be applied automatically", missing.stderr)
        self.assertNotEqual(0, stale.returncode)
        self.assertIn("unknown or stale invalidation candidate", stale.stderr)


def _candidate(ai_dir: Path, candidate_kind: str) -> dict:
    candidates = run_json_cli(
        "show-invalidation-candidates",
        "--ai-dir",
        str(ai_dir),
        "--object-id",
        "DEC-001",
        "--change-kind",
        "invalidated",
        "--max-depth",
        "1",
        "--include-low-severity",
    )
    return next(candidate for candidate in candidates["candidates"] if candidate["candidate_kind"] == candidate_kind)


def _open_session_id(ai_dir: Path) -> str:
    return sorted(path.stem for path in (ai_dir / "sessions").glob("*.json"))[0]


def _event_ids(specs: list[dict]) -> list[str]:
    return [spec["event_id"] for spec in specs]


if __name__ == "__main__":
    unittest.main()
