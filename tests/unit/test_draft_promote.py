from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.draft_promote import DraftPromotionError, promote_draft_decision, promote_draft_set
from decide_me.draft_sets import DraftSetHeadMismatchError, create_draft_set
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, load_runtime, read_event_log, runtime_paths, validate_runtime
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftPromoteTests(unittest.TestCase):
    def test_promote_materializes_decision_proposal_question_and_risk_scaffold(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")
            before_count = len(read_event_log(runtime_paths(ai_dir)))

            result = promote_draft_decision(
                ai_dir,
                "DS-20260513-001",
                "DD-001",
                session_id=session_id,
            )

            self.assertEqual("promoted", result["status"])
            self.assertEqual("proposed", result["decision"]["status"])
            self.assertTrue(result["proposal"]["is_active"])
            self.assertEqual(["explicit"], result["proposal"]["object"]["metadata"]["acceptance_mode_allowed"])
            self.assertEqual("DS-20260513-001", result["decision"]["draft_origin"]["draft_set_id"])
            self.assertEqual("DD-001", result["decision"]["draft_origin"]["draft_decision_id"])

            events = read_event_log(runtime_paths(ai_dir))[before_count:]
            self.assertEqual(
                [
                    "object_recorded",
                    "object_recorded",
                    "object_linked",
                    "object_status_changed",
                    "object_recorded",
                    "object_recorded",
                    "object_linked",
                    "object_linked",
                    "session_question_asked",
                ],
                [event["event_type"] for event in events],
            )
            self.assertNotIn("draft_decision_promoted", {event["event_type"] for event in events})

            bundle = load_runtime(runtime_paths(ai_dir))
            session = bundle["sessions"][session_id]
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            risk_objects = [obj for obj in objects.values() if obj.get("type") == "risk"]
            self.assertEqual(result["proposal_id"], session["working_state"]["active_proposal_id"])
            self.assertEqual("medium", risk_objects[0]["metadata"]["risk_tier"])
            self.assertTrue(
                any(
                    link["source_object_id"] == risk_objects[0]["id"]
                    and link["relation"] == "challenges"
                    and link["target_object_id"] == result["decision_id"]
                    for link in bundle["project_state"]["links"]
                )
            )
            log_lines = _promotion_log_lines(ai_dir)
            self.assertEqual(1, len(log_lines))
            self.assertEqual([event["event_id"] for event in events], log_lines[0]["event_ids"])
            draft_set = json.loads((ai_dir / "draft-sets" / "DS-20260513-001" / "draft-set.json").read_text(encoding="utf-8"))
            self.assertEqual(["DD-001"], draft_set["promotion"]["promoted_decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_repromoting_same_draft_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")
            first = promote_draft_decision(ai_dir, "DS-20260513-001", "DD-001", session_id=session_id)
            events_after_first = read_event_log(runtime_paths(ai_dir))

            second = promote_draft_decision(ai_dir, "DS-20260513-001", "DD-001", session_id=session_id)

            self.assertEqual("already_promoted", second["status"])
            self.assertEqual(first["decision_id"], second["decision_id"])
            self.assertEqual(first["proposal_id"], second["proposal_id"])
            self.assertEqual([], second["event_ids"])
            self.assertEqual(events_after_first, read_event_log(runtime_paths(ai_dir)))
            self.assertEqual(1, len(_promotion_log_lines(ai_dir)))

    def test_stale_draft_is_rejected_by_default_and_can_be_overridden(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")
            create_session(str(ai_dir), context="Move project head")

            with self.assertRaisesRegex(DraftSetHeadMismatchError, "draft set is stale"):
                promote_draft_decision(ai_dir, "DS-20260513-001", "DD-001", session_id=session_id)

            result = promote_draft_decision(
                ai_dir,
                "DS-20260513-001",
                "DD-001",
                session_id=session_id,
                allow_stale=True,
            )

            self.assertTrue(result["decision"]["draft_origin"]["stale_promoted"])

    def test_bulk_promotion_rejects_explicit_high_risk_bulk_request(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _bootstrap_with_session(Path(tmp))
            payload = _draft_input()
            payload["promotion"] = {
                "promoted_decision_ids": [],
                "bulk_promotable_ids": ["DD-001"],
                "individual_review_required_ids": [],
            }
            create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

            with self.assertRaisesRegex(DraftPromotionError, "non-bulk-promotable"):
                promote_draft_set(
                    ai_dir,
                    "DS-20260513-001",
                    session_id=session_id,
                    only_bulk_promotable=True,
                )


def _bootstrap_with_session(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft promotion.",
        current_milestone="PR3",
    )
    session_id = create_session(str(ai_dir), context="Promote draft decision")["session"]["id"]
    return ai_dir, session_id


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
            "option": "Store drafts in the canonical event log.",
            "reason_not_recommended": "It would blur accepted and draft state.",
        }
    ]
    return deepcopy(payload)


def _promotion_log_lines(ai_dir: Path) -> list[dict]:
    path = ai_dir / "draft-sets" / "DS-20260513-001" / "promotion-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
