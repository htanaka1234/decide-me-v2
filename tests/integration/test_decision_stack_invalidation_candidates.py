from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.invalidation_candidates import generate_invalidation_candidates
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact, validate_runtime
from tests.helpers.typed_metadata import metadata_for_object_type


class DecisionStackInvalidationCandidatesIntegrationTests(unittest.TestCase):
    def test_candidates_are_generated_without_runtime_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan Phase 6-4.",
                current_milestone="Phase 6-4",
            )
            session = create_session(str(ai_dir), context="Decision stack invalidation candidates")
            session_id = session["session"]["id"]

            transact(ai_dir, lambda _bundle: _events(session_id))
            rebuilt = rebuild_and_persist(ai_dir)
            project_state = rebuilt["project_state"]
            original_project_state = deepcopy(project_state)
            event_files_before = sorted(path.as_posix() for path in (ai_dir / "events").rglob("*.jsonl"))

            self.assertEqual([], validate_runtime(ai_dir))

            report = generate_invalidation_candidates(project_state, "O-privacy", change_kind="changed")

            self.assertEqual(original_project_state, project_state)
            self.assertEqual(
                event_files_before,
                sorted(path.as_posix() for path in (ai_dir / "events").rglob("*.jsonl")),
            )
            self.assertEqual(
                original_project_state,
                json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8")),
            )
            self.assertEqual("O-privacy", report["root_object_id"])
            self.assertEqual(
                ["D-auth", "A-implement-auth", "V-auth-flow"],
                [candidate["target_object_id"] for candidate in report["candidates"]],
            )
            by_id = {candidate["target_object_id"]: candidate for candidate in report["candidates"]}
            self.assertEqual("review", by_id["D-auth"]["candidate_kind"])
            self.assertFalse(by_id["D-auth"]["requires_human_approval"])
            self.assertEqual("revise", by_id["A-implement-auth"]["candidate_kind"])
            self.assertEqual("revalidate", by_id["V-auth-flow"]["candidate_kind"])


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
        "body": "Invalidation candidates integration object.",
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
        "rationale": "Invalidation candidates integration link.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": [event_id],
    }


if __name__ == "__main__":
    unittest.main()
