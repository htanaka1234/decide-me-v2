from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.draft_promote import promote_draft_decision
from decide_me.draft_sets import create_draft_set
from decide_me.interview import handle_reply
from decide_me.lifecycle import create_session
from decide_me.safety_approval import approve_safety_gate
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths, validate_runtime
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftPromotionSafetyGateTests(unittest.TestCase):
    def test_explicit_only_promoted_draft_rejects_plain_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            create_draft_set(ai_dir, _low_risk_explicit_only_draft(), draft_set_id="DS-20260513-001")
            promoted = promote_draft_decision(ai_dir, "DS-20260513-001", "DD-001", session_id=session_id)

            with self.assertRaisesRegex(ValueError, "does not allow ok acceptance"):
                handle_reply(str(ai_dir), session_id, "OK", repo_root=tmp)

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("proposed", objects[promoted["decision_id"]]["status"])
            self.assertEqual("active", objects[promoted["proposal_id"]]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_high_risk_promoted_draft_uses_existing_safety_approval_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            create_draft_set(ai_dir, _high_risk_draft(), draft_set_id="DS-20260513-001")
            promoted = promote_draft_decision(ai_dir, "DS-20260513-001", "DD-001", session_id=session_id)

            with self.assertRaisesRegex(ValueError, "approve-safety-gate"):
                handle_reply(
                    str(ai_dir),
                    session_id,
                    f"Accept {promoted['proposal_id']}",
                    repo_root=tmp,
                )

            approval = approve_safety_gate(
                str(ai_dir),
                session_id,
                promoted["decision_id"],
                approved_by="reviewer",
                reason="Reviewed promoted high-risk draft.",
            )
            self.assertEqual("approved", approval["status"])
            accepted = handle_reply(
                str(ai_dir),
                session_id,
                f"Accept {promoted['proposal_id']}",
                repo_root=tmp,
            )

            self.assertEqual("accepted", accepted["status"])
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("accepted", objects[promoted["decision_id"]]["status"])
            self.assertEqual("accepted", objects[promoted["proposal_id"]]["status"])
            self.assertEqual([], validate_runtime(ai_dir))


def _bootstrap_with_session(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft promotion safety gate.",
        current_milestone="PR3",
    )
    session_id = create_session(str(ai_dir), context="Draft promotion safety")["session"]["id"]
    return ai_dir, session_id


def _base_draft() -> dict:
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
            "option": "Continue manual discovery.",
            "reason_not_recommended": "The draft already contains a reviewable recommendation.",
        }
    ]
    return deepcopy(payload)


def _low_risk_explicit_only_draft() -> dict:
    payload = _base_draft()
    draft = payload["draft_decisions"][0]
    draft["risk_tier"] = "low"
    draft["promotion_recipe"]["acceptance_mode_allowed"] = ["explicit"]
    return payload


def _high_risk_draft() -> dict:
    payload = _base_draft()
    draft = payload["draft_decisions"][0]
    draft["risk_tier"] = "high"
    draft["promotion_recipe"]["acceptance_mode_allowed"] = ["explicit"]
    return payload


if __name__ == "__main__":
    unittest.main()
