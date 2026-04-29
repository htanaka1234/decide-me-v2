from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import close_session, create_session
from decide_me.planner import generate_plan
from decide_me.protocol import discover_decision, resolve_by_evidence
from decide_me.store import bootstrap_runtime, validate_runtime
from tests.helpers.impact_runtime import run_json_cli


class GateEnforcedPlanGenerationTests(unittest.TestCase):
    def test_unapproved_action_is_excluded_from_implementation_ready_actions_until_approved(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _build_closed_evidence_resolved_session(ai_dir)

            plan = generate_plan(str(ai_dir), [session_id])
            action = plan["action_plan"]["actions"][0]

            self.assertTrue(action["declared_implementation_ready"])
            self.assertFalse(action["implementation_ready"])
            self.assertEqual("needs_approval", action["safety_gate"]["gate_status"])
            self.assertEqual([], plan["action_plan"]["implementation_ready_actions"])
            self.assertEqual("conditional", plan["action_plan"]["readiness"])

            approval_session = create_session(str(ai_dir), context="Approve implementation action")["session"]["id"]
            run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                approval_session,
                "--object-id",
                action["id"],
                "--approved-by",
                "user",
                "--reason",
                "Accepted missing verification gap for current milestone.",
            )
            approved_plan = generate_plan(str(ai_dir), [session_id])

            self.assertEqual([action["id"]], [item["id"] for item in approved_plan["action_plan"]["implementation_ready_actions"]])
            self.assertEqual("passed", approved_plan["action_plan"]["actions"][0]["safety_gate"]["gate_status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_irreversible_action_metadata_requires_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _build_closed_evidence_resolved_session(ai_dir, reversibility="irreversible")

            plan = generate_plan(str(ai_dir), [session_id])
            action = plan["action_plan"]["actions"][0]

            self.assertTrue(action["declared_implementation_ready"])
            self.assertFalse(action["implementation_ready"])
            self.assertEqual("irreversible", action["safety_gate"]["reversibility"])
            self.assertIn("irreversible_change", action["safety_gate"]["approval_reasons"])
            self.assertEqual([], plan["action_plan"]["implementation_ready_actions"])
            self.assertEqual("conditional", plan["action_plan"]["readiness"])


def _build_closed_evidence_resolved_session(ai_dir: Path, *, reversibility: str = "reversible") -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Gate implementation-ready actions.",
        current_milestone="Phase 7",
    )
    session_id = create_session(str(ai_dir), context="Plan gate enforcement")["session"]["id"]
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": "D-code",
            "title": "Code change",
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "resolvable_by": "codebase",
            "reversibility": reversibility,
            "question": "What code change is needed?",
        },
    )
    resolution = resolve_by_evidence(
        str(ai_dir),
        session_id,
        decision_id="D-code",
        source="docs",
        summary="The code path is documented and ready to implement.",
        evidence=["docs/code.md"],
    )
    if resolution["status"] == "pending_approval":
        run_json_cli(
            "approve-safety-gate",
            "--ai-dir",
            str(ai_dir),
            "--session-id",
            session_id,
            "--object-id",
            "D-code",
            "--approved-by",
            "user",
            "--reason",
            "Approved irreversible evidence resolution for fixture setup.",
        )
        resolve_by_evidence(
            str(ai_dir),
            session_id,
            decision_id="D-code",
            source="docs",
            summary="The code path is documented and ready to implement.",
            evidence=["docs/code.md"],
        )
    close_session(str(ai_dir), session_id)
    return session_id


if __name__ == "__main__":
    unittest.main()
