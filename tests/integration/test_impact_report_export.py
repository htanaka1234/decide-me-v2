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


class ImpactReportExportTests(unittest.TestCase):
    def test_export_impact_report_writes_markdown_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))
            output = ai_dir / "exports" / "impact" / "O-privacy.md"
            event_snapshot = _event_snapshot(ai_dir)
            project_state = (ai_dir / "project-state.json").read_text(encoding="utf-8")

            result = _run_cli(
                "export-impact-report",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-privacy",
                "--change-kind",
                "changed",
                "--max-depth",
                "3",
                "--include-low-severity",
                "--include-invalidated",
                "--output",
                str(output),
            )
            payload = json.loads(result.stdout)
            report = output.read_text(encoding="utf-8")

            self.assertEqual(str(output), payload["path"])
            self.assertIn("# Impact Report: O-privacy", report)
            self.assertIn("## Summary", report)
            self.assertIn("- Change kind: changed", report)
            self.assertIn("- Generated at: ", report)
            self.assertIn("- Max depth: 3", report)
            self.assertIn("- Include low severity: true", report)
            self.assertIn("- Include invalidated: true", report)
            self.assertIn("- Affected objects: 3", report)
            self.assertIn("- Highest severity: high", report)
            self.assertIn("## Affected Objects", report)
            self.assertIn("| D-auth | decision | strategy | unresolved | high | decision_review_required |", report)
            self.assertIn("| A-implement-auth | action | execution | active | medium | action_rework_candidate |", report)
            self.assertIn("## Invalidation Candidates", report)
            self.assertIn("| D-auth | review | high | not required |", report)
            self.assertIn("| A-implement-auth | revise | medium | not required |", report)
            self.assertIn("## Paths", report)
            self.assertIn("O-privacy -> D-auth -> A-implement-auth -> V-auth-flow", report)
            self.assertIn("This report is read-only.", report)

            self.assertEqual(event_snapshot, _event_snapshot(ai_dir))
            self.assertEqual(project_state, (ai_dir / "project-state.json").read_text(encoding="utf-8"))

    def test_export_impact_report_rejects_runtime_state_output(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))
            output = ai_dir / "project-state.json"
            project_state = output.read_text(encoding="utf-8")

            result = _run_cli(
                "export-impact-report",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "O-privacy",
                "--change-kind",
                "changed",
                "--output",
                str(output),
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("impact report output must be inside ai-dir exports/impact/", result.stderr)
            self.assertEqual(project_state, output.read_text(encoding="utf-8"))
            self.assertFalse((ai_dir / "exports" / "impact").exists())


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
    session = create_session(str(ai_dir), context="Impact report export")
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
        "body": "Impact report export integration object.",
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
        "rationale": "Impact report export integration link.",
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
