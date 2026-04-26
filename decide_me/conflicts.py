from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from decide_me.events import build_event, new_tx_id, utc_now
from decide_me.projections import rebuild_projections
from decide_me.store import (
    CONTROL_EVENT_TYPES,
    SYSTEM_SESSION_ID,
    _write_lock,
    _write_projections_and_index,
    _write_transaction,
    canonicalize_events,
    effective_events_from_raw,
    ensure_runtime_dirs,
    read_raw_event_log,
    rejected_transaction_ids,
    runtime_paths,
)
from decide_me.validate import (
    SESSION_MUTATION_EVENT_TYPES,
    StateValidationError,
    validate_event_log,
    validate_projection_bundle,
)


MAX_REJECTION_SET_SIZE = 2
ENTITY_ID_PATTERN = re.compile(r"\b[DP]-[A-Za-z0-9_.:-]+\b")


def detect_merge_conflicts(ai_dir: str) -> list[dict[str, Any]]:
    paths = runtime_paths(ai_dir)
    raw_events = read_raw_event_log(paths)
    effective_events = effective_events_from_raw(raw_events)
    try:
        validate_event_log(effective_events)
    except StateValidationError as exc:
        conflict_message = str(exc)
    else:
        return []

    return _detect_merge_conflicts_from_invalid_events(effective_events, conflict_message)


def _detect_merge_conflicts_from_invalid_events(
    effective_events: list[dict[str, Any]],
    conflict_message: str,
) -> list[dict[str, Any]]:
    transactions = _transactions_by_id(effective_events)
    conflicts: list[dict[str, Any]] = []
    for session_id, candidate_tx_ids in _targetable_tx_ids_by_session(transactions).items():
        resolution_options = _valid_resolution_options(
            effective_events,
            candidate_tx_ids,
        )
        if not resolution_options:
            continue
        candidate_ids, option_payloads = _resolution_options_with_participants(
            conflict_message,
            effective_events,
            transactions,
            candidate_tx_ids,
            resolution_options,
        )
        if not option_payloads:
            continue
        conflicts.append(
            {
                "session_id": session_id,
                "kind": _classify_conflict(conflict_message),
                "message": conflict_message,
                "candidate_transactions": [
                    _summarize_transaction(tx_id, transactions[tx_id]) for tx_id in candidate_ids
                ],
                "resolution_options": option_payloads,
            }
        )
        break
    return conflicts


