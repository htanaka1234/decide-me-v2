from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.events import new_event_id, utc_now
from decide_me.sources.model import (
    evidence_object_id,
    find_unit,
    load_source_metadata,
    load_units,
)
from decide_me.store import load_runtime, runtime_paths, transact
from decide_me.taxonomy import stable_unique


EVIDENCE_RELEVANCE = {"supports", "challenges", "verifies", "constrains"}


def link_evidence_to_object(
    ai_dir: str | Path,
    *,
    session_id: str,
    source_unit_id: str,
    relevance: str,
    decision_id: str | None = None,
    object_id: str | None = None,
    quote: str | None = None,
    interpretation_note: str | None = None,
) -> dict[str, Any]:
    if relevance not in EVIDENCE_RELEVANCE:
        allowed = ", ".join(sorted(EVIDENCE_RELEVANCE))
        raise ValueError(f"relevance must be one of: {allowed}")
    if bool(decision_id) == bool(object_id):
        raise ValueError("exactly one of decision_id or object_id is required")
    target_object_id = decision_id or object_id
    assert target_object_id is not None
    unit = find_unit(ai_dir, source_unit_id)
    metadata = load_source_metadata(ai_dir, unit["source_document_id"])
    evidence_id = evidence_object_id(source_unit_id)
    link_id = f"L-{evidence_id}-{relevance}-{target_object_id}"
    now = utc_now()
    outcome: dict[str, Any] = {"status": "linked"}

    def builder(bundle: dict[str, Any]) -> list[dict[str, Any]]:
        session = bundle["sessions"].get(session_id)
        if session is None:
            raise ValueError(f"unknown session: {session_id}")
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is closed")
        target = _find_object(bundle, target_object_id)
        if target is None:
            raise ValueError(f"unknown target object: {target_object_id}")
        if decision_id is not None and target.get("type") != "decision":
            raise ValueError(f"decision_id references non-decision object: {decision_id}")
        existing_evidence = _find_object(bundle, evidence_id)
        if existing_evidence is not None and existing_evidence.get("type") != "evidence":
            raise ValueError(f"evidence object id collision: {evidence_id}")
        existing_link = _find_link(bundle, link_id)
        if existing_link is not None:
            if (
                existing_link.get("source_object_id") != evidence_id
                or existing_link.get("relation") != relevance
                or existing_link.get("target_object_id") != target_object_id
            ):
                raise ValueError(f"evidence link id collision: {link_id}")
            outcome["status"] = "exists"
            return []

        events: list[dict[str, Any]] = []
        if existing_evidence is None:
            evidence_event_id = new_event_id()
            events.append(
                {
                    "event_id": evidence_event_id,
                    "session_id": session_id,
                    "event_type": "object_recorded",
                    "payload": {
                        "object": _object_payload(
                            object_id=evidence_id,
                            object_type="evidence",
                            title=unit["citation"],
                            body=interpretation_note or f"Source unit {source_unit_id}",
                            status="active",
                            created_at=now,
                            event_id=evidence_event_id,
                            metadata={
                                "source": "source-store",
                                "source_ref": unit["citation"],
                                "summary": interpretation_note or unit["citation"],
                                "confidence": "high",
                                "freshness": "current",
                                "observed_at": now,
                                "valid_until": unit.get("effective_to"),
                                "source_document_id": metadata["id"],
                                "source_unit_id": unit["id"],
                                "source_unit_hash": unit["content_hash"],
                                "citation": unit["citation"],
                                "quote": quote,
                                "interpretation_note": interpretation_note,
                                "effective_from": unit["effective_from"],
                                "effective_to": unit["effective_to"],
                            },
                        )
                    },
                }
            )
        elif existing_evidence.get("metadata", {}).get("source_unit_hash") != unit["content_hash"]:
            raise ValueError(f"existing evidence {evidence_id} points at a different source unit hash")

        link_event_id = new_event_id()
        events.append(
            {
                "event_id": link_event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {
                    "link": _link_payload(
                        link_id=link_id,
                        source_object_id=evidence_id,
                        relation=relevance,
                        target_object_id=target_object_id,
                        rationale=interpretation_note or unit["citation"],
                        created_at=now,
                        event_id=link_event_id,
                    )
                },
            }
        )
        events.append(
            {
                "session_id": session_id,
                "event_type": "evidence_linked_to_object",
                "payload": {
                    "evidence_object_id": evidence_id,
                    "target_object_id": target_object_id,
                    "source_document_id": metadata["id"],
                    "source_unit_id": unit["id"],
                    "source_unit_hash": unit["content_hash"],
                    "relevance": relevance,
                    "linked_at": now,
                },
            }
        )
        return events

    events, bundle = transact(ai_dir, builder)
    return {
        "status": outcome["status"],
        "source_unit_id": source_unit_id,
        "evidence_object_id": evidence_id,
        "target_object_id": target_object_id,
        "link_id": link_id,
        "event_ids": [event["event_id"] for event in events],
        "project_head": bundle["project_state"]["state"].get("project_head"),
    }


