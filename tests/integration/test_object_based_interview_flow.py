from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import create_session
from decide_me.protocol import discover_decision, resolve_by_evidence
from decide_me.store import (
    bootstrap_runtime,
    load_runtime,
    rebuild_and_persist,
    runtime_paths,
    validate_runtime,
)


class ObjectBasedInterviewFlowTests(unittest.TestCase):
    def test_free_form_answer_creates_user_proposal_constraint_and_follow_up_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should users sign in?",
                },
            )
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)
            original_proposal_id = turn["proposal_id"]

            reply = "Use SSO only if legal signs off, and we also need audit export before launch."
            result = handle_reply(str(ai_dir), session_id, reply, repo_root=tmp)

            self.assertEqual("accepted", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            user_proposals = [
                obj
                for obj in objects.values()
                if obj["type"] == "proposal"
                and obj["metadata"].get("author") == "user"
                and obj["status"] == "accepted"
            ]

            self.assertEqual("rejected", objects[original_proposal_id]["status"])
            self.assertEqual("accepted", objects["D-auth"]["status"])
            self.assertEqual(1, len(user_proposals))
            user_proposal_id = user_proposals[0]["id"]
            self.assertTrue(
                any(
                    link["source_object_id"] == "D-auth"
                    and link["relation"] == "accepts"
                    and link["target_object_id"] == user_proposal_id
                    for link in links
                )
            )
            self.assertTrue(
                any(
                    link["source_object_id"] == user_proposal_id
                    and link["relation"] == "addresses"
                    and link["target_object_id"] == "D-auth"
                    for link in links
                )
            )
            recommended_option_ids = [
                link["target_object_id"]
                for link in links
                if link["source_object_id"] == user_proposal_id and link["relation"] == "recommends"
            ]
            self.assertEqual(["Use SSO"], [objects[object_id]["title"] for object_id in recommended_option_ids])
            self.assertTrue(
                any(
                    obj["type"] == "constraint"
                    and obj["title"] == "only if legal signs off"
                    for obj in objects.values()
                )
            )
            constraint_ids = [
                obj["id"]
                for obj in objects.values()
                if obj["type"] == "constraint" and obj["title"] == "only if legal signs off"
            ]
            self.assertTrue(
                any(
                    link["source_object_id"] in constraint_ids
                    and link["relation"] == "addresses"
                    and link["target_object_id"] == "D-auth"
                    for link in links
                )
            )
            self.assertTrue(
                any(
                    obj["type"] == "decision"
                    and obj["id"] != "D-auth"
                    and "audit export" in obj["title"].casefold()
                    for obj in objects.values()
                )
            )

            rebuilt = rebuild_and_persist(ai_dir)
            rebuilt_objects = {obj["id"]: obj for obj in rebuilt["project_state"]["objects"]}
            self.assertEqual("accepted", rebuilt_objects["D-auth"]["status"])
            self.assertEqual("accepted", rebuilt_objects[user_proposal_id]["status"])

    def test_evidence_resolution_uses_evidence_object_and_supports_link(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-docs",
                    "title": "Docs source",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Which docs source should drive implementation?",
                },
            )

            resolve_by_evidence(
                str(ai_dir),
                session_id,
                decision_id="D-docs",
                source="docs",
                summary="The architecture note is authoritative.",
                evidence_refs=["docs/architecture.md"],
            )

            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            evidence_ids = [
                obj["id"]
                for obj in objects.values()
                if obj["type"] == "evidence" and obj["metadata"].get("ref") == "docs/architecture.md"
            ]

            self.assertEqual("resolved-by-evidence", objects["D-docs"]["status"])
            self.assertEqual(1, len(evidence_ids))
            self.assertTrue(
                any(
                    link["source_object_id"] == evidence_ids[0]
                    and link["relation"] == "supports"
                    and link["target_object_id"] == "D-docs"
                    for link in links
                )
            )


def _bootstrap_session(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise Phase 5-4 object interview flow.",
        current_milestone="Phase 5-4",
    )
    return create_session(str(ai_dir), context="Object interview")["session"]["id"]


if __name__ == "__main__":
    unittest.main()
