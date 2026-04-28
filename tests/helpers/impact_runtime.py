from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, rebuild_and_persist, transact


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "decide_me.py"


def build_impact_runtime(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Harden Phase 6 graph and impact regressions.",
        current_milestone="Phase 6-6",
    )
    session = create_session(str(ai_dir), context="Phase 6 graph impact gate")
    session_id = session["session"]["id"]
    transact(ai_dir, lambda _bundle: _events(session_id))
    rebuild_and_persist(ai_dir)
    return ai_dir


def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"CLI failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def run_json_cli(*args: str) -> dict[str, Any]:
    return json.loads(run_cli(*args).stdout)


def runtime_state_snapshot(ai_dir: Path) -> dict[str, str]:
    paths: list[Path] = []
    paths.extend(sorted((ai_dir / "events").rglob("*.jsonl")))
    for path in (
        ai_dir / "project-state.json",
        ai_dir / "taxonomy-state.json",
        ai_dir / "runtime-index.json",
        ai_dir / "session-graph-cache.json",
    ):
        if path.exists():
            paths.append(path)
    sessions_dir = ai_dir / "sessions"
    if sessions_dir.exists():
        paths.extend(sorted(sessions_dir.glob("*.json")))
    return _hash_snapshot(ai_dir, paths)


def event_hash_snapshot(ai_dir: Path) -> dict[str, str]:
    return _hash_snapshot(ai_dir, sorted((ai_dir / "events").rglob("*.jsonl")))


def tree_hash_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return _hash_snapshot(root, sorted(path for path in root.rglob("*") if path.is_file()))


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def only_impact_export_paths(paths: list[str]) -> bool:
    return all(path.startswith("exports/impact/") and path.endswith(".md") for path in paths)


def semantic_impact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": payload["summary"],
        "affected_objects": payload["affected_objects"],
        "affected_links": payload["affected_links"],
        "paths": payload["paths"],
    }


def semantic_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "impact_summary": payload["impact_summary"],
        "candidates": payload["candidates"],
    }


def semantic_bounded_graph(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": payload["nodes"],
        "edges": payload["edges"],
    }


def object_ids(payload: dict[str, Any], key: str) -> list[str]:
    return [item["object_id"] for item in payload[key]]


def edge_ids(payload: dict[str, Any]) -> list[str]:
    return [item["link_id"] for item in payload["edges"]]


def candidate_target_ids(payload: dict[str, Any]) -> list[str]:
    return [item["target_object_id"] for item in payload["candidates"]]


def delete_derived_projection_files(ai_dir: Path) -> None:
    for path in (
        ai_dir / "project-state.json",
        ai_dir / "taxonomy-state.json",
        ai_dir / "runtime-index.json",
        ai_dir / "session-graph-cache.json",
    ):
        if path.exists():
            path.unlink()
    sessions_dir = ai_dir / "sessions"
    if sessions_dir.exists():
        for path in sessions_dir.glob("*.json"):
            path.unlink()


def load_schema(relative_path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _events(session_id: str) -> list[dict[str, Any]]:
    object_specs = [
        ("E-objective", "OBJ-001", "objective", "active", {}),
        ("E-constraint", "CON-001", "constraint", "active", {}),
        ("E-decision", "DEC-001", "decision", "accepted", {"priority": "P0", "frontier": "now"}),
        ("E-action", "ACT-001", "action", "active", {}),
        ("E-verification", "VER-001", "verification", "active", {}),
        ("E-risk", "RISK-001", "risk", "active", {}),
        ("E-dependent-decision", "DEC-002", "decision", "unresolved", {"priority": "P1", "frontier": "later"}),
        ("E-proposal", "PROP-001", "proposal", "invalidated", {}),
        ("E-option", "OPT-001", "option", "invalidated", {}),
    ]
    link_specs = [
        ("E-link-objective-decision", "L-OBJ-001-constrains-DEC-001", "OBJ-001", "constrains", "DEC-001"),
        ("E-link-constraint-decision", "L-CON-001-constrains-DEC-001", "CON-001", "constrains", "DEC-001"),
        ("E-link-action-decision", "L-ACT-001-addresses-DEC-001", "ACT-001", "addresses", "DEC-001"),
        ("E-link-verification-action", "L-VER-001-verifies-ACT-001", "VER-001", "verifies", "ACT-001"),
        ("E-link-dependent-decision", "L-DEC-002-depends-on-DEC-001", "DEC-002", "depends_on", "DEC-001"),
        ("E-link-action-risk", "L-ACT-001-mitigates-RISK-001", "ACT-001", "mitigates", "RISK-001"),
        ("E-link-proposal-decision", "L-PROP-001-addresses-DEC-001", "PROP-001", "addresses", "DEC-001"),
        ("E-link-proposal-option", "L-PROP-001-recommends-OPT-001", "PROP-001", "recommends", "OPT-001"),
        ("E-link-decision-proposal", "L-DEC-001-accepts-PROP-001", "DEC-001", "accepts", "PROP-001"),
    ]
    return [
        {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": "object_recorded",
            "payload": {"object": _object(object_id, object_type, event_id, status=status, metadata=metadata)},
        }
        for event_id, object_id, object_type, status, metadata in object_specs
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
    event_id: str,
    *,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Phase 6-6 graph impact regression fixture object.",
        "status": status,
        "created_at": "2026-04-28T00:00:00Z",
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
        "rationale": "Phase 6-6 graph impact regression fixture link.",
        "created_at": "2026-04-28T00:00:00Z",
        "source_event_ids": [event_id],
    }


def _hash_snapshot(root: Path, paths: list[Path]) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env
