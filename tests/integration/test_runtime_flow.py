from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.events import EVENT_TYPES
from decide_me.lifecycle import create_session
from decide_me.protocol import (
    accept_proposal,
    discover_decision,
    enrich_decision,
    issue_proposal,
    resolve_by_evidence,
)
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
                "addresses",
                links[f"L-{active_proposal['proposal_id']}-addresses-D-auth"]["relation"],
            )
            option_id = next(
                link["target_object_id"]
                for link in links.values()
                if link["source_object_id"] == active_proposal["proposal_id"]
                and link["relation"] == "recommends"
            )
            self.assertEqual("Use magic links.", objects[option_id]["title"])
            self.assertEqual(
                "accepts",
                links[f"L-D-auth-accepts-{active_proposal['proposal_id']}"]["relation"],
            )
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            persisted = json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["project_state"], persisted)

    def test_reuses_evidence_object_across_multiple_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reuse evidence objects.",
                current_milestone="Phase 5-3",
            )
            session_id = create_session(str(ai_dir), context="Evidence reuse")["session"]["id"]
            for decision_id, title in (
                ("D-auth", "Auth mode"),
                ("D-audit", "Audit sink"),
            ):
                discover_decision(
                    str(ai_dir),
                    session_id,
                    {
                        "id": decision_id,
                        "title": title,
                        "priority": "P0",
                        "frontier": "now",
                        "domain": "technical",
                        "question": f"Resolve {title}?",
                    },
                )
                resolve_by_evidence(
                    str(ai_dir),
                    session_id,
                    decision_id=decision_id,
                    source="docs",
                    summary="The architecture note resolves this.",
                    evidence_refs=["docs/architecture.md"],
                )

            self.assertEqual([], validate_runtime(ai_dir))
            rebuilt = rebuild_and_persist(ai_dir)
            evidence_objects = [
                obj
                for obj in rebuilt["project_state"]["objects"]
                if obj["type"] == "evidence" and obj["metadata"].get("ref") == "docs/architecture.md"
            ]
            self.assertEqual(1, len(evidence_objects))
            support_links = [
                link
                for link in rebuilt["project_state"]["links"]
                if link["relation"] == "supports" and link["source_object_id"] == evidence_objects[0]["id"]
            ]

            self.assertEqual({"D-auth", "D-audit"}, {link["target_object_id"] for link in support_links})

    def test_deleted_write_commands_are_not_exposed_by_cli(self) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "decide_me.py"
        help_result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertNotIn("classify-session", help_result.stdout)
        self.assertNotIn("link-session", help_result.stdout)
        self.assertNotIn("resolve-session-conflict", help_result.stdout)

        invalid_result = subprocess.run(
            [sys.executable, str(script), "classify-session", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, invalid_result.returncode)
        self.assertIn("invalid choice", invalid_result.stderr)


if __name__ == "__main__":
    unittest.main()
