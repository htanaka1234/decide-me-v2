from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.classification import classify_session
from decide_me.exports import export_adr
from decide_me.events import utc_now
from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import close_session, create_session, list_sessions, show_session
from decide_me.planner import generate_plan
from decide_me.protocol import (
    accept_proposal,
    discover_decision,
    issue_proposal,
    resolve_by_evidence,
    update_classification,
)
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime


class RuntimeFlowTests(unittest.TestCase):
    def test_parallel_sessions_do_not_accept_stale_plain_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise stale proposal handling",
                current_milestone="MVP",
            )
            s1 = create_session(ai_dir, context="Auth thread")["session"]["id"]
            s2 = create_session(ai_dir, context="Audit thread")["session"]["id"]

            discover_decision(
                ai_dir,
                s1,
                {
                    "id": "D-001",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            discover_decision(
                ai_dir,
                s2,
                {
                    "id": "D-002",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should audit logs work?",
                },
            )

            proposal = issue_proposal(
                ai_dir,
                s1,
                decision_id="D-001",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            issue_proposal(
                ai_dir,
                s2,
                decision_id="D-002",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Cheaper for the milestone.",
                if_not="A separate sink becomes in scope now.",
            )
            accept_proposal(ai_dir, s2)

            with self.assertRaisesRegex(ValueError, "stale"):
                accept_proposal(ai_dir, s1)

            accepted = accept_proposal(ai_dir, s1, proposal_id=proposal["proposal_id"])
            self.assertEqual("accepted", accepted["status"])

            rebuild_and_persist(ai_dir)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_close_sessions_generate_plan_and_adr(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Generate an action plan",
                current_milestone="MVP",
            )

            s1 = create_session(ai_dir, context="Auth decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                s1,
                {
                    "id": "D-001",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "How should auth work?",
                },
            )
            update_classification(
                ai_dir,
                s1,
                domain="technical",
                abstraction_level="architecture",
                search_terms=["auth"],
            )
            resolve_by_evidence(
                ai_dir,
                s1,
                decision_id="D-001",
                source="codebase",
                summary="Use the existing magic-link flow.",
                evidence_refs=["app/auth.py"],
            )
            close_session(ai_dir, s1)

            s2 = create_session(ai_dir, context="Audit decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                s2,
                {
                    "id": "D-002",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "kind": "choice",
                    "question": "Where should audit logs land?",
                },
            )
            issue_proposal(
                ai_dir,
                s2,
                decision_id="D-002",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Lowest operational overhead.",
                if_not="A separate sink becomes in scope now.",
            )
            accept_proposal(ai_dir, s2)
            close_session(ai_dir, s2)

            plan = generate_plan(ai_dir, [s1, s2])
            self.assertEqual("action-plan", plan["status"])
            self.assertEqual("ready", plan["action_plan"]["readiness"])
            self.assertTrue(Path(plan["export_path"]).exists())

            adr_path = export_adr(ai_dir, "D-001")
            self.assertTrue(adr_path.exists())
            self.assertEqual([], validate_runtime(ai_dir))

    def test_classification_search_and_lazy_compatibility_backfill(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise taxonomy-aware search",
                current_milestone="MVP",
            )

            session = create_session(ai_dir, context="Authentication choices")
            session_id = session["session"]["id"]
            classification = classify_session(
                ai_dir,
                session_id,
                domain="technical",
                abstraction_level="architecture",
                candidate_terms=["email link"],
                source_refs=["latest_summary"],
            )
            self.assertEqual("technical", classification["classification"]["domain"])
            self.assertIn("latest_summary", classification["classification"]["source_refs"])

            listing = list_sessions(
                ai_dir,
                domains=["technical"],
                abstraction_levels=["architecture"],
                tag_terms=["email link"],
            )
            self.assertEqual(1, listing["count"])
            self.assertEqual(session_id, listing["sessions"][0]["session_id"])

            close_session(ai_dir, session_id)

            now = utc_now()

            def builder(bundle: dict[str, object]) -> list[dict[str, object]]:
                return [
                    {
                        "session_id": session_id,
                        "event_type": "taxonomy_extended",
                        "payload": {
                            "nodes": [
                                {
                                    "id": "tag:magic-links",
                                    "axis": "tag",
                                    "label": "magic links",
                                    "aliases": ["authentication"],
                                    "parent_id": None,
                                    "replaced_by": [],
                                    "status": "active",
                                    "created_at": now,
                                    "updated_at": now,
                                },
                                {
                                    "id": "tag:email-link",
                                    "axis": "tag",
                                    "label": "email link",
                                    "aliases": [],
                                    "parent_id": None,
                                    "replaced_by": ["tag:magic-links"],
                                    "status": "replaced",
                                    "created_at": bundle["taxonomy_state"]["nodes"][-1]["created_at"],
                                    "updated_at": now,
                                },
                            ]
                        },
                    }
                ]

            transact(ai_dir, builder)

            display = show_session(ai_dir, session_id)
            self.assertIn("tag:magic-links", display["session"]["classification"]["compatibility_tags"])
            self.assertIn("tag:magic-links", display["compatibility_tag_refs_added"])

            listing = list_sessions(ai_dir, tag_terms=["authentication"])
            self.assertEqual(1, listing["count"])
            self.assertGreaterEqual(len(listing["backfilled"]), 0)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_advance_session_resolves_evidence_then_handles_ok_reply(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "auth.py").write_text(
                "def login():\n    return 'magic link auth flow'\n",
                encoding="utf-8",
            )
            ai_dir = str(root / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Advance interview turns",
                current_milestone="MVP",
            )

            session_id = create_session(ai_dir, context="MVP decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-001",
                    "title": "Magic link auth",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "codebase",
                    "question": "Should the MVP use the existing magic-link flow?",
                    "context": "Use the current auth implementation if possible.",
                    "recommendation": {
                        "summary": "Use the existing magic-link flow.",
                        "rationale_short": "The repo already has it.",
                    },
                },
            )
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-002",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "recommendation": {
                        "summary": "Start with 30 days.",
                        "rationale_short": "It keeps the MVP scope small.",
                    },
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=root)
            self.assertEqual("question", turn["status"])
            self.assertEqual("D-002", turn["decision_id"])
            self.assertEqual(1, len(turn["auto_resolved"]))
            self.assertEqual("D-001", turn["auto_resolved"][0]["decision_id"])
            self.assertIn("app/auth.py", turn["auto_resolved"][0]["evidence_refs"])
            self.assertIn("Resolved by evidence: D-001", turn["message"])

            reply = handle_reply(ai_dir, session_id, "OK", repo_root=root)
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("complete", reply["next_turn"]["status"])
            self.assertIn("Accepted: D-002", reply["message"])
            self.assertIn("Next recommended action:", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_accepts_freeform_alternative_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Capture free-form answers",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-010",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "recommendation": {
                        "summary": "Start with 30 days.",
                        "rationale_short": "It keeps the MVP scope small.",
                    },
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=tmp)
            self.assertEqual("question", turn["status"])

            reply = handle_reply(
                ai_dir,
                session_id,
                "Use 90 days because enterprise customers will expect it.",
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(
                "Use 90 days because enterprise customers will expect it.",
                reply["decision"]["accepted_answer"]["summary"],
            )
            self.assertEqual("complete", reply["next_turn"]["status"])
            self.assertIn(
                "Accepted answer overrides the last recommendation.",
                reply["decision"]["notes"],
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_rejects_negative_only_reply(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject proposal with free-form no",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-011",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "recommendation": {
                        "summary": "Start with 30 days.",
                        "rationale_short": "It keeps the MVP scope small.",
                    },
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(ai_dir, session_id, "No", repo_root=tmp)
            self.assertEqual("rejected", reply["status"])
            self.assertIn("Rejected: D-011", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_accepts_affirming_freeform_phrase(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Accept affirming phrase",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-012",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "recommendation": {
                        "summary": "Start with 30 days.",
                        "rationale_short": "It keeps the MVP scope small.",
                    },
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(ai_dir, session_id, "Sounds good", repo_root=tmp)
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("Start with 30 days.", reply["decision"]["accepted_answer"]["summary"])
            self.assertEqual("explicit", reply["decision"]["accepted_answer"]["accepted_via"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_extracts_constraints_and_follow_up_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Extract constraints and follow-up decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-020",
                    "title": "Authentication mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "human",
                    "question": "Should the MVP use magic links?",
                    "context": "Choose the initial authentication mode.",
                    "recommendation": {
                        "summary": "Use magic links for the MVP.",
                        "rationale_short": "It keeps auth scope down.",
                    },
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(
                ai_dir,
                session_id,
                "Sounds good, but only for enterprise tenants, and we also need password reset before launch.",
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(
                "Use magic links for the MVP.",
                reply["decision"]["accepted_answer"]["summary"],
            )
            self.assertEqual(["only for enterprise tenants"], reply["captured_constraints"])
            self.assertEqual(1, len(reply["discovered_decisions"]))
            discovered = reply["discovered_decisions"][0]
            self.assertEqual("P0", discovered["priority"])
            self.assertEqual("now", discovered["frontier"])
            self.assertIn("Constraint: only for enterprise tenants", reply["decision"]["notes"])
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual(discovered["id"], reply["next_turn"]["decision_id"])
            self.assertIn("Captured constraints:", reply["message"])
            self.assertIn("Discovered decisions:", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_extracts_multiple_constraints_and_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Extract multiple constraints and follow-up decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-021",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "recommendation": {
                        "summary": "Start with 30 days.",
                        "rationale_short": "It keeps the MVP scope small.",
                    },
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(
                ai_dir,
                session_id,
                (
                    "Use 90 days, but only for enterprise tenants, and it must stay in the US, "
                    "and we also need S3 export before launch, and we need retention to be configurable later."
                ),
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("Use 90 days", reply["decision"]["accepted_answer"]["summary"])
            self.assertEqual(
                ["only for enterprise tenants", "it must stay in the US"],
                reply["captured_constraints"],
            )
            self.assertEqual(2, len(reply["discovered_decisions"]))
            priorities = {(item["priority"], item["frontier"]) for item in reply["discovered_decisions"]}
            self.assertIn(("P0", "now"), priorities)
            self.assertIn(("P2", "later"), priorities)
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
