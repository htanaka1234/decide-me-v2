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
    def test_domain_pack_sessions_seed_initial_decision_and_question(self) -> None:
        cases = (
            (
                "research",
                "research_question",
                "What research question should this plan answer?",
                "data",
            ),
            (
                "procurement",
                "requirement_definition",
                "What requirements must this procurement decision satisfy?",
                "ops",
            ),
            (
                "software",
                "architecture_choice",
                "What architecture choice should guide this implementation?",
                "technical",
            ),
        )
        for pack_id, decision_type, question, core_domain in cases:
            with self.subTest(pack_id=pack_id):
                with TemporaryDirectory() as tmp:
                    ai_dir = Path(tmp) / ".ai" / "decide-me"
                    _bootstrap_runtime(ai_dir)
                    session = create_session(
                        str(ai_dir),
                        context=f"Exercise {pack_id} pack.",
                        domain_pack_id=pack_id,
                    )

                    turn = advance_session(str(ai_dir), session["session"]["id"], repo_root=tmp)

                    self.assertEqual("question", turn["status"])
                    self.assertIn(question, turn["message"])
                    self.assertEqual(decision_type, turn["decision"]["domain_decision_type"])
                    self.assertEqual(pack_id, turn["decision"]["domain_pack_id"])
                    self.assertEqual(core_domain, turn["decision"]["domain"])
                    self.assertTrue(turn["decision"]["domain_criteria"])

    def test_generic_session_without_related_decisions_remains_unbound(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            _bootstrap_runtime(ai_dir)
            session = create_session(str(ai_dir), context="General planning note", domain_pack_id="generic")

            turn = advance_session(str(ai_dir), session["session"]["id"], repo_root=tmp)

        self.assertEqual("unbound", turn["status"])

    def test_software_session_manual_decision_flow_preserves_question_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            _bootstrap_runtime(ai_dir)
            session_id = create_session(str(ai_dir), context="Auth thread", domain_pack_id="software")["session"]["id"]
            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "question": "How should users sign in?",
                },
            )

            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)

        self.assertEqual("question", turn["status"])
        self.assertEqual("D-auth", turn["decision_id"])
        self.assertEqual("software", turn["decision"]["domain_pack_id"])
        self.assertEqual("auth_strategy", turn["decision"]["domain_decision_type"])
        self.assertIn("Question:", turn["message"])

    def test_domain_pack_follow_up_decision_gets_inferred_pack_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            _bootstrap_runtime(ai_dir)
            session = create_session(
                str(ai_dir),
                context="Plan a cohort study.",
                domain_pack_id="research",
            )
            turn = advance_session(str(ai_dir), session["session"]["id"], repo_root=tmp)

            result = handle_reply(
                str(ai_dir),
                session["session"]["id"],
                "Use a retrospective cohort study, and we also need missing data strategy before launch.",
                repo_root=tmp,
            )

            self.assertEqual("accepted", result["status"])
            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            decisions = [
                obj
                for obj in bundle["project_state"]["objects"]
                if obj["type"] == "decision" and obj["id"] != turn["decision_id"]
            ]
            self.assertTrue(
                any(
                    decision["metadata"].get("domain_pack_id") == "research"
                    and decision["metadata"].get("domain_decision_type") == "missing_data_strategy"
                    and decision["metadata"].get("domain_criteria")
                    for decision in decisions
                )
            )

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
                evidence=["docs/architecture.md"],
            )

            self.assertEqual([], validate_runtime(ai_dir))
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            evidence_ids = [
                obj["id"]
                for obj in objects.values()
                if obj["type"] == "evidence" and obj["metadata"].get("source_ref") == "docs/architecture.md"
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
    _bootstrap_runtime(ai_dir)
    return create_session(str(ai_dir), context="Object interview")["session"]["id"]


def _bootstrap_runtime(ai_dir: Path) -> None:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise Phase 5-4 object interview flow.",
        current_milestone="Phase 5-4",
    )


if __name__ == "__main__":
    unittest.main()
