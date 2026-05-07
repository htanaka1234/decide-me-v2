from __future__ import annotations

import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.events import new_event_id, utc_now
from decide_me.graph_traversal import build_graph_index, descendants_with_paths
from decide_me.sources.model import (
    evidence_object_id,
    find_unit,
    load_source_metadata,
    load_units,
    short_hash,
)
from decide_me.store import load_runtime, read_event_log, runtime_paths, transact
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
    _validate_quote(unit, quote)
    metadata = load_source_metadata(ai_dir, unit["source_document_id"])
    evidence_id = evidence_object_id(source_unit_id)
    now = utc_now()
    link_metadata = _source_store_link_metadata(
        metadata=metadata,
        unit=unit,
        quote=quote,
        interpretation_note=interpretation_note,
        linked_at=now,
    )
    link_id = (
        f"L-{evidence_id}-{relevance}-{target_object_id}-"
        f"{short_hash(source_unit_id, target_object_id, relevance, quote, interpretation_note, length=8)}"
    )
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
                or _metadata_without_linked_at(existing_link.get("metadata", {}))
                != _metadata_without_linked_at(link_metadata)
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
                                "summary": unit["citation"],
                                "confidence": "high",
                                "freshness": "current",
                                "observed_at": now,
                                "valid_until": unit.get("effective_to"),
                                "source_document_id": metadata["id"],
                                "source_unit_id": unit["id"],
                                "source_unit_hash": unit["content_hash"],
                                "citation": unit["citation"],
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
                        metadata=link_metadata,
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
                    "link_id": link_id,
                    "target_object_id": target_object_id,
                    "source_document_id": metadata["id"],
                    "source_unit_id": unit["id"],
                    "source_unit_hash": unit["content_hash"],
                    "relevance": relevance,
                    "quote": quote,
                    "interpretation_note": interpretation_note,
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
    include_previous_version_links: bool = False,
) -> dict[str, Any]:
    metadata = load_source_metadata(ai_dir, source_id)
    source_ids = [source_id]
    previous_source_ids: list[str] = []
    if include_previous_version_links and source_unit_id is None:
        previous_source_ids = _previous_source_ids(ai_dir, source_id)
        source_ids.extend(previous_source_ids)

    unit_ids_by_source = {candidate_id: {unit["id"] for unit in load_units(ai_dir, candidate_id)} for candidate_id in source_ids}
    unit_ids = set(unit_ids_by_source[source_id])
    if source_unit_id is not None:
        if source_unit_id not in unit_ids:
            raise ValueError(f"source unit {source_unit_id} does not belong to source document {source_id}")
        unit_ids = {source_unit_id}
        unit_ids_by_source = {source_id: unit_ids}

    bundle = load_runtime(runtime_paths(ai_dir))
    objects_by_id = {obj["id"]: obj for obj in bundle["project_state"].get("objects", [])}
    evidence_objects = [
        obj
        for obj in objects_by_id.values()
        if obj.get("type") == "evidence"
        and obj.get("metadata", {}).get("source_document_id") in unit_ids_by_source
        and obj.get("metadata", {}).get("source_unit_id")
        in unit_ids_by_source.get(obj.get("metadata", {}).get("source_document_id"), set())
    ]
    evidence_ids = {obj["id"] for obj in evidence_objects}
    affected: list[dict[str, Any]] = []
    direct_decision_ids: list[str] = []
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
                "source_document_id": objects_by_id[link["source_object_id"]]["metadata"]["source_document_id"],
                "source_unit_id": objects_by_id[link["source_object_id"]]["metadata"]["source_unit_id"],
            }
        )
        if target.get("type") == "decision":
            direct_decision_ids.append(target["id"])

    downstream = _downstream_decisions(bundle["project_state"], evidence_ids)
    downstream_decision_ids = [item["decision_id"] for item in downstream]
    decision_ids = [*direct_decision_ids, *downstream_decision_ids]

    return {
        "status": "ok",
        "source_document": {
            "id": metadata["id"],
            "title": metadata["title"],
            "content_hash": metadata["content_hash"],
            "effective_from": metadata["effective_from"],
            "effective_to": metadata["effective_to"],
        },
        "included_source_document_ids": source_ids,
        "included_previous_source_document_ids": previous_source_ids,
        "source_unit_ids": sorted(unit_id for ids in unit_ids_by_source.values() for unit_id in ids),
        "summary": {
            "evidence_object_count": len(evidence_objects),
            "direct_affected_object_count": len(affected),
            "affected_object_count": len(affected),
            "direct_affected_decision_count": len(set(direct_decision_ids)),
            "downstream_affected_decision_count": len(set(downstream_decision_ids)),
            "affected_decision_count": len(set(decision_ids)),
        },
        "evidence_object_ids": sorted(evidence_ids),
        "affected_objects": sorted(affected, key=lambda item: (item["object_id"], item["via_link_id"])),
        "downstream_affected_decisions": sorted(
            downstream,
            key=lambda item: (item["decision_id"], item["via_evidence_object_id"], item["path_link_ids"]),
        ),
        "affected_decision_ids": sorted(stable_unique(decision_ids)),
        "source_link_ids": sorted(stable_unique([*link_ids, *[link_id for item in downstream for link_id in item["path_link_ids"]]])),
    }


