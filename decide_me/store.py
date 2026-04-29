from __future__ import annotations

import json
import os
import hashlib
import subprocess
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from decide_me.events import build_event, new_tx_id, utc_now, validate_event
from decide_me.projections import apply_events_to_bundle, project_head_after_event, rebuild_projections
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
CONTROL_EVENT_TYPES = {"transaction_rejected"}
RUNTIME_INDEX_SCHEMA_VERSION = 1
EVENT_DISCOVERY_ENV = "DECIDE_ME_EVENT_DISCOVERY"


class _ShellEventDiscoveryFailed(StateValidationError):
    pass


@dataclass(frozen=True)
class RuntimePaths:
    ai_dir: Path
    events_dir: Path
    system_events_dir: Path
    session_events_dir: Path
    project_state: Path
    taxonomy_state: Path
    sessions_dir: Path
    runtime_index: Path
    session_graph_cache: Path
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
        runtime_index=root / "runtime-index.json",
        session_graph_cache=root / "session-graph-cache.json",
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
    for path in _event_files(paths):
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
    _reject_legacy_event_log(paths)
    bundle = _load_projection_bundle(paths)
    runtime_index = _load_runtime_index(paths)
    _validate_runtime_index(paths, bundle, runtime_index)
    validate_projection_bundle(bundle)
    return bundle


def _load_projection_bundle(paths: RuntimePaths) -> dict[str, Any]:
    project_state = load_json_if_exists(paths.project_state)
    taxonomy_state = load_json_if_exists(paths.taxonomy_state)
    if project_state is None:
        raise StateValidationError("missing project-state.json; run rebuild-projections")
    if taxonomy_state is None:
        raise StateValidationError("missing taxonomy-state.json; run rebuild-projections")
    sessions = {
        path.stem: load_json(path)
        for path in sorted(paths.sessions_dir.glob("*.json"))
        if path.is_file()
    }
    return {
        "project_state": project_state,
        "taxonomy_state": taxonomy_state,
        "sessions": sessions,
    }


def _load_runtime_index(paths: RuntimePaths) -> dict[str, Any]:
    index = load_json_if_exists(paths.runtime_index)
    if index is None:
        raise StateValidationError("missing runtime-index.json; run rebuild-projections")
    if not isinstance(index, dict):
        raise StateValidationError("runtime-index.json must contain an object")
    return index