def show_source_impact(
    ai_dir: str | Path,
    *,
    source_id: str,
    source_unit_id: str | None = None,
) -> dict[str, Any]:
    metadata = load_source_metadata(ai_dir, source_id)
    unit_ids = {unit["id"] for unit in load_units(ai_dir, source_id)}
    if source_unit_id is not None:
        if source_unit_id not in unit_ids:
            raise ValueError(f"source unit {source_unit_id} does not belong to source document {source_id}")
        unit_ids = {source_unit_id}

    bundle = load_runtime(runtime_paths(ai_dir))
    objects_by_id = {obj["id"]: obj for obj in bundle["project_state"].get("objects", [])}
    evidence_objects = [
        obj
        for obj in objects_by_id.values()
        if obj.get("type") == "evidence"
        and obj.get("metadata", {}).get("source_document_id") == source_id
        and obj.get("metadata", {}).get("source_unit_id") in unit_ids
    ]
    evidence_ids = {obj["id"] for obj in evidence_objects}
    affected: list[dict[str, Any]] = []
    decision_ids: list[str] = []
    link_ids: list[str] = []
    for link in bundle["project_state"].get("links", []):
        if link.get("source_object_id") not in evidence_ids:
            continue
        target = objects_by_id.get(link["target_object_id"])
        if not target:
            continue
        link_ids.append(link["id"])
        affected.append(
            {
                "object_id": target["id"],
                "object_type": target["type"],
                "status": target["status"],
                "title": target.get("title"),
                "via_evidence_object_id": link["source_object_id"],
                "via_link_id": link["id"],
                "relevance": link["relation"],
            }
        )
        if target.get("type") == "decision":
            decision_ids.append(target["id"])

    return {
        "status": "ok",
        "source_document": {
            "id": metadata["id"],
            "title": metadata["title"],
            "content_hash": metadata["content_hash"],
            "effective_from": metadata["effective_from"],
            "effective_to": metadata["effective_to"],
        },
        "source_unit_ids": sorted(unit_ids),
        "summary": {
            "evidence_object_count": len(evidence_objects),
            "affected_object_count": len(affected),
            "affected_decision_count": len(set(decision_ids)),
        },
        "evidence_object_ids": sorted(evidence_ids),
        "affected_objects": sorted(affected, key=lambda item: (item["object_id"], item["via_link_id"])),
        "affected_decision_ids": sorted(stable_unique(decision_ids)),
        "source_link_ids": sorted(stable_unique(link_ids)),
    }


def _find_object(bundle: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    for obj in bundle["project_state"].get("objects", []):
        if obj.get("id") == object_id:
            return obj
    return None


def _find_link(bundle: dict[str, Any], link_id: str) -> dict[str, Any] | None:
    for link in bundle["project_state"].get("links", []):
        if link.get("id") == link_id:
            return link
    return None


def _object_payload(
    *,
    object_id: str,
    object_type: str,
    title: str | None,
    body: str | None,
    status: str,
    created_at: str,
    event_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": object_id,
        "type": object_type,
        "title": title,
        "body": body,
        "status": status,
        "created_at": created_at,
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": deepcopy(metadata),
    }


def _link_payload(
    *,
    link_id: str,
    source_object_id: str,
    relation: str,
    target_object_id: str,
    rationale: str | None,
    created_at: str,
    event_id: str,
) -> dict[str, Any]:
    return {
        "id": link_id,
        "source_object_id": source_object_id,
        "relation": relation,
        "target_object_id": target_object_id,
        "rationale": rationale,
        "created_at": created_at,
        "source_event_ids": [event_id],
    }
