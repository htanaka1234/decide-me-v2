from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.impact_analysis import analyze_impact
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime


class DecisionStackImpactAnalysisIntegrationTests(unittest.TestCase):
    def test_objective_and_constraint_changes_detect_downstream_stack_without_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 6-3.",
                current_milestone="Phase 6-3",
            )
            session = create_session(str(ai_dir), context="Decision stack impact analysis")
            session_id = session["session"]["id"]

            transact(ai_dir, lambda _bundle: _events(session_id))
            rebuilt = rebuild_and_persist(ai_dir)
            project_state = rebuilt["project_state"]
            original_project_state = deepcopy(project_state)
            event_files_before = sorted(path.as_posix() for path in (ai_dir / "events").rglob("*.jsonl"))

            self.assertEqual([], validate_runtime(ai_dir))

            constraint_report = analyze_impact(project_state, "O-privacy", change_kind="changed")
            objective_report = analyze_impact(project_state, "O-project-objective", change_kind="changed")

            self.assertEqual(original_project_state, project_state)
            self.assertEqual(
                event_files_before,
                sorted(path.as_posix() for path in (ai_dir / "events").rglob("*.jsonl")),
            )
            self.assertEqual(
                original_project_state,
                json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8")),
            )
            self.assertEqual(
                ["D-auth", "A-implement-auth", "V-auth-flow"],
                [item["object_id"] for item in constraint_report["affected_objects"]],
            )
            self.assertEqual(
                ["D-auth", "A-implement-auth", "V-auth-flow"],
                [item["object_id"] for item in objective_report["affected_objects"]],
            )
            by_id = {item["object_id"]: item for item in constraint_report["affected_objects"]}
            self.assertEqual("high", by_id["D-auth"]["severity"])
            self.assertEqual("action_rework_candidate", by_id["A-implement-auth"]["impact_kind"])
            self.assertEqual("verification_review_required", by_id["V-auth-flow"]["impact_kind"])


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
            "event_id": "E-link-decision-objective",
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {
                "link": _link(
                    "L-decision-depends-objective",
                    "D-auth",
                    "depends_on",
                    "O-project-objective",
                    "E-link-decision-objective",
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
        "body": "Impact analysis integration object.",
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
        "rationale": "Impact analysis integration link.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