def bootstrap_runtime(
    ai_dir: str | Path,
    *,
    project_name: str,
    objective: str,
    current_milestone: str,
    stop_rule: str | None = None,
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
        _write_projections_and_index(paths, bundle, effective_events=[event], rejected_tx_ids=set())
        return bundle


def rebuild_and_persist(ai_dir: str | Path) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        raw_events = read_raw_event_log(paths)
        events = effective_events_from_raw(raw_events)
        validate_event_log(events)
        bundle = rebuild_projections(events)
        validate_projection_bundle(bundle)
        _write_projections_and_index(
            paths,
            bundle,
            effective_events=events,
            rejected_tx_ids=rejected_transaction_ids(raw_events),
        )
        return bundle


def compact_runtime(ai_dir: str | Path) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        raw_events = read_raw_event_log(paths)
        events = effective_events_from_raw(raw_events)
        validate_event_log(events)
        rebuilt = rebuild_projections(events)
        validate_projection_bundle(rebuilt)

        issues = _projection_mismatch_issues(paths, rebuilt)
        if issues:
            raise StateValidationError("cannot compact invalid runtime: " + "; ".join(issues))

        _write_projections_and_index(
            paths,
            rebuilt,
            effective_events=events,
            rejected_tx_ids=rejected_transaction_ids(raw_events),
        )
        return _load_runtime_index(paths)


def benchmark_runtime(ai_dir: str | Path) -> dict[str, Any]:
    if os.environ.get("DECIDE_ME_PERF") != "1":
        return {
            "status": "skipped",
            "reason": "set DECIDE_ME_PERF=1 to run runtime performance checks",
        }
    paths = runtime_paths(ai_dir)
    started = time.perf_counter()
    bundle = load_runtime(paths)
    load_runtime_seconds = time.perf_counter() - started
    return {
        "status": "ok",
        "load_runtime_seconds": load_runtime_seconds,
        "event_count": bundle["project_state"]["state"]["event_count"],
        "session_count": len(bundle["sessions"]),
        "decision_count": len(
            [
                item
                for item in bundle["project_state"]["objects"]
                if item.get("type") == "decision"
            ]
        ),
    }


def validate_runtime(ai_dir: str | Path, *, full: bool = True) -> list[str]:
    paths = runtime_paths(ai_dir)
    if not full:
        return _validate_runtime_light(paths)
    return _validate_runtime_full(paths)


def _validate_runtime_light(paths: RuntimePaths) -> list[str]:
    issues: list[str] = []
    try:
        _reject_legacy_event_log(paths)
        if not paths.runtime_index.exists():
            return _validate_runtime_full(paths)
        bundle = _load_projection_bundle(paths)
        runtime_index = _load_runtime_index(paths)
        _validate_runtime_index(paths, bundle, runtime_index)
        validate_projection_bundle(bundle)
        issues.extend(_domain_pack_registry_issues(paths, bundle))
    except (StateValidationError, ValueError) as exc:
        issues.append(str(exc))
    return issues


def _validate_runtime_full(paths: RuntimePaths) -> list[str]:
    issues: list[str] = []
    try:
        raw_events = read_raw_event_log(paths)
        events = effective_events_from_raw(raw_events)
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
    issues.extend(_domain_pack_registry_issues(paths, rebuilt))

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

    expected_index = _build_runtime_index(
        paths,
        rebuilt,
        effective_events=events,
        rejected_tx_ids=rejected_transaction_ids(raw_events),
    )
    persisted_index = load_json_if_exists(paths.runtime_index)
    if persisted_index is None:
        issues.append("missing runtime-index.json")
    elif _canonical_json(persisted_index) != _canonical_json(expected_index):
        issues.append("runtime-index.json does not match the event log")

    return issues


def _domain_pack_registry_issues(paths: RuntimePaths, bundle: dict[str, Any]) -> list[str]:
    from decide_me.domains import load_domain_registry

    try:
        registry = load_domain_registry(paths.ai_dir)
    except ValueError as exc:
        return [str(exc)]

    issues: list[str] = []
    for session_id, session in bundle["sessions"].items():
        issues.extend(
            _domain_pack_metadata_issues(
                registry,
                session.get("classification", {}),
                f"session {session_id}.classification",
            )
        )

    for obj in bundle["project_state"]["objects"]:
        if obj.get("type") != "decision":
            continue
        metadata = obj.get("metadata", {})
        label = f"decision object {obj.get('id', '?')}.metadata"
        metadata_issues = _domain_pack_metadata_issues(registry, metadata, label)
        issues.extend(metadata_issues)
        if metadata_issues or "domain_pack_id" not in metadata:
            continue

        decision_type_id = metadata.get("domain_decision_type")
        if decision_type_id is None:
            if "domain_criteria" in metadata:
                issues.append(f"{label}.domain_criteria requires domain_decision_type")
            continue

        try:
            spec = registry.decision_type(metadata["domain_pack_id"], decision_type_id)
        except KeyError as exc:
            issues.append(f"{label}.domain_decision_type {decision_type_id} is not defined: {exc}")
            continue

        if "domain_criteria" not in metadata:
            issues.append(f"{label}.domain_criteria is required for domain_decision_type {decision_type_id}")
        elif list(metadata["domain_criteria"]) != list(spec.criteria):
            issues.append(
                f"{label}.domain_criteria does not match domain decision type {decision_type_id}"
            )
    return issues


def _domain_pack_metadata_issues(
    registry: Any,
    metadata: dict[str, Any],
    label: str,
) -> list[str]:
    from decide_me.domains import domain_pack_digest

    pack_metadata_keys = ("domain_pack_id", "domain_pack_version", "domain_pack_digest")
    present = [key for key in pack_metadata_keys if key in metadata]
    if present and len(present) != len(pack_metadata_keys):
        missing = sorted(set(pack_metadata_keys) - set(present))
        return [f"{label} has incomplete domain pack metadata; missing: {', '.join(missing)}"]
    if not present:
        return []

    pack_id = metadata.get("domain_pack_id")
    try:
        pack = registry.get(pack_id)
    except KeyError as exc:
        return [f"{label}.domain_pack_id is not defined: {exc}"]

    issues: list[str] = []
    if metadata.get("domain_pack_version") != pack.version:
        issues.append(
            f"{label}.domain_pack_version mismatch for domain pack {pack_id}; "
            f"expected {pack.version}, got {metadata.get('domain_pack_version')}"
        )
    expected_digest = domain_pack_digest(pack)
    if metadata.get("domain_pack_digest") != expected_digest:
        issues.append(
            f"{label}.domain_pack_digest mismatch for domain pack {pack_id}; "
            f"expected {expected_digest}, got {metadata.get('domain_pack_digest')}"
        )
    return issues


def _projection_mismatch_issues(paths: RuntimePaths, rebuilt: dict[str, Any]) -> list[str]:
    issues: list[str] = []
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

    for session_id in sorted(set(session_files) - set(rebuilt["sessions"])):
        issues.append(f"stale session projection exists for {session_id}")
    return issues


EventSpec = dict[str, Any]
Builder = Callable[[dict[str, Any]], list[EventSpec]]


def transact(ai_dir: str | Path, builder: Builder) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        current_bundle = load_runtime(paths)
        validate_projection_bundle(current_bundle)
        runtime_index = _load_runtime_index(paths)

        specs = builder(current_bundle)
        if not specs:
            return [], current_bundle

        tx_id = new_tx_id()
        tx_timestamp = _next_transaction_timestamp(runtime_index, utc_now())
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
                    event_id=spec.get("event_id"),
                    project_head=current_bundle["project_state"]["state"]["project_head"],
                )
            )

        built_events = canonicalize_events(built_events)
        _validate_incremental_session_scope(current_bundle, built_events)
        _validate_incremental_events(runtime_index, built_events)
        new_bundle = apply_events_to_bundle(deepcopy(current_bundle), built_events)
        validate_projection_bundle(new_bundle)
        _write_transaction(paths, built_events)
        _write_projections_and_index(
            paths,
            new_bundle,
            last_event_sort_key=event_sort_key(built_events[-1]),
            rejected_tx_ids=set(runtime_index.get("rejected_tx_ids", [])),
        )
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


