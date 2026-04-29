from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.interview import advance_session
from decide_me.lifecycle import close_session, create_session
from decide_me.protocol import discover_decision, resolve_by_evidence
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths, transact, validate_runtime
from tests.helpers.impact_runtime import event_hash_snapshot, runtime_state_snapshot, run_json_cli
from tests.helpers.typed_metadata import risk_metadata


class GateEnforcedEvidenceResolutionTests(unittest.TestCase):
    def test_high_risk_evidence_resolution_records_pending_then_resolves_after_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _build_session(Path(tmp))
            _discover_decision(ai_dir, session_id, "D-risky")
            _attach_risk(ai_dir, session_id, "D-risky", risk_metadata(risk_tier="high", approval_threshold="human_review"))

            pending = resolve_by_evidence(
                str(ai_dir),
                session_id,
                decision_id="D-risky",
                source="docs",
                summary="The docs contain the implementation answer.",
                evidence=["docs/risky.md"],
            )

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("pending_approval", pending["status"])
            self.assertEqual("needs_approval", pending["safety_gate"]["gate_status"])
            self.assertEqual("unresolved", objects["D-risky"]["status"])
            self.assertTrue(any(obj["type"] == "evidence" for obj in objects.values()))
            self.assertEqual([], validate_runtime(ai_dir))

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
                "Reviewed high-risk evidence resolution.",
            )
            resolved = resolve_by_evidence(
                str(ai_dir),
                session_id,
                decision_id="D-risky",
                source="docs",
                summary="The docs contain the implementation answer.",
                evidence=["docs/risky.md"],
            )

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("resolved", resolved["status"])
            self.assertEqual("passed", resolved["safety_gate"]["gate_status"])
            self.assertEqual("resolved-by-evidence", objects["D-risky"]["status"])
            self.assertEqual(1, len(resolved["event_ids"]))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_blocked_evidence_resolution_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir, session_id = _build_session(Path(tmp))
            _discover_decision(ai_dir, session_id, "D-critical")
            _attach_risk(ai_dir, session_id, "D-critical", risk_metadata(risk_tier="critical"))
            before_events = event_hash_snapshot(ai_dir)
            before_runtime = runtime_state_snapshot(ai_dir)

            with self.assertRaisesRegex(ValueError, "gate_status=blocked"):
                resolve_by_evidence(
                    str(ai_dir),
                    session_id,
                    decision_id="D-critical",
                    source="docs",
                    summary="The docs contain the implementation answer.",
                    evidence=["docs/critical.md"],
                )

            self.assertEqual(before_events, event_hash_snapshot(ai_dir))
            self.assertEqual(before_runtime, runtime_state_snapshot(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_advance_session_stops_when_auto_evidence_resolution_needs_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Stop unsafe auto evidence resolution.",
                current_milestone="Phase 7",
            )
            source_session = create_session(str(ai_dir), context="Source evidence")["session"]["id"]
            _discover_decision(ai_dir, source_session, "D-source", title="Shared docs decision")
            resolve_by_evidence(
                str(ai_dir),
                source_session,
                decision_id="D-source",
                source="docs",
                summary="Prior docs resolve the shared decision.",
                evidence=["docs/source.md"],
            )
            close_session(str(ai_dir), source_session)

            target_session = create_session(str(ai_dir), context="Target evidence")["session"]["id"]
            _discover_decision(ai_dir, target_session, "D-target", title="Shared docs decision")
            _attach_risk(ai_dir, target_session, "D-target", risk_metadata(risk_tier="high", approval_threshold="human_review"))

            turn = advance_session(str(ai_dir), target_session, repo_root=tmp)

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            self.assertEqual("pending_approval", turn["status"])
            self.assertEqual("D-target", turn["decision_id"])
            self.assertEqual("unresolved", objects["D-target"]["status"])
            self.assertIn("safety approval is required", turn["message"])
            self.assertEqual([], validate_runtime(ai_dir))


def _build_session(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Gate evidence resolution.",
        current_milestone="Phase 7",
    )
    return ai_dir, create_session(str(ai_dir), context="Evidence resolution")["session"]["id"]


def _discover_decision(ai_dir: Path, session_id: str, decision_id: str, *, title: str = "Risky evidence decision") -> None:
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": decision_id,
            "title": title,
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "resolvable_by": "docs",
            "question": "Can evidence resolve this decision?",
        },
    )


def _attach_risk(ai_dir: Path, session_id: str, decision_id: str, metadata: dict) -> None:
    risk_id = f"R-{decision_id}"
    transact(
        ai_dir,
        lambda _bundle: [
            {
                "event_id": f"E-{risk_id}",
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {"object": _object(risk_id, "risk", "open", metadata)},
            },
            {
                "event_id": f"E-L-{risk_id}",
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {"link": _link(f"L-{risk_id}-constrains-{decision_id}", risk_id, "constrains", decision_id)},
            },
        ],
    )


def _object(object_id: str, object_type: str, status: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Evidence resolution fixture.",
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
        "rationale": "Evidence resolution fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": ["E-link"],
    }


if __name__ == "__main__":
    unittest.main()
