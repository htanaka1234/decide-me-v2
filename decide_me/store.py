from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from decide_me.events import build_event, utc_now
from decide_me.projections import rebuild_projections
from decide_me.validate import StateValidationError, validate_event_log, validate_projection_bundle

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


SYSTEM_SESSION_ID = "SYSTEM"


@dataclass(frozen=True)
class RuntimePaths:
    ai_dir: Path
    event_log: Path
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
        event_log=root / "event-log.jsonl",
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


def read_event_log(paths: RuntimePaths) -> list[dict[str, Any]]:
    if not paths.event_log.exists():
        return []
    events: list[dict[str, Any]] = []
    with paths.event_log.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                events.append(json.loads(stripped))
    return events


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
    if paths.event_log.exists() and paths.event_log.read_text(encoding="utf-8").strip():
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
                "project-version-changed",
                "session-boundary",
                "superseded-proposal",
                "decision-invalidated",
                "session-closed",
            ],
            "close_policy": "generate-close-summary-on-close",
        },
        "default_bundles": default_bundles or [],
    }
    event = build_event(
        sequence=1,
        session_id=SYSTEM_SESSION_ID,
        event_type="project_initialized",
        project_version_after=1,
        payload=payload,
        timestamp=utc_now(),
    )
    bundle = rebuild_projections([event])
    validate_projection_bundle(bundle)
    _write_runtime(paths, [event], bundle)
    return bundle


def rebuild_and_persist(ai_dir: str | Path) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    ensure_runtime_dirs(paths)
    with _write_lock(paths.lock_path):
        events = read_event_log(paths)
        validate_event_log(events)
        bundle = rebuild_projections(events)
        validate_projection_bundle(bundle)
        _write_runtime(paths, events, bundle)
        return bundle


def validate_runtime(ai_dir: str | Path) -> list[str]:
    paths = runtime_paths(ai_dir)
    issues: list[str] = []
    events = read_event_log(paths)
    try:
        validate_event_log(events)
    except (StateValidationError, ValueError) as exc:
        issues.append(str(exc))
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

        next_sequence = len(existing_events) + 1
        current_version = current_bundle["project_state"]["state"]["project_version"]
        new_events = list(existing_events)

        for offset, spec in enumerate(specs, start=1):
            new_events.append(
                build_event(
                    sequence=next_sequence,
                    session_id=spec.get("session_id", SYSTEM_SESSION_ID),
                    event_type=spec["event_type"],
                    project_version_after=current_version + offset,
                    payload=spec["payload"],
                    timestamp=spec.get("ts"),
                )
            )
            next_sequence += 1

        validate_event_log(new_events)
        new_bundle = rebuild_projections(new_events)
        validate_projection_bundle(new_bundle)
        _write_runtime(paths, new_events, new_bundle)
        return new_events[len(existing_events) :], new_bundle


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


def _write_runtime(paths: RuntimePaths, events: list[dict[str, Any]], bundle: dict[str, Any]) -> None:
    ensure_runtime_dirs(paths)
    _atomic_write_text(
        paths.event_log,
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
    )
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
