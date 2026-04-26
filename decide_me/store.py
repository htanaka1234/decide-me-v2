from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from decide_me.events import AUTO_PROJECT_HEAD, build_event, new_tx_id, utc_now, validate_event
from decide_me.projections import project_heads_by_event_id, rebuild_projections
from decide_me.validate import (
    StateValidationError,
    validate_event_log,
    validate_event_log_structure,
    validate_projection_bundle,
)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


SYSTEM_SESSION_ID = "SYSTEM"
CONTROL_EVENT_TYPES = {"transaction_rejected", "session_linked", "semantic_conflict_resolved"}


@dataclass(frozen=True)
class RuntimePaths:
    ai_dir: Path
    events_dir: Path
    system_events_dir: Path
    session_events_dir: Path
    project_state: Path
    taxonomy_state: Path
    sessions_dir: Path
    exports_dir: Path
    plans_dir: Path
    adr_dir: Path
    lock_path: Path


def runtime_paths(ai_dir: str | Path) -> RuntimePaths:
    root = Path(ai_dir)
    return RuntimePaths(
        ai_dir=root,
        events_dir=root / "events",
        system_events_dir=root / "events" / "system",
        session_events_dir=root / "events" / "sessions",
        project_state=root / "project-state.json",
        taxonomy_state=root / "taxonomy-state.json",
        sessions_dir=root / "sessions",
        exports_dir=root / "exports",
        plans_dir=root / "exports" / "plans",
        adr_dir=root / "exports" / "adr",
        lock_path=root / "write.lock",
    )


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    paths.ai_dir.mkdir(parents=True, exist_ok=True)
    paths.system_events_dir.mkdir(parents=True, exist_ok=True)
    paths.session_events_dir.mkdir(parents=True, exist_ok=True)
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    paths.plans_dir.mkdir(parents=True, exist_ok=True)
    paths.adr_dir.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_json_if_exists(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


def read_raw_event_log(paths: RuntimePaths) -> list[dict[str, Any]]:
    _reject_legacy_event_log(paths)
    if not paths.events_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(paths.events_dir.rglob("*.jsonl")):
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    relative = path.relative_to(paths.ai_dir)
                    raise StateValidationError(
                        f"{relative} line {line_number} contains malformed JSON: {exc.msg}"
                    ) from exc
                _validate_event_file_location(paths, path, event)
                events.append(event)
    raw_events = canonicalize_events(events)
    validate_event_log_structure(raw_events)
    _validate_transaction_rejection_controls(raw_events)
    return raw_events


def read_event_log(paths: RuntimePaths) -> list[dict[str, Any]]:
    return effective_events_from_raw(read_raw_event_log(paths))


def effective_events_from_raw(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_events = canonicalize_events(events)
    validate_event_log_structure(raw_events)
    _validate_transaction_rejection_controls(raw_events)
    rejected_tx_ids = rejected_transaction_ids(raw_events)
    return canonicalize_events(
        [
            event
            for event in raw_events
            if event["tx_id"] not in rejected_tx_ids or event["event_type"] == "transaction_rejected"
        ]
    )


def rejected_transaction_ids(events: list[dict[str, Any]]) -> set[str]:
    rejected: set[str] = set()
    for event in events:
        if event.get("event_type") != "transaction_rejected":
            continue
        for tx_id in event["payload"]["rejected_tx_ids"]:
            if tx_id in rejected:
                raise StateValidationError(f"transaction {tx_id} is rejected more than once")
            rejected.add(tx_id)
    return rejected


def load_runtime(paths: RuntimePaths) -> dict[str, Any]:
    events = read_event_log(paths)
    validate_event_log(events)
    bundle = rebuild_projections(events)
    validate_projection_bundle(bundle)
    return bundle


def bootstrap_runtime(
    ai_dir: str | Path,
    *,
    project_name: str,
    objective: str,
    current_milestone: str,
    stop_rule: str | None = None,
    default_bundles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        _reject_legacy_event_log(paths)
        if _event_files(paths):
            raise StateValidationError(f"runtime already exists at {paths.ai_dir}")

        stop_rule = stop_rule or (
            "All relevant P0 decisions with frontier=now are resolved, accepted, or explicitly deferred."
        )
        payload = {
            "project": {
                "name": project_name,
                "objective": objective,
                "current_milestone": current_milestone,
                "stop_rule": stop_rule,
            },
            "protocol": {
                "plain_ok_scope": "same-session-active-proposal-only",
                "proposal_expiry_rules": [
                    "project-head-changed",
                    "session-boundary",
                    "superseded-proposal",
                    "decision-invalidated",
                    "session-closed",
                ],
                "close_policy": "generate-close-summary-on-close",
            },
            "default_bundles": default_bundles or [],
        }
        tx_id = new_tx_id()
        event = build_event(
            tx_id=tx_id,
            tx_index=1,
            tx_size=1,
            session_id=SYSTEM_SESSION_ID,
            event_type="project_initialized",
            payload=payload,
            timestamp=utc_now(),
        )
        bundle = rebuild_projections([event])
        validate_projection_bundle(bundle)
        _write_transaction(paths, [event])
        _write_projections(paths, bundle)
        return bundle


def rebuild_and_persist(ai_dir: str | Path) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        events = read_event_log(paths)
        validate_event_log(events)
        bundle = rebuild_projections(events)
        validate_projection_bundle(bundle)
        _write_projections(paths, bundle)
        return bundle


def validate_runtime(ai_dir: str | Path) -> list[str]:
    paths = runtime_paths(ai_dir)
    issues: list[str] = []
    try:
        events = read_event_log(paths)
        validate_event_log(events)
    except (StateValidationError, ValueError) as exc:
        issues.append(str(exc))
        try:
            from decide_me.conflicts import detect_merge_conflicts

            if detect_merge_conflicts(str(paths.ai_dir)):
                issues.append("unresolved same-session merge conflict; run detect-merge-conflicts")
        except (StateValidationError, ValueError):
            pass
        return issues

    rebuilt = rebuild_projections(events)
    try:
        validate_projection_bundle(rebuilt)
    except (StateValidationError, ValueError) as exc:
        issues.append(str(exc))
        return issues

    persisted_project = load_json_if_exists(paths.project_state)
    persisted_taxonomy = load_json_if_exists(paths.taxonomy_state)
    if persisted_project is None:
        issues.append("missing project-state.json")
    elif _canonical_json(persisted_project) != _canonical_json(rebuilt["project_state"]):
        issues.append("project-state.json does not match the event log")

    if persisted_taxonomy is None:
        issues.append("missing taxonomy-state.json")
    elif _canonical_json(persisted_taxonomy) != _canonical_json(rebuilt["taxonomy_state"]):
        issues.append("taxonomy-state.json does not match the event log")

    session_files = {
        path.stem: load_json(path) for path in paths.sessions_dir.glob("*.json") if path.is_file()
    }
    for session_id, session_state in rebuilt["sessions"].items():
        persisted = session_files.get(session_id)
        if persisted is None:
            issues.append(f"missing session projection for {session_id}")
        elif _canonical_json(persisted) != _canonical_json(session_state):
            issues.append(f"session projection mismatch for {session_id}")

    extra_files = set(session_files) - set(rebuilt["sessions"])
    for session_id in sorted(extra_files):
        issues.append(f"stale session projection exists for {session_id}")

    return issues


EventSpec = dict[str, Any]
Builder = Callable[[dict[str, Any]], list[EventSpec]]


def transact(ai_dir: str | Path, builder: Builder) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        existing_events = read_event_log(paths)
        validate_event_log(existing_events)
        current_bundle = rebuild_projections(existing_events)
        validate_projection_bundle(current_bundle)

        specs = builder(current_bundle)
        if not specs:
            return [], current_bundle

        tx_id = new_tx_id()
        tx_timestamp = utc_now()
        tx_size = len(specs)
        built_events: list[dict[str, Any]] = []
        tx_session_id: str | None = None

        for offset, spec in enumerate(specs, start=1):
            session_id = spec.get("session_id", SYSTEM_SESSION_ID)
            if tx_session_id is None:
                tx_session_id = session_id
            elif session_id != tx_session_id:
                raise StateValidationError("transaction events must share one session_id")
            built_events.append(
                build_event(
                    tx_id=tx_id,
                    tx_index=offset,
                    tx_size=tx_size,
                    session_id=session_id,
                    event_type=spec["event_type"],
                    payload=spec["payload"],
                    timestamp=spec.get("ts", tx_timestamp),
                    project_head=current_bundle["project_state"]["state"]["project_head"],
                )
            )

        new_events = canonicalize_events([*existing_events, *built_events])
        _fill_auto_project_heads(new_events, specs, built_events)
        validate_event_log(new_events)
        new_bundle = rebuild_projections(new_events)
        validate_projection_bundle(new_bundle)
        _write_transaction(paths, built_events)
        _write_projections(paths, new_bundle)
        return built_events, new_bundle


@contextmanager
def _write_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:  # pragma: no branch
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:  # pragma: no branch
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def canonicalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=_canonical_event_sort_key)


def _canonical_event_sort_key(event: dict[str, Any]) -> tuple[int, str, str, int, str]:
    return (
        0 if event.get("event_type") == "project_initialized" else 1,
        str(event.get("ts") or ""),
        str(event.get("tx_id") or ""),
        int(event.get("tx_index") or 0),
        str(event.get("event_id") or ""),
    )


def _event_files(paths: RuntimePaths) -> list[Path]:
    if not paths.events_dir.exists():
        return []
    return sorted(path for path in paths.events_dir.rglob("*.jsonl") if path.is_file())


def _reject_legacy_event_log(paths: RuntimePaths) -> None:
    legacy_path = paths.ai_dir / "event-log.jsonl"
    if legacy_path.exists():
        raise StateValidationError(
            "legacy event-log.jsonl is unsupported in this runtime layout; "
            "automatic migration is not available. Rebootstrap this runtime, or export with the previous runtime "
            "and recreate it under .ai/decide-me/events/."
        )


def _validate_transaction_rejection_controls(events: list[dict[str, Any]]) -> None:
    by_tx_id: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_tx_id.setdefault(event["tx_id"], []).append(event)

    rejected_tx_ids: set[str] = set()
    control_events = [event for event in events if event["event_type"] == "transaction_rejected"]
    for event in control_events:
        tx_id = event["tx_id"]
        tx_events = by_tx_id[tx_id]
        if len(tx_events) != 1:
            raise StateValidationError("transaction_rejected must be the only event in its transaction")
        session_id = event["session_id"]
        if session_id == SYSTEM_SESSION_ID:
            raise StateValidationError("transaction_rejected must use a non-SYSTEM session_id")

        payload = event["payload"]
        target_tx_ids = [payload["kept_tx_id"], *payload["rejected_tx_ids"]]
        for target_tx_id in target_tx_ids:
            target_events = by_tx_id.get(target_tx_id)
            if target_events is None:
                raise StateValidationError(f"transaction_rejected references unknown transaction {target_tx_id}")
            if target_tx_id == tx_id:
                raise StateValidationError("transaction_rejected must not target its own transaction")
            target_session_ids = {target["session_id"] for target in target_events}
            if target_session_ids != {session_id}:
                raise StateValidationError(
                    f"transaction_rejected target {target_tx_id} must belong to session {session_id}"
                )
            if any(target["event_type"] in CONTROL_EVENT_TYPES for target in target_events):
                raise StateValidationError("transaction_rejected must not target control transactions")
            if any(target["event_type"] in {"project_initialized", "session_created"} for target in target_events):
                raise StateValidationError("transaction_rejected must not target initialization transactions")

        kept_tx_id = payload["kept_tx_id"]
        if kept_tx_id in rejected_tx_ids:
            raise StateValidationError(f"kept transaction {kept_tx_id} is rejected by another transaction_rejected")
        for rejected_tx_id in payload["rejected_tx_ids"]:
            if rejected_tx_id in rejected_tx_ids:
                raise StateValidationError(f"transaction {rejected_tx_id} is rejected more than once")
            rejected_tx_ids.add(rejected_tx_id)


def _validate_event_file_location(paths: RuntimePaths, path: Path, event: dict[str, Any]) -> None:
    relative = path.relative_to(paths.ai_dir)
    parts = relative.parts
    tx_id = event.get("tx_id")
    session_id = event.get("session_id")
    if len(parts) == 3 and parts[0] == "events" and parts[1] == "system":
        if session_id != SYSTEM_SESSION_ID:
            raise StateValidationError(f"{relative} contains non-SYSTEM event {event.get('event_id')}")
    elif len(parts) == 4 and parts[0] == "events" and parts[1] == "sessions":
        if session_id != parts[2]:
            raise StateValidationError(f"{relative} contains event for session {session_id}")
    else:
        raise StateValidationError(f"unsupported event log path: {relative}")
    if path.stem != tx_id:
        raise StateValidationError(f"{relative} filename does not match tx_id {tx_id}")


def _write_transaction(paths: RuntimePaths, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    session_ids = {event["session_id"] for event in events}
    tx_ids = {event["tx_id"] for event in events}
    if len(session_ids) != 1 or len(tx_ids) != 1:
        raise StateValidationError("transaction events must share one tx_id and session_id")
    session_id = next(iter(session_ids))
    tx_id = next(iter(tx_ids))
    directory = paths.system_events_dir if session_id == SYSTEM_SESSION_ID else paths.session_events_dir / session_id
    path = directory / f"{tx_id}.jsonl"
    if path.exists():
        raise StateValidationError(f"transaction already exists: {tx_id}")
    body = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    _atomic_write_text(path, body)


def _fill_auto_project_heads(
    canonical_events: list[dict[str, Any]], specs: list[EventSpec], built_events: list[dict[str, Any]]
) -> None:
    heads = project_heads_by_event_id(canonical_events)
    for spec, event in zip(specs, built_events, strict=True):
        if event["event_type"] != "proposal_issued":
            continue
        original = spec["payload"].get("proposal", {}).get("based_on_project_head")
        if original not in {None, AUTO_PROJECT_HEAD}:
            continue
        event["payload"]["proposal"]["based_on_project_head"] = heads[event["event_id"]]
        validate_event(event)


def _write_projections(paths: RuntimePaths, bundle: dict[str, Any]) -> None:
    ensure_runtime_dirs(paths)
    _atomic_write_json(paths.project_state, bundle["project_state"])
    _atomic_write_json(paths.taxonomy_state, bundle["taxonomy_state"])

    active_session_files: set[Path] = set()
    for session_id, session_state in bundle["sessions"].items():
        path = paths.sessions_dir / f"{session_id}.json"
        active_session_files.add(path)
        _atomic_write_json(path, session_state)

    for existing in paths.sessions_dir.glob("*.json"):
        if existing not in active_session_files:
            existing.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    _atomic_write_text(path, body)


def _atomic_write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