def event_sort_key(event: dict[str, Any]) -> list[Any]:
    return list(_canonical_event_sort_key(event))


def _canonical_event_sort_key(event: dict[str, Any]) -> tuple[int, str, str, int, str]:
    return (
        0 if event.get("event_type") == "project_initialized" else 1,
        str(event.get("ts") or ""),
        str(event.get("tx_id") or ""),
        int(event.get("tx_index") or 0),
        str(event.get("event_id") or ""),
    )


def _sort_key_tuple(value: list[Any] | tuple[Any, ...] | None) -> tuple[int, str, str, int, str] | None:
    if value is None:
        return None
    if len(value) != 5:
        raise StateValidationError("runtime-index.last_event_sort_key is malformed")
    return (int(value[0]), str(value[1]), str(value[2]), int(value[3]), str(value[4]))


def _validate_incremental_events(runtime_index: dict[str, Any], events: list[dict[str, Any]]) -> None:
    if not events:
        return
    tx_ids = {event["tx_id"] for event in events}
    session_ids = {event["session_id"] for event in events}
    if len(tx_ids) != 1 or len(session_ids) != 1:
        raise StateValidationError("transaction events must share one tx_id and session_id")
    tx_size = len(events)
    tx_indexes = sorted(event["tx_index"] for event in events)
    if tx_indexes != list(range(1, tx_size + 1)):
        raise StateValidationError("transaction tx_index values must be contiguous")
    if any(event["tx_size"] != tx_size for event in events):
        raise StateValidationError("transaction tx_size does not match event count")
    if any(event["event_type"] == "transaction_rejected" for event in events):
        raise StateValidationError("transaction_rejected requires rebuild-projections after writing")
    last_sort_key = _sort_key_tuple(runtime_index.get("last_event_sort_key"))
    if last_sort_key is None:
        return
    for event in events:
        if _canonical_event_sort_key(event) <= last_sort_key:
            raise StateValidationError("incremental transaction is not after the current checkpoint")