def resolve_merge_conflict(
    ai_dir: str,
    *,
    session_id: str,
    keep_tx_id: str,
    reject_tx_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason must be a non-empty string")

    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        raw_events = read_raw_event_log(paths)
        effective_events = effective_events_from_raw(raw_events)
        try:
            validate_event_log(effective_events)
        except StateValidationError as exc:
            conflict_message = str(exc)
        else:
            raise ValueError("no unresolved merge conflict exists")

        transactions = _transactions_by_id(raw_events)
        normalized_reject_tx_ids = _normalize_reject_tx_ids(reject_tx_ids)
        _validate_resolution_targets(
            session_id=session_id,
            keep_tx_id=keep_tx_id,
            reject_tx_ids=normalized_reject_tx_ids,
            transactions=transactions,
            already_rejected=rejected_transaction_ids(raw_events),
        )
        _validate_resolution_option(
            session_id=session_id,
            keep_tx_id=keep_tx_id,
            reject_tx_ids=normalized_reject_tx_ids,
            conflicts=_detect_merge_conflicts_from_invalid_events(effective_events, conflict_message),
        )

        now = utc_now()
        event = build_event(
            tx_id=new_tx_id(),
            tx_index=1,
            tx_size=1,
            session_id=session_id,
            event_type="transaction_rejected",
            payload={
                "kept_tx_id": keep_tx_id,
                "rejected_tx_ids": normalized_reject_tx_ids,
                "reason": reason,
                "resolved_at": now,
                "conflict_kind": _classify_conflict(conflict_message),
                "conflict_summary": conflict_message,
            },
            timestamp=now,
        )
        proposed_raw_events = canonicalize_events([*raw_events, event])
        proposed_effective_events = effective_events_from_raw(proposed_raw_events)
        validate_event_log(proposed_effective_events)
        bundle = rebuild_projections(proposed_effective_events)
        validate_projection_bundle(bundle)

        _write_transaction(paths, [event])
        _write_projections_and_index(
            paths,
            bundle,
            effective_events=proposed_effective_events,
            rejected_tx_ids=rejected_transaction_ids(proposed_raw_events),
        )
        state = bundle["project_state"]["state"]
        return {
            "resolution_event": event,
            "session_id": session_id,
            "kept_tx_id": keep_tx_id,
            "rejected_tx_ids": normalized_reject_tx_ids,
            "project_head": state["project_head"],
            "event_count": state["event_count"],
        }


def _valid_resolution_options(
    events: list[dict[str, Any]],
    candidate_tx_ids: list[str],
) -> list[tuple[str, ...]]:
    options: list[tuple[str, ...]] = []
    max_size = min(MAX_REJECTION_SET_SIZE, len(candidate_tx_ids))
    for size in range(1, max_size + 1):
        for reject_tx_ids in combinations(candidate_tx_ids, size):
            trial_events = _without_transactions(events, set(reject_tx_ids))
            try:
                validate_event_log(trial_events)
            except StateValidationError:
                continue
            options.append(tuple(reject_tx_ids))
        if options:
            break
    return options


def _resolution_options_with_participants(
    conflict_message: str,
    events: list[dict[str, Any]],
    transactions: dict[str, list[dict[str, Any]]],
    candidate_tx_ids: list[str],
    resolution_options: list[tuple[str, ...]],
) -> tuple[list[str], list[dict[str, list[str]]]]:
    conflict_kind = _classify_conflict(conflict_message)
    all_option_tx_ids = {tx_id for option in resolution_options for tx_id in option}
    entity_tx_ids = _entity_participant_tx_ids(conflict_message, transactions, candidate_tx_ids)
    lifecycle_tx_ids = (
        _session_lifecycle_participant_tx_ids(events, transactions, candidate_tx_ids)
        if conflict_kind == "session-lifecycle-conflict"
        else set()
    )
    allow_option_union_fallback = conflict_kind in {
        "competing-active-proposals",
        "proposal-response-conflict",
        "duplicate-decision-discovery",
        "session-lifecycle-conflict",
    }

    candidate_ids: set[str] = set()
    payloads: list[dict[str, list[str]]] = []
    for option in resolution_options:
        rejected = set(option)
        participants = set(rejected) | entity_tx_ids | lifecycle_tx_ids
        if len(participants) < 2 and allow_option_union_fallback:
            participants |= all_option_tx_ids
        if len(participants) < 2:
            continue
        reject_tx_ids = list(option)
        surviving_tx_ids = sorted(participants - rejected)
        if not surviving_tx_ids:
            continue
        candidate_ids.update(participants)
        payloads.append(
            {
                "reject_tx_ids": reject_tx_ids,
                "surviving_tx_ids": surviving_tx_ids,
                "keep_tx_ids": list(surviving_tx_ids),
            }
        )
    return sorted(candidate_ids), payloads


def _entity_participant_tx_ids(
    conflict_message: str,
    transactions: dict[str, list[dict[str, Any]]],
    candidate_tx_ids: list[str],
) -> set[str]:
    participants: set[str] = set()
    proposal_ids = {
        entity_id for entity_id in ENTITY_ID_PATTERN.findall(conflict_message) if entity_id.startswith("P-")
    }
    decision_ids = {
        entity_id for entity_id in ENTITY_ID_PATTERN.findall(conflict_message) if entity_id.startswith("D-")
    }
    for tx_id in candidate_tx_ids:
        tx_events = transactions[tx_id]
        tx_proposal_ids = {proposal_id for event in tx_events for proposal_id in _proposal_ids(event)}
        tx_decision_ids = {decision_id for event in tx_events for decision_id in _decision_ids(event)}
        if proposal_ids & tx_proposal_ids or decision_ids & tx_decision_ids:
            participants.add(tx_id)
    return participants


def _session_lifecycle_participant_tx_ids(
    events: list[dict[str, Any]],
    transactions: dict[str, list[dict[str, Any]]],
    candidate_tx_ids: list[str],
) -> set[str]:
    candidate_set = set(candidate_tx_ids)
    close_tx_ids = {
        tx_id
        for tx_id in candidate_set
        if any(event["event_type"] == "session_closed" for event in transactions[tx_id])
    }
    late_mutation_tx_ids: set[str] = set()
    closed_sessions: set[str] = set()
    for event in canonicalize_events(events):
        session_id = event["session_id"]
        tx_id = event["tx_id"]
        if session_id in closed_sessions and tx_id in candidate_set:
            if event["event_type"] in SESSION_MUTATION_EVENT_TYPES or event["event_type"] == "session_closed":
                late_mutation_tx_ids.add(tx_id)
        if event["event_type"] == "session_closed":
            closed_sessions.add(session_id)
    return close_tx_ids | late_mutation_tx_ids


def _validate_resolution_option(
    *,
    session_id: str,
    keep_tx_id: str,
    reject_tx_ids: list[str],
    conflicts: list[dict[str, Any]],
) -> None:
    requested_rejects = set(reject_tx_ids)
    for conflict in conflicts:
        if conflict["session_id"] != session_id:
            continue
        candidate_tx_ids = {item["tx_id"] for item in conflict["candidate_transactions"]}
        if keep_tx_id not in candidate_tx_ids:
            raise ValueError("keep_tx_id is not part of the unresolved merge conflict")
        for option in conflict["resolution_options"]:
            if set(option["reject_tx_ids"]) != requested_rejects:
                continue
            if keep_tx_id not in set(option["surviving_tx_ids"]):
                raise ValueError("keep_tx_id must be a surviving transaction for the selected resolution option")
            return
        raise ValueError("reject_tx_ids do not match a valid resolution option")
    raise ValueError(f"no unresolved merge conflict exists for session {session_id}")


def _without_transactions(events: list[dict[str, Any]], tx_ids: set[str]) -> list[dict[str, Any]]:
    return canonicalize_events([event for event in events if event["tx_id"] not in tx_ids])


def _targetable_tx_ids_by_session(
    transactions: dict[str, list[dict[str, Any]]]
) -> dict[str, list[str]]:
    by_session: dict[str, list[str]] = {}
    for tx_id, events in transactions.items():
        if _is_targetable_transaction(events):
            session_id = events[0]["session_id"]
            by_session.setdefault(session_id, []).append(tx_id)
    return {session_id: sorted(tx_ids) for session_id, tx_ids in sorted(by_session.items())}


def _is_targetable_transaction(events: list[dict[str, Any]]) -> bool:
    session_ids = {event["session_id"] for event in events}
    if len(session_ids) != 1 or SYSTEM_SESSION_ID in session_ids:
        return False
    event_types = {event["event_type"] for event in events}
    if event_types & CONTROL_EVENT_TYPES:
        return False
    if event_types & {"project_initialized", "session_created"}:
        return False
    return True


def _validate_resolution_targets(
    *,
    session_id: str,
    keep_tx_id: str,
    reject_tx_ids: list[str],
    transactions: dict[str, list[dict[str, Any]]],
    already_rejected: set[str],
) -> None:
    if session_id == SYSTEM_SESSION_ID:
        raise ValueError("merge conflicts can only be resolved for non-SYSTEM sessions")
    if keep_tx_id in reject_tx_ids:
        raise ValueError("keep_tx_id must not be listed as a rejected transaction")
    target_tx_ids = [keep_tx_id, *reject_tx_ids]
    for tx_id in target_tx_ids:
        events = transactions.get(tx_id)
        if events is None:
            raise ValueError(f"unknown transaction: {tx_id}")
        if tx_id in already_rejected:
            raise ValueError(f"transaction is already rejected: {tx_id}")
        if not _is_targetable_transaction(events):
            raise ValueError(f"transaction cannot be selected for merge conflict resolution: {tx_id}")
        tx_session_ids = {event["session_id"] for event in events}
        if tx_session_ids != {session_id}:
            raise ValueError(f"transaction {tx_id} does not belong to session {session_id}")


def _normalize_reject_tx_ids(reject_tx_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tx_id in reject_tx_ids:
        candidate = tx_id.strip()
        if not candidate:
            raise ValueError("reject_tx_id must be a non-empty string")
        if candidate in seen:
            raise ValueError(f"duplicate reject_tx_id: {candidate}")
        seen.add(candidate)
        normalized.append(candidate)
    if not normalized:
        raise ValueError("at least one reject_tx_id is required")
    return normalized


def _transactions_by_id(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    transactions: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        transactions.setdefault(event["tx_id"], []).append(event)
    return {
        tx_id: sorted(tx_events, key=lambda event: event["tx_index"])
        for tx_id, tx_events in sorted(transactions.items())
    }


def _summarize_transaction(tx_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types = [event["event_type"] for event in events]
    decision_ids = sorted({decision_id for event in events for decision_id in _decision_ids(event)})
    proposal_ids = sorted({proposal_id for event in events for proposal_id in _proposal_ids(event)})
    timestamps = sorted(event["ts"] for event in events)
    return {
        "tx_id": tx_id,
        "event_types": event_types,
        "decision_ids": decision_ids,
        "proposal_ids": proposal_ids,
        "first_ts": timestamps[0],
        "last_ts": timestamps[-1],
        "summary": _transaction_summary_text(events),
    }


def _decision_ids(event: dict[str, Any]) -> list[str]:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type == "decision_discovered":
        return [payload["decision"]["id"]]
    if event_type in {"decision_enriched", "question_asked", "decision_deferred", "decision_resolved_by_evidence"}:
        return [payload["decision_id"]]
    if event_type == "proposal_issued":
        return [payload["proposal"]["target_id"]]
    if event_type in {"proposal_accepted", "proposal_rejected"}:
        return [payload["target_id"]]
    if event_type == "decision_invalidated":
        return [payload["decision_id"], payload["invalidated_by_decision_id"]]
    return []


def _proposal_ids(event: dict[str, Any]) -> list[str]:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type == "proposal_issued":
        return [payload["proposal"]["proposal_id"]]
    if event_type in {"proposal_accepted", "proposal_rejected"}:
        return [payload["proposal_id"]]
    return []


def _transaction_summary_text(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event["event_type"] == "proposal_issued":
            proposal = event["payload"]["proposal"]
            return (
                f"proposal {proposal['proposal_id']} for {proposal['target_id']}: "
                f"{proposal['recommendation']}"
            )
        if event["event_type"] == "proposal_accepted":
            return f"accept proposal {event['payload']['proposal_id']}"
        if event["event_type"] == "proposal_rejected":
            return f"reject proposal {event['payload']['proposal_id']}: {event['payload']['reason']}"
        if event["event_type"] == "decision_discovered":
            decision = event["payload"]["decision"]
            return f"discover decision {decision['id']}: {decision['title']}"
    return ", ".join(event["event_type"] for event in events)


def _classify_conflict(message: str) -> str:
    if "proposal_issued while proposal" in message:
        return "competing-active-proposals"
    if "proposal_accepted" in message or "proposal_rejected" in message:
        return "proposal-response-conflict"
    if "duplicate decision_discovered id" in message:
        return "duplicate-decision-discovery"
    if "mutates closed session" in message or "already closed" in message:
        return "session-lifecycle-conflict"
    return "same-session-semantic-conflict"
