from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "decide_me.py"


class ImpactCliTests(unittest.TestCase):
    def test_show_impact_and_candidates_return_json_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))
            event_snapshot = _event_snapshot(ai_dir)
            project_state = (ai_dir / "project-state.json").read_text(encoding="utf-8")

            impact_result = _run_cli(
                "show-impact",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-privacy",
                "--change-kind",
                "changed",
                "--max-depth",
                "3",
            )
            impact = json.loads(impact_result.stdout)

            self.assertEqual("O-privacy", impact["root_object_id"])
            self.assertEqual("changed", impact["change_kind"])
            self.assertEqual(4, impact["summary"]["affected_count"])
            self.assertEqual("high", impact["summary"]["highest_severity"])
            self.assertEqual(
                ["D-auth", "A-implement-auth", "R-auth-revisit", "V-auth-flow"],
                [item["object_id"] for item in impact["affected_objects"]],
            )

            candidate_result = _run_cli(
                "show-invalidation-candidates",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-privacy",
                "--change-kind",
                "changed",
                "--max-depth",
                "3",
            )
            candidates = json.loads(candidate_result.stdout)

            self.assertEqual("O-privacy", candidates["root_object_id"])
            self.assertEqual(
                ["D-auth", "A-implement-auth", "V-auth-flow"],
                [candidate["target_object_id"] for candidate in candidates["candidates"]],
            )
            by_target = {candidate["target_object_id"]: candidate for candidate in candidates["candidates"]}
            self.assertEqual("review", by_target["D-auth"]["candidate_kind"])
            self.assertFalse(by_target["D-auth"]["requires_human_approval"])
            self.assertEqual("revise", by_target["A-implement-auth"]["candidate_kind"])
            self.assertEqual("revalidate", by_target["V-auth-flow"]["candidate_kind"])

            self.assertEqual(event_snapshot, _event_snapshot(ai_dir))
            self.assertEqual(project_state, (ai_dir / "project-state.json").read_text(encoding="utf-8"))

    def test_cli_flags_include_low_severity_and_invalidated_targets(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))

            default_candidates = json.loads(
                _run_cli(
                    "show-invalidation-candidates",
                    "--ai-dir",
                    str(ai_dir),
                    "--object-id",
                    "O-privacy",
                    "--change-kind",
                    "changed",
                    "--max-depth",
                    "3",
                ).stdout
            )
            low_candidates = json.loads(
                _run_cli(
                    "show-invalidation-candidates",
                    "--ai-dir",
                    str(ai_dir),
                    "--object-id",
                    "O-privacy",
                    "--change-kind",
                    "changed",
                    "--max-depth",
                    "3",
                    "--include-low-severity",
                ).stdout
            )

            self.assertNotIn(
                "R-auth-revisit",
                [candidate["target_object_id"] for candidate in default_candidates["candidates"]],
            )
            self.assertIn(
                "R-auth-revisit",
                [candidate["target_object_id"] for candidate in low_candidates["candidates"]],
            )

            default_impact = json.loads(
                _run_cli(
                    "show-impact",
                    "--ai-dir",
                    str(ai_dir),
                    "--object-id",
                    "O-privacy",
                    "--change-kind",
                    "changed",
                    "--max-depth",
                    "3",
                ).stdout
            )
            invalidated_impact = json.loads(
                _run_cli(
                    "show-impact",
                    "--ai-dir",
                    str(ai_dir),
                    "--object-id",
                    "O-privacy",
                    "--change-kind",
                    "changed",
                    "--max-depth",
                    "3",
                    "--include-invalidated",
                ).stdout
            )
            invalidated_candidates = json.loads(
                _run_cli(
                    "show-invalidation-candidates",
                    "--ai-dir",
                    str(ai_dir),
                    "--object-id",
                    "O-privacy",
                    "--change-kind",
                    "changed",
                    "--max-depth",
                    "3",
                    "--include-invalidated",
                ).stdout
            )

            self.assertNotIn(
                "A-invalidated-auth",
                [affected["object_id"] for affected in default_impact["affected_objects"]],
            )
            self.assertIn(
                "A-invalidated-auth",
                [affected["object_id"] for affected in invalidated_impact["affected_objects"]],
            )
            self.assertIn(
                "A-invalidated-auth",
                [candidate["target_object_id"] for candidate in invalidated_candidates["candidates"]],
            )

    def test_show_impact_reports_clear_cli_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))

            missing = _run_cli(
                "show-impact",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-missing",
                "--change-kind",
                "changed",
                check=False,
            )

            self.assertEqual(1, missing.returncode)
            self.assertIn("unknown object_id: O-missing", missing.stderr)

            invalid_kind = _run_cli(
                "show-impact",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-privacy",
                "--change-kind",
                "renamed",
                check=False,
            )

            self.assertNotEqual(0, invalid_kind.returncode)
            self.assertIn("invalid choice", invalid_kind.stderr)


def _run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"CLI failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def _runtime_with_stack(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Plan Phase 6-5.",
        current_milestone="Phase 6-5",
    )
    session = create_session(str(ai_dir), context="Decision stack CLI")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def _events(session_id: str) -> list[dict]:
    return [
        {
            "event_id": "E-constraint",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("O-privacy", "constraint", "E-constraint")},
        },
        {
            "event_id": "E-decision",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("D-auth", "decision", "E-decision", status="unresolved")},
        },
        {
            "event_id": "E-action",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("A-implement-auth", "action", "E-action")},
        },
        {
            "event_id": "E-verification",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("V-auth-flow", "verification", "E-verification")},
        },
        {
            "event_id": "E-revisit-trigger",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object("R-auth-revisit", "revisit_trigger", "E-revisit-trigger")},
        },
        {
            "event_id": "E-invalidated-action",
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(
                    "A-invalidated-auth",
                    "action",
                    "E-invalidated-action",
                    status="invalidated",
                )
            },
        },
        {
            "event_id": "E-link-constraint-decision",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-constraint-constrains-decision",
                    "O-privacy",
                    "constrains",
                    "D-auth",
                    "E-link-constraint-decision",
                )
            },
        },
        {
            "event_id": "E-link-action-decision",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-action-addresses-decision",
                    "A-implement-auth",
                    "addresses",
                    "D-auth",
                    "E-link-action-decision",
                )
            },
        },
        {
            "event_id": "E-link-decision-revisit-trigger",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-decision-revisits-trigger",
                    "D-auth",
                    "revisits",
                    "R-auth-revisit",
                    "E-link-decision-revisit-trigger",
                )
            },
        },
        {
            "event_id": "E-link-invalidated-action-decision",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-invalidated-action-addresses-decision",
                    "A-invalidated-auth",
                    "addresses",
                    "D-auth",
                    "E-link-invalidated-action-decision",
                )
            },
        },
        {
            "event_id": "E-link-verification-action",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-verification-requires-action",
                    "V-auth-flow",
                    "requires",
                    "A-implement-auth",
                    "E-link-verification-action",
                )
            },
        },
    ]


def _object(object_id: str, object_type: str, event_id: str, *, status: str = "active") -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Impact CLI integration object.",
        "status": status,
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": {},
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Impact CLI integration link.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


def _event_snapshot(ai_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(ai_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((ai_dir / "events").rglob("*.jsonl"))
    }


if __name__ == "__main__":
    unittest.main()
