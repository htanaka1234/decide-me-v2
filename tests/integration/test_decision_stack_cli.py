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
from tests.helpers.typed_metadata import metadata_for_object_type


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "decide_me.py"
CLI_TIMEOUT_SECONDS = 30


class DecisionStackCliTests(unittest.TestCase):
    def test_show_decision_stack_returns_bounded_subgraph_json(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_stack(Path(tmp))

            result = _run_cli(
                "show-decision-stack",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "D-auth",
                "--upstream-depth",
                "1",
                "--downstream-depth",
                "2",
            )
            subgraph = json.loads(result.stdout)

            self.assertEqual("D-auth", subgraph["root_object_id"])
            self.assertEqual(
                ["A-implement-auth", "D-auth", "O-privacy", "V-auth-flow"],
                [node["object_id"] for node in subgraph["nodes"]],
            )
            self.assertEqual(
                [
                    "L-action-addresses-decision",
                    "L-constraint-constrains-decision",
                    "L-verification-requires-action",
                ],
                [edge["link_id"] for edge in subgraph["edges"]],
            )

            shallow_result = _run_cli(
                "show-decision-stack",
                "--ai-dir",
                str(ai_dir),
                "--object-id",
                "D-auth",
                "--upstream-depth",
                "0",
                "--downstream-depth",
                "1",
            )
            shallow = json.loads(shallow_result.stdout)

            self.assertEqual(
                ["A-implement-auth", "D-auth"],
                [node["object_id"] for node in shallow["nodes"]],
            )
            self.assertEqual(["L-action-addresses-decision"], [edge["link_id"] for edge in shallow["edges"]])


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
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
        "body": "Decision stack CLI integration object.",
        "status": status,
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata_for_object_type(object_type),
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Decision stack CLI integration link.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
