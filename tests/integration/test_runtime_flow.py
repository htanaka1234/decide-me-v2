from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.classification import classify_session
from decide_me.events import EVENT_TYPES
from decide_me.lifecycle import create_session
from decide_me.protocol import (
    accept_proposal,
    discover_decision,
    enrich_decision,
    issue_proposal,
    update_classification,
)
from decide_me.session_graph import link_session, resolve_session_conflict
from decide_me.store import (
    bootstrap_runtime,
    load_runtime,
    read_event_log,
    rebuild_and_persist,
    runtime_paths,
    validate_runtime,
)


class RuntimeFlowTests(unittest.TestCase):
    def test_decision_workflow_emits_only_domain_neutral_events(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise Phase 5-3 runtime flow.",
                current_milestone="Phase 5-3",
            )
            session_id = create_session(str(ai_dir), context="Auth thread")["session"]["id"]

            discover_decision(
                str(ai_dir),
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            enrich_decision(
                str(ai_dir),
                session_id,
                decision_id="D-auth",
                context_append="The MVP needs low-friction authentication.",
                agent_relevant=True,
            )
            active_proposal = issue_proposal(
                str(ai_dir),
                session_id,
                decision_id="D-auth",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="This avoids password reset scope.",
                if_not="Password auth expands the initial milestone.",
            )
            accept_proposal(str(ai_dir), session_id)

            paths = runtime_paths(ai_dir)
            events = read_event_log(paths)
            event_types = [event["event_type"] for event in events]

            self.assertTrue(set(event_types).issubset(EVENT_TYPES))
            self.assertIn("object_recorded", event_types)
            self.assertIn("object_updated", event_types)
            self.assertIn("object_status_changed", event_types)
            self.assertIn("object_linked", event_types)
            self.assertIn("session_question_asked", event_types)
            self.assertIn("session_answer_recorded", event_types)

            bundle = load_runtime(paths)
            objects = {item["id"]: item for item in bundle["project_state"]["objects"]}
            links = {item["id"]: item for item in bundle["project_state"]["links"]}

            self.assertEqual("accepted", objects["D-auth"]["status"])
            self.assertEqual("accepted", objects[active_proposal["proposal_id"]]["status"])
            self.assertEqual(
                "Use magic links.",
                objects["D-auth"]["metadata"]["accepted_answer"]["summary"],
            )
            self.assertEqual(
                "recommends",
                links[f"L-{active_proposal['proposal_id']}-recommends-D-auth"]["relation"],
            )
            self.assertEqual(
                "accepts",
                links[f"L-D-auth-accepts-{active_proposal['proposal_id']}"]["relation"],
            )
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            persisted = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["project_state"], persisted)

    def test_deleted_source_of_truth_commands_hard_fail(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject deleted event sources.",
                current_milestone="Phase 5-3",
            )
            parent_id = create_session(str(ai_dir), context="Parent")["session"]["id"]
            child_id = create_session(str(ai_dir), context="Child")["session"]["id"]

            with self.assertRaisesRegex(ValueError, "unsupported"):
                classify_session(
                    str(ai_dir),
                    parent_id,
                    candidate_terms=["runtime"],
                    source_refs=["accepted_decisions"],
                )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                update_classification(
                    str(ai_dir),
                    parent_id,
                    domain="technical",
                    abstraction_level="implementation",
                )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                link_session(
                    str(ai_dir),
                    parent_session_id=parent_id,
                    child_session_id=child_id,
                    relationship="refines",
                    reason="Deleted source event.",
                )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                resolve_session_conflict(
                    str(ai_dir),
                    conflict_id="C-demo",
                    winning_session_id=parent_id,
                    rejected_session_ids=[child_id],
                    reason="Deleted source event.",
                )

            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