def _previous_source_ids(ai_dir: str | Path, source_id: str) -> list[str]:
    paths = runtime_paths(ai_dir)
    previous: list[str] = []
    pending = [source_id]
    seen = {source_id}
    for event in reversed(read_event_log(paths)):
        if event.get("event_type") != "source_version_updated":
            continue
        payload = event.get("payload", {})
        current_id = payload.get("source_document_id")
        previous_id = payload.get("previous_source_document_id")
        if current_id not in pending or not isinstance(previous_id, str) or previous_id in seen:
            continue
        previous.append(previous_id)
        pending.append(previous_id)
        seen.add(previous_id)
    return previous


def _downstream_decisions(project_state: dict[str, Any], evidence_ids: set[str]) -> list[dict[str, Any]]:
    if not evidence_ids:
        return []
    objects_by_id = {obj["id"]: obj for obj in project_state.get("objects", [])}
    index = build_graph_index(project_state)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for evidence_id in sorted(evidence_ids):
        for item in descendants_with_paths(index, evidence_id):
            obj = objects_by_id.get(item["object_id"])
            if not obj or obj.get("type") != "decision":
                continue
            path = item.get("path", {})
            path_link_ids = list(path.get("link_ids", []))
            path_object_ids = list(path.get("node_ids", []))
            key = (evidence_id, obj["id"], tuple(path_link_ids))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "decision_id": obj["id"],
                    "decision_status": obj.get("status"),
                    "decision_title": obj.get("title"),
                    "via_evidence_object_id": evidence_id,
                    "path_object_ids": path_object_ids,
                    "path_link_ids": path_link_ids,
                }
            )
    return rows


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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": link_id,
        "source_object_id": source_object_id,
        "relation": relation,
        "target_object_id": target_object_id,
        "rationale": rationale,
        "created_at": created_at,
        "source_event_ids": [event_id],
    }
    if metadata:
        payload["metadata"] = deepcopy(metadata)
    return payload


def _source_store_link_metadata(
    *,
    metadata: dict[str, Any],
    unit: dict[str, Any],
    quote: str | None,
    interpretation_note: str | None,
    linked_at: str,
) -> dict[str, Any]:
    return {
        "source_document_id": metadata["id"],
        "source_unit_id": unit["id"],
        "source_unit_hash": unit["content_hash"],
        "citation": unit["citation"],
        "quote": quote,
        "interpretation_note": interpretation_note,
        "effective_from": unit["effective_from"],
        "effective_to": unit["effective_to"],
        "linked_at": linked_at,
    }


def _validate_quote(unit: dict[str, Any], quote: str | None) -> None:
    if quote is None:
        return
    if not quote.strip():
        raise ValueError("quote must be a non-empty string when provided")
    normalized_quote = _quote_match_text(quote)
    candidates = [
        _quote_match_text(unit.get("text_exact") or ""),
        _quote_match_text(unit.get("text_normalized") or ""),
    ]
    if not any(normalized_quote in candidate for candidate in candidates):
        raise ValueError("quote must be contained in source unit text")


def _quote_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _metadata_without_linked_at(metadata: dict[str, Any]) -> dict[str, Any]:
    copied = dict(metadata)
    copied.pop("linked_at", None)
    return copied