def _validate_incremental_session_scope(bundle: dict[str, Any], events: list[dict[str, Any]]) -> None:
    sessions = bundle.get("sessions", {})
    for event in events:
        event_type = event["event_type"]
        session_id = event["session_id"]
        if event_type in {"project_initialized", "plan_generated"}:
            if session_id != SYSTEM_SESSION_ID:
                raise StateValidationError(f"{event_type} must use SYSTEM session_id")
            continue
        if event_type == "session_created":
            payload_session_id = event["payload"]["session"]["id"]
            if session_id != payload_session_id:
                raise StateValidationError("session_created event.session_id must match payload.session.id")
            if session_id in sessions:
                raise StateValidationError(f"duplicate session_created id: {session_id}")
            continue
        if session_id == SYSTEM_SESSION_ID:
            raise StateValidationError(f"{event_type} must not use SYSTEM session_id")
        session = sessions.get(session_id)
        if session is None:
            raise StateValidationError(f"event references unknown session: {session_id}")
        if session["session"]["lifecycle"]["status"] == "closed":
            raise StateValidationError(f"{event_type} mutates closed session {session_id}")


def _next_transaction_timestamp(runtime_index: dict[str, Any], candidate: str) -> str:
    last_sort_key = _sort_key_tuple(runtime_index.get("last_event_sort_key"))
    if last_sort_key is None:
        return candidate
    last_timestamp = last_sort_key[1]
    if candidate > last_timestamp:
        return candidate
    try:
        parsed = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return candidate
    return (parsed + timedelta(microseconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _event_files(paths: RuntimePaths) -> list[Path]:
    if not paths.events_dir.exists():
        return []
    mode = os.environ.get(EVENT_DISCOVERY_ENV, "auto").strip().casefold() or "auto"
    if mode == "python":
        return _python_event_files(paths)
    if mode == "shell":
        return _shell_event_files(paths)
    if mode == "auto":
        try:
            return _shell_event_files(paths)
        except _ShellEventDiscoveryFailed:
            return _python_event_files(paths)
    raise StateValidationError(f"{EVENT_DISCOVERY_ENV} must be one of: auto, python, shell")


def _python_event_files(paths: RuntimePaths) -> list[Path]:
    return sorted(path for path in paths.events_dir.rglob("*.jsonl") if path.is_file())


def _shell_event_files(paths: RuntimePaths) -> list[Path]:
    try:
        completed = subprocess.run(
            ["find", str(paths.events_dir), "-type", "f", "-name", "*.jsonl", "-print0"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise _ShellEventDiscoveryFailed(f"shell event discovery failed: {exc}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise _ShellEventDiscoveryFailed(f"shell event discovery failed with exit code {completed.returncode}{detail}")

    events_root = paths.events_dir.resolve()
    event_files: list[Path] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            discovered = Path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise StateValidationError("shell event discovery returned a non-UTF-8 path") from exc

        resolved = discovered.resolve()
        try:
            relative = resolved.relative_to(events_root)
        except ValueError as exc:
            raise StateValidationError("shell event discovery returned a path outside events/") from exc

        path = paths.events_dir / relative
        if path.is_file():
            event_files.append(path)
    return sorted(event_files)


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


def _write_projections_and_index(
    paths: RuntimePaths,
    bundle: dict[str, Any],
    *,
    effective_events: list[dict[str, Any]] | None = None,
    last_event_sort_key: list[Any] | None = None,
    rejected_tx_ids: set[str],
) -> None:
    _write_projections(paths, bundle)
    runtime_index = _build_runtime_index(
        paths,
        bundle,
        effective_events=effective_events,
        last_event_sort_key=last_event_sort_key,
        rejected_tx_ids=rejected_tx_ids,
    )
    _write_runtime_index(paths, runtime_index)


def _build_runtime_index(
    paths: RuntimePaths,
    bundle: dict[str, Any],
    *,
    effective_events: list[dict[str, Any]] | None = None,
    last_event_sort_key: list[Any] | None = None,
    rejected_tx_ids: set[str],
) -> dict[str, Any]:
    project_state = bundle["project_state"]
    state = project_state["state"]
    if effective_events is not None:
        last_event_sort_key = event_sort_key(effective_events[-1]) if effective_events else None
    if last_event_sort_key is None and state.get("last_event_id") is not None:
        existing = load_json_if_exists(paths.runtime_index)
        if isinstance(existing, dict):
            last_event_sort_key = existing.get("last_event_sort_key")
    return {
        "schema_version": RUNTIME_INDEX_SCHEMA_VERSION,
        "projection_schema_version": project_state["schema_version"],
        "project_head": state.get("project_head"),
        "event_count": state.get("event_count"),
        "last_event_id": state.get("last_event_id"),
        "last_event_sort_key": last_event_sort_key,
        "rejected_tx_ids": sorted(rejected_tx_ids),
        "projection_files": _projection_manifest(paths),
    }


def _write_runtime_index(paths: RuntimePaths, runtime_index: dict[str, Any]) -> None:
    _atomic_write_json(paths.runtime_index, runtime_index)


def _validate_runtime_index(paths: RuntimePaths, bundle: dict[str, Any], runtime_index: dict[str, Any]) -> None:
    state = bundle["project_state"]["state"]
    if runtime_index.get("schema_version") != RUNTIME_INDEX_SCHEMA_VERSION:
        raise StateValidationError("runtime-index.schema_version must be 1")
    if runtime_index.get("projection_schema_version") != bundle["project_state"].get("schema_version"):
        raise StateValidationError("runtime-index projection_schema_version does not match project-state.json")
    for key in ("project_head", "event_count", "last_event_id"):
        if runtime_index.get(key) != state.get(key):
            raise StateValidationError(f"runtime-index.{key} does not match project-state.json")
    _sort_key_tuple(runtime_index.get("last_event_sort_key"))
    rejected_tx_ids = runtime_index.get("rejected_tx_ids")
    if not isinstance(rejected_tx_ids, list) or any(not isinstance(tx_id, str) for tx_id in rejected_tx_ids):
        raise StateValidationError("runtime-index.rejected_tx_ids must be a list of strings")
    if runtime_index.get("projection_files") != _projection_manifest(paths):
        raise StateValidationError("runtime-index projection file manifest is stale")


def _projection_manifest(paths: RuntimePaths) -> dict[str, dict[str, Any]]:
    files = [paths.project_state, paths.taxonomy_state]
    files.extend(sorted(path for path in paths.sessions_dir.glob("*.json") if path.is_file()))
    manifest: dict[str, dict[str, Any]] = {}
    for path in files:
        if not path.exists():
            continue
        body = path.read_bytes()
        manifest[str(path.relative_to(paths.ai_dir))] = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    return manifest


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
