from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.lifecycle import close_session, create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.typed_metadata import (
    assumption_metadata,
    evidence_metadata,
    revisit_trigger_metadata,
    risk_metadata,
    verification_metadata,
)


NOW = "2026-04-29T00:00:00Z"
PAST = "2026-04-28T00:00:00Z"


def build_document_runtime(tmp: Path) -> tuple[Path, str]:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Build a generic document compiler.",
        current_milestone="Phase 8",
    )
    session = create_session(str(ai_dir), context="Phase 8 document compiler")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    close_session(str(ai_dir), session_id)
    return ai_dir, session_id


def build_two_session_document_runtime(tmp: Path) -> tuple[Path, str, str]:
    ai_dir, first_session_id = build_document_runtime(tmp)
    session = create_session(str(ai_dir), context="Second Phase 8 document compiler session")
    second_session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _second_session_events(second_session_id))
    rebuild_and_persist(ai_dir)
    close_session(str(ai_dir), second_session_id)
    return ai_dir, first_session_id, second_session_id


def document_events(session_id: str) -> list[dict[str, Any]]:
    return _events(session_id)


def _second_session_events(session_id: str) -> list[dict[str, Any]]:
    object_specs = [
        ("E2-objective", "OBJ-002", "objective", "active", "Second session objective.", {}),
        ("E2-decision", "DEC-002", "decision", "accepted", "Use a second document model.", {"priority": "P1", "frontier": "later"}),
        ("E2-proposal", "PRO-002", "proposal", "accepted", "Second proposal.", {}),
        ("E2-option", "OPT-002", "option", "active", "Second option.", {}),
    ]
    link_specs = [
        ("E2-link-proposal-decision", "L-PRO-002-addresses-DEC-002", "PRO-002", "addresses", "DEC-002"),
        ("E2-link-proposal-option", "L-PRO-002-recommends-OPT-002", "PRO-002", "recommends", "OPT-002"),
        ("E2-link-decision-proposal", "L-DEC-002-accepts-PRO-002", "DEC-002", "accepts", "PRO-002"),
        ("E2-link-objective-decision", "L-OBJ-002-constrains-DEC-002", "OBJ-002", "constrains", "DEC-002"),
    ]
    return [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(object_id, object_type, status, body, event_id, metadata),
            },
        }
        for event_id, object_id, object_type, status, body, metadata in object_specs
    ] + [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {"link": _link(link_id, source, relation, target, event_id)},
        }
        for event_id, link_id, source, relation, target in link_specs
    ]


