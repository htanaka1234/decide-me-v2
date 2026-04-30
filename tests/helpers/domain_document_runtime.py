from __future__ import annotations

from pathlib import Path
from typing import Any

from decide_me.domains import DomainRegistry, domain_pack_digest, load_builtin_packs
from decide_me.lifecycle import close_session, create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact
from tests.helpers.document_runtime import NOW
from tests.helpers.typed_metadata import evidence_metadata, risk_metadata


def build_domain_document_runtime(
    tmp: Path,
    pack_id: str,
    *,
    ai_dir: Path | None = None,
) -> tuple[Path, str]:
    target_ai_dir = ai_dir or tmp / ".ai" / "decide-me"
    if ai_dir is None:
        bootstrap_runtime(
            target_ai_dir,
            project_name="Demo",
            objective="Build a domain pack document profile.",
            current_milestone="Phase 9",
        )
    session = create_session(str(target_ai_dir), context=f"{pack_id} document profile", domain_pack_id=pack_id)
    session_id = session["session"]["id"]
    transact(target_ai_dir, lambda _bundle: _session_events(pack_id, session_id))
    rebuild_and_persist(target_ai_dir)
    close_session(str(target_ai_dir), session_id)
    return target_ai_dir, session_id


def _session_events(pack_id: str, session_id: str) -> list[dict[str, Any]]:
    return [_with_session_event_id(event, session_id) for event in _events(pack_id, session_id)]


def _events(pack_id: str, session_id: str) -> list[dict[str, Any]]:
    if pack_id == "research":
        return _research_events(session_id)
    if pack_id == "procurement":
        return _procurement_events(session_id)
    raise ValueError(f"unsupported domain document fixture pack: {pack_id}")


def _with_session_event_id(event: dict[str, Any], session_id: str) -> dict[str, Any]:
    old_event_id = event["event_id"]
    new_event_id = f"{old_event_id}-{session_id}"
    event["event_id"] = new_event_id
    payload = event.get("payload", {})
    if event.get("event_type") == "object_recorded":
        payload["object"]["source_event_ids"] = [new_event_id]
    elif event.get("event_type") == "object_linked":
        payload["link"]["source_event_ids"] = [new_event_id]
    return event


def _research_events(session_id: str) -> list[dict[str, Any]]:
    decision_metadata = _decision_metadata("research", "primary_endpoint")
    evidence = {
        **evidence_metadata(
            source="docs",
            source_ref="docs/protocol.md",
            summary="Protocol draft defines the study objective.",
        ),
        **_pack_identity("research"),
        "evidence_requirement_id": "protocol_or_project_brief",
        "domain_evidence_type": "protocol",
    }
    risk = {
        **risk_metadata(
            statement="Endpoint ambiguity can invalidate analysis planning.",
            risk_tier="high",
            approval_threshold="human_review",
        ),
        **_pack_identity("research"),
        "domain_risk_type": "unclear_endpoint",
    }
    return [
        _object_event(session_id, "E-OBJ-research", "OBJ-research", "objective", "active", "Define the research plan.", {}),
        _object_event(session_id, "E-DEC-primary", "DEC-primary", "decision", "accepted", "Choose the primary endpoint.", decision_metadata),
        _object_event(session_id, "E-PRO-primary", "PRO-primary", "proposal", "accepted", "Use all-cause readmission as the primary endpoint.", {}),
        _object_event(session_id, "E-OPT-primary", "OPT-primary", "option", "active", "All-cause readmission.", {}),
        _object_event(session_id, "E-EVI-protocol", "EVI-protocol", "evidence", "active", "Protocol draft.", evidence),
        _object_event(session_id, "E-RSK-endpoint", "RSK-endpoint", "risk", "open", "Endpoint ambiguity.", risk),
        _link_event(session_id, "E-L-OBJ-DEC", "L-OBJ-research-constrains-DEC-primary", "OBJ-research", "constrains", "DEC-primary"),
        _link_event(session_id, "E-L-PRO-DEC", "L-PRO-primary-addresses-DEC-primary", "PRO-primary", "addresses", "DEC-primary"),
        _link_event(session_id, "E-L-PRO-OPT", "L-PRO-primary-recommends-OPT-primary", "PRO-primary", "recommends", "OPT-primary"),
        _link_event(session_id, "E-L-DEC-PRO", "L-DEC-primary-accepts-PRO-primary", "DEC-primary", "accepts", "PRO-primary"),
        _link_event(session_id, "E-L-EVI-DEC", "L-EVI-protocol-supports-DEC-primary", "EVI-protocol", "supports", "DEC-primary"),
        _link_event(session_id, "E-L-RSK-DEC", "L-RSK-endpoint-challenges-DEC-primary", "RSK-endpoint", "challenges", "DEC-primary"),
    ]


