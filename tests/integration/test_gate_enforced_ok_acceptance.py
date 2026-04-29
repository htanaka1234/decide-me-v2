from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import create_session
from decide_me.protocol import discover_decision
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths, transact, validate_runtime
from tests.helpers.impact_runtime import run_json_cli
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


class GateEnforcedOkAcceptanceTests(unittest.TestCase):
    def test_plain_ok_cannot_accept_target_that_needs_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_decision(ai_dir, session_id)
            _attach_human_review_gate_inputs(ai_dir, session_id)
            advance_session(str(ai_dir), session_id, repo_root=tmp)

            with self.assertRaisesRegex(ValueError, "safety gate needs explicit approval"):
                handle_reply(str(ai_dir), session_id, "OK", repo_root=tmp)

            bundle = load_runtime(runtime_paths(ai_dir))
            self.assertEqual("proposed", {obj["id"]: obj for obj in bundle["project_state"]["objects"]}["D-risky"]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_explicit_accept_requires_dedicated_approval_for_human_review_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_decision(ai_dir, session_id)
            _attach_human_review_gate_inputs(ai_dir, session_id)
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)
            proposal_id = turn["proposal_id"]

            with self.assertRaisesRegex(ValueError, "approve-safety-gate"):
                handle_reply(str(ai_dir), session_id, f"Accept {proposal_id}", repo_root=tmp)

            run_json_cli(
                "approve-safety-gate",
                "--ai-dir",
                str(ai_dir),
                "--session-id",
                session_id,
                "--object-id",
                "D-risky",
                "--approved-by",
                "user",
                "--reason",
                "Reviewed high-risk decision.",
            )
            accepted = handle_reply(str(ai_dir), session_id, f"Accept {proposal_id}", repo_root=tmp)

            self.assertEqual("accepted", accepted["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_explicit_acceptance_threshold_records_inline_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _bootstrap_session(ai_dir)
            _discover_decision(ai_dir, session_id)
            _attach_explicit_acceptance_gate_inputs(ai_dir, session_id)
            turn = advance_session(str(ai_dir), session_id, repo_root=tmp)

            accepted = handle_reply(str(ai_dir), session_id, f"Accept {turn['proposal_id']}", repo_root=tmp)

            self.assertEqual("accepted", accepted["status"])
            bundle = load_runtime(runtime_paths(ai_dir))
            approvals = [
                obj
                for obj in bundle["project_state"]["objects"]
                if obj.get("type") == "artifact"
                and obj.get("metadata", {}).get("artifact_type") == "safety_gate_approval"
            ]
            self.assertEqual(1, len(approvals))
            self.assertEqual("explicit_acceptance", approvals[0]["metadata"]["approval_level"])
            self.assertEqual([], validate_runtime(ai_dir))


def _bootstrap_session(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Enforce safety gates on OK acceptance.",
        current_milestone="Phase 7",
    )
    return create_session(str(ai_dir), context="Gate enforcement")["session"]["id"]


def _discover_decision(ai_dir: Path, session_id: str) -> None:
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": "D-risky",
            "title": "Risky rollout",
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "question": "Should the risky rollout proceed?",
        },
    )


def _attach_human_review_gate_inputs(ai_dir: Path, session_id: str) -> None:
    transact(ai_dir, lambda _bundle: _gate_events(session_id, risk_metadata(risk_tier="high", approval_threshold="human_review")))


def _attach_explicit_acceptance_gate_inputs(ai_dir: Path, session_id: str) -> None:
    transact(ai_dir, lambda _bundle: _gate_events(session_id, risk_metadata(risk_tier="low", approval_threshold="explicit_acceptance")))


def _gate_events(session_id: str, risk: dict) -> list[dict]:
    return [
        {"event_id": f"E-evidence-{risk['approval_threshold']}", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("E-risky", "evidence", "active", evidence_metadata())}},
        {"event_id": f"E-risk-{risk['approval_threshold']}", "session_id": session_id, "event_type": "object_recorded", "payload": {"object": _object("R-risky", "risk", "open", risk)}},
        {"event_id": f"E-link-evidence-{risk['approval_threshold']}", "session_id": session_id, "event_type": "object_linked", "payload": {"link": _link("L-E-risky-supports-D-risky", "E-risky", "supports", "D-risky")}},
        {"event_id": f"E-link-risk-{risk['approval_threshold']}", "session_id": session_id, "event_type": "object_linked", "payload": {"link": _link("L-R-risky-constrains-D-risky", "R-risky", "constrains", "D-risky")}},
    ]


def _object(object_id: str, object_type: str, status: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Gate enforcement fixture.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-fixture"],
        "metadata": metadata,
    }


def _link(link_id: str, source: str, relation: str, target: str) -> dict:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Gate enforcement fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


if __name__ == "__main__":
    unittest.main()