def _events(session_id: str) -> list[dict[str, Any]]:
    object_specs = [
        ("E-objective", "OBJ-001", "objective", "active", "Document compiler objective.", {}),
        ("E-criterion", "CRI-001", "criterion", "active", "Deterministic output.", {}),
        ("E-constraint", "CON-001", "constraint", "active", "Exports remain derived.", {}),
        (
            "E-assumption",
            "ASM-001",
            "assumption",
            "active",
            "Projection state is current.",
            assumption_metadata(
                statement="Projection state is current.",
                expires_at=PAST,
                owner="maintainer",
            ),
        ),
        (
            "E-evidence-current",
            "EVI-001",
            "evidence",
            "active",
            "Tests cover the document compiler.",
            evidence_metadata(
                source="tests",
                source_ref="tests/test_documents.py",
                summary="Tests cover the document compiler.",
            ),
        ),
        (
            "E-evidence-stale",
            "EVI-002",
            "evidence",
            "active",
            "Old notes are stale.",
            evidence_metadata(
                source="docs",
                source_ref="docs/old.md",
                summary="Old notes are stale.",
                valid_until=PAST,
            ),
        ),
        (
            "E-risk",
            "RSK-001",
            "risk",
            "open",
            "Human notes could be overwritten.",
            risk_metadata(
                statement="Human notes could be overwritten.",
                risk_tier="medium",
                approval_threshold="explicit_acceptance",
                mitigation_object_ids=["ACT-001"],
            ),
        ),
        (
            "E-risk-invalidated",
            "RSK-002",
            "risk",
            "invalidated",
            "Superseded document risk.",
            risk_metadata(
                statement="Superseded document risk.",
                risk_tier="low",
                approval_threshold="none",
            ),
        ),
        (
            "E-decision",
            "DEC-001",
            "decision",
            "accepted",
            "Use a generic document model.",
            {"priority": "P0", "frontier": "now", "domain": "technical", "reversibility": "reversible"},
        ),
        ("E-proposal", "PRO-001", "proposal", "accepted", "Use DocumentModel.", {}),
        ("E-option", "OPT-001", "option", "active", "Generic DocumentModel pipeline.", {}),
        (
            "E-action",
            "ACT-001",
            "action",
            "active",
            "Implement export-document.",
            {
                "decision_id": "DEC-001",
                "action_type": "execution",
                "responsibility": "runtime",
                "priority": "P0",
                "implementation_ready": True,
                "required_inputs": ["DocumentModel contract", "DEC-001"],
                "outputs": ["export-document command"],
                "source_decision_refs": ["DEC-001"],
                "next_step": "Ship the compiler.",
            },
        ),
        (
            "E-action-gap",
            "ACT-002",
            "action",
            "completed",
            "Add release checks.",
            {"responsibility": "qa", "priority": "P1"},
        ),
        (
            "E-verification",
            "VER-001",
            "verification",
            "active",
            "Renderer test passes.",
            verification_metadata(result="pass"),
        ),
        (
            "E-revisit",
            "REV-001",
            "revisit_trigger",
            "active",
            "Revisit after Phase 8.",
            revisit_trigger_metadata(due_at=PAST, target_object_ids=["DEC-001"]),
        ),
    ]
    link_specs = [
        ("E-link-proposal-decision", "L-PRO-001-addresses-DEC-001", "PRO-001", "addresses", "DEC-001"),
        ("E-link-proposal-option", "L-PRO-001-recommends-OPT-001", "PRO-001", "recommends", "OPT-001"),
        ("E-link-decision-proposal", "L-DEC-001-accepts-PRO-001", "DEC-001", "accepts", "PRO-001"),
        ("E-link-evidence-decision", "L-EVI-001-supports-DEC-001", "EVI-001", "supports", "DEC-001"),
        ("E-link-evidence-action", "L-EVI-001-supports-ACT-001", "EVI-001", "supports", "ACT-001"),
        ("E-link-stale-decision", "L-EVI-002-supports-DEC-001", "EVI-002", "supports", "DEC-001"),
        ("E-link-assumption-decision", "L-ASM-001-constrains-DEC-001", "ASM-001", "constrains", "DEC-001"),
        ("E-link-risk-decision", "L-RSK-001-challenges-DEC-001", "RSK-001", "challenges", "DEC-001"),
        ("E-link-evidence-risk", "L-EVI-001-supports-RSK-001", "EVI-001", "supports", "RSK-001"),
        ("E-link-invalidated-risk-decision", "L-RSK-002-challenges-DEC-001", "RSK-002", "challenges", "DEC-001"),
        ("E-link-action-risk", "L-ACT-001-mitigates-RSK-001", "ACT-001", "mitigates", "RSK-001"),
        ("E-link-action-decision", "L-ACT-001-addresses-DEC-001", "ACT-001", "addresses", "DEC-001"),
        ("E-link-verification-action", "L-VER-001-verifies-ACT-001", "VER-001", "verifies", "ACT-001"),
        ("E-link-revisit-decision", "L-REV-001-revisits-DEC-001", "REV-001", "revisits", "DEC-001"),
        ("E-link-criterion-option", "L-CRI-001-supports-OPT-001", "CRI-001", "supports", "OPT-001"),
        ("E-link-constraint-option", "L-CON-001-constrains-OPT-001", "CON-001", "constrains", "OPT-001"),
    ]
    return [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {
                "object": _object(object_id, object_type, status, body, event_id, metadata),
            },
        }
        for event_id, object_id, object_type, status, body, metadata in object_specs
    ] + [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_linked",
            "payload": {"link": _link(link_id, source, relation, target, event_id)},
        }
        for event_id, link_id, source, relation, target in link_specs
    ]


def _object(
    object_id: str,
    object_type: str,
    status: str,
    body: str,
    event_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": body,
        "status": status,
        "created_at": NOW,
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata,
    }


def _link(link_id: str, source: str, relation: str, target: str, event_id: str) -> dict[str, Any]:
    return {
        "id": link_id,
        "source_object_id": source,
        "relation": relation,
        "target_object_id": target,
        "rationale": "Document compiler fixture link.",
        "created_at": NOW,
        "source_event_ids": [event_id],
    }
