from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from decide_me.store import rebuild_and_persist, transact
from tests.helpers.impact_runtime import (
    build_impact_runtime,
    changed_paths,
    event_hash_snapshot,
    run_cli,
    run_json_cli,
    runtime_state_snapshot,
)
from tests.helpers.typed_metadata import metadata_for_object_type


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
            self.assertEqual([], result["committed_events"])
            self.assertEqual(before_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_runtime, runtime_state_snapshot(ai_dir))

    def test_apply_candidate_dry_run_validates_explicit_session_id(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            candidate = _candidate(ai_dir, "add_verification")
            before_runtime = runtime_state_snapshot(ai_dir)

            result = run_cli(
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
                "S-missing",
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("unknown session_id: S-missing", result.stderr)
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
        self.assertEqual(result["event_ids"], _event_ids(result["committed_events"]))
        self.assertEqual(["object_recorded", "object_linked"], _event_types(result["committed_events"]))
        self.assertEqual([session_id, session_id], _event_sessions(result["committed_events"]))
        self.assertTrue(all(event["tx_id"] for event in result["committed_events"]))
        self.assertEqual([1, 2], [event["tx_index"] for event in result["committed_events"]])
        self.assertTrue(any(path.startswith("events/") for path in changed))
        self.assertIn("VER-043f3fe15492", project_state)
        self.assertIn("L-VER-043f3fe15492-verifies-ACT-001", project_state)

    def test_high_severity_candidate_can_use_candidate_apply_approval_when_gate_does_not_require_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            session_id = _open_session_id(ai_dir)
            transact(ai_dir, lambda _bundle: _high_downstream_decision_events(session_id))
            rebuild_and_persist(ai_dir)
            gate_before = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "DEC-003")
            candidate = _candidate_for_target(ai_dir, "DEC-003", "invalidate")

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
                "Invalidate downstream accepted decision.",
                check=False,
            )
            approval = run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "DEC-003",
                "--approved-by",
                "tester",
                "--reason",
                "Approve high severity candidate application.",
                "--candidate-apply-approval",
            )
            gate_after_approval = run_json_cli("show-safety-gate", "--ai-dir", str(ai_dir), "--object-id", "DEC-003")

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
                "Invalidate downstream accepted decision.",
                "--safety-approval-id",
                approval["approval_artifact_ids"][0],
            )

        self.assertEqual("high", candidate["severity"])
        self.assertEqual("materialized", candidate["materialization_status"])
        self.assertEqual("passed", gate_before["gate_status"])
        self.assertFalse(gate_before["approval_required"])
        self.assertNotEqual(0, missing_approval.returncode)
        self.assertIn("safety approval artifact is required for high severity candidate", missing_approval.stderr)
        self.assertEqual("approved", approval["status"])
        self.assertFalse(gate_after_approval["approval_required"])
        self.assertEqual(approval["approval_artifact_ids"], gate_after_approval["approval_artifact_ids"])
        self.assertEqual("applied", result["status"])
        self.assertEqual(candidate["candidate_id"], result["candidate_id"])
        self.assertEqual(["object_status_changed", "object_updated"], _event_types(result["committed_events"]))

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
    return next(candidate for candidate in _candidates(ai_dir)["candidates"] if candidate["candidate_kind"] == candidate_kind)


def _candidate_for_target(ai_dir: Path, target_object_id: str, candidate_kind: str) -> dict:
    return next(
        candidate
        for candidate in _candidates(ai_dir)["candidates"]
        if candidate["target_object_id"] == target_object_id and candidate["candidate_kind"] == candidate_kind
    )


def _candidates(ai_dir: Path) -> dict:
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
    return candidates


def _high_downstream_decision_events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-high-decision",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "DEC-003",
                    "decision",
                    "E-high-decision",
                    status="accepted",
                    metadata={"priority": "P1", "frontier": "now"},
                )
            },
        },
        {
            "event_id": "E-high-proposal",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "PROP-003",
                    "proposal",
                    "E-high-proposal",
                    status="active",
                    metadata={},
                )
            },
        },
        {
            "event_id": "E-high-option",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "OPT-003",
                    "option",
                    "E-high-option",
                    status="active",
                    metadata={},
                )
            },
        },
        _link_event(
            session_id,
            "E-high-proposal-decision-link",
            "L-PROP-003-addresses-DEC-003",
            "PROP-003",
            "addresses",
            "DEC-003",
        ),
        _link_event(
            session_id,
            "E-high-proposal-option-link",
            "L-PROP-003-recommends-OPT-003",
            "PROP-003",
            "recommends",
            "OPT-003",
        ),
        _link_event(
            session_id,
            "E-high-decision-proposal-link",
            "L-DEC-003-accepts-PROP-003",
            "DEC-003",
            "accepts",
            "PROP-003",
        ),
        {
            "event_id": "E-high-decision-link",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": {
                    "id": "L-DEC-003-depends-on-DEC-001",
                    "source_object_id": "DEC-003",
                    "relation": "depends_on",
                    "target_object_id": "DEC-001",
                    "rationale": "Accepted downstream decision depends on DEC-001.",
                    "created_at": "2026-04-28T00:00:00Z",
                    "source_event_ids": ["E-high-decision-link"],
                }
            },
        },
    ]


def _object(object_id: str, object_type: str, event_id: str, *, status: str, metadata: dict) -> dict:
    typed_metadata = metadata_for_object_type(object_type)
    typed_metadata.update(metadata)
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "High severity invalidation apply fixture object.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": typed_metadata,
    }


def _link_event(
    session_id: str,
    event_id: str,
    link_id: str,
    source_object_id: str,
    relation: str,
    target_object_id: str,
) -> dict:
    return {
        "event_id": event_id,
        "session_id": session_id,
        "event_type": "object_linked",
        "payload": {
            "link": {
                "id": link_id,
                "source_object_id": source_object_id,
                "relation": relation,
                "target_object_id": target_object_id,
                "rationale": "High severity invalidation apply fixture link.",
                "created_at": "2026-04-28T00:00:00Z",
                "source_event_ids": [event_id],
            }
        },
    }


def _open_session_id(ai_dir: Path) -> str:
    return sorted(path.stem for path in (ai_dir / "sessions").glob("*.json"))[0]


def _event_ids(specs: list[dict]) -> list[str]:
    return [spec["event_id"] for spec in specs]


def _event_types(specs: list[dict]) -> list[str]:
    return [spec["event_type"] for spec in specs]


def _event_sessions(specs: list[dict]) -> list[str]:
    return [spec["session_id"] for spec in specs]


if __name__ == "__main__":
    unittest.main()