def _procurement_events(session_id: str) -> list[dict[str, Any]]:
    decision_metadata = _decision_metadata("procurement", "final_selection")
    comparison = {
        **evidence_metadata(
            source="docs",
            source_ref="docs/vendor-comparison.md",
            summary="Comparison table summarizes candidate vendors.",
        ),
        **_pack_identity("procurement"),
        "evidence_requirement_id": "comparison_table",
        "domain_evidence_type": "comparison",
    }
    risk = {
        **risk_metadata(
            statement="A single vendor may increase switching cost.",
            risk_tier="high",
            approval_threshold="human_review",
        ),
        **_pack_identity("procurement"),
        "domain_risk_type": "vendor_lock_in",
    }
    return [
        _object_event(session_id, "E-DEC-final", "DEC-final", "decision", "accepted", "Select the preferred vendor.", decision_metadata),
        _object_event(session_id, "E-PRO-final", "PRO-final", "proposal", "accepted", "Select Vendor A.", {}),
        _object_event(session_id, "E-OPT-vendor-a", "OPT-vendor-a", "option", "active", "Vendor A.", {}),
        _object_event(session_id, "E-EVI-comparison", "EVI-comparison", "evidence", "active", "Vendor comparison.", comparison),
        _object_event(session_id, "E-RSK-lock-in", "RSK-lock-in", "risk", "open", "Vendor lock-in.", risk),
        _link_event(session_id, "E-L-PRO-DEC", "L-PRO-final-addresses-DEC-final", "PRO-final", "addresses", "DEC-final"),
        _link_event(session_id, "E-L-PRO-OPT", "L-PRO-final-recommends-OPT-vendor-a", "PRO-final", "recommends", "OPT-vendor-a"),
        _link_event(session_id, "E-L-DEC-PRO", "L-DEC-final-accepts-PRO-final", "DEC-final", "accepts", "PRO-final"),
        _link_event(session_id, "E-L-EVI-DEC", "L-EVI-comparison-supports-DEC-final", "EVI-comparison", "supports", "DEC-final"),
        _link_event(session_id, "E-L-RSK-DEC", "L-RSK-lock-in-challenges-DEC-final", "RSK-lock-in", "challenges", "DEC-final"),
    ]


def _decision_metadata(pack_id: str, decision_type_id: str) -> dict[str, Any]:
    registry = DomainRegistry(load_builtin_packs())
    spec = registry.decision_type(pack_id, decision_type_id)
    return {
        "priority": spec.default_priority,
        "frontier": "now",
        "reversibility": spec.default_reversibility,
        **_pack_identity(pack_id),
        "domain_decision_type": spec.id,
        "domain_criteria": list(spec.criteria),
    }


def _pack_identity(pack_id: str) -> dict[str, Any]:
    pack = load_builtin_packs()[pack_id]
    return {
        "domain_pack_id": pack.pack_id,
        "domain_pack_version": pack.version,
        "domain_pack_digest": domain_pack_digest(pack),
    }


def _object_event(
    session_id: str,
    event_id: str,
    object_id: str,
    object_type: str,
    status: str,
    body: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "session_id": session_id,
        "event_type": "object_recorded",
        "payload": {
            "object": {
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
        },
    }


def _link_event(
    session_id: str,
    event_id: str,
    link_id: str,
    source: str,
    relation: str,
    target: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "session_id": session_id,
        "event_type": "object_linked",
        "payload": {
            "link": {
                "id": link_id,
                "source_object_id": source,
                "relation": relation,
                "target_object_id": target,
                "rationale": "Domain document profile fixture link.",
                "created_at": NOW,
                "source_event_ids": [event_id],
            }
        },
    }
