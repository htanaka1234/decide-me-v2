from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from decide_me.events import EVENT_TYPES
from decide_me.protocol import discover_decision
from decide_me.store import load_runtime, read_event_log, runtime_paths


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "decide_me.py"


def run_cli(*args: str, cwd: str | Path = REPO_ROOT) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        env=_env(),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return json.loads(result.stdout)


def bootstrap_cli(ai_dir: Path, *, objective: str = "Exercise Phase 5 runtime gate.") -> dict[str, Any]:
    return run_cli(
        "bootstrap",
        "--ai-dir",
        str(ai_dir),
        "--project-name",
        "Demo",
        "--objective",
        objective,
        "--current-milestone",
        "Phase 5 completion gate",
    )


def create_session_cli(ai_dir: Path, *, context: str = "Object runtime gate") -> str:
    payload = run_cli("create-session", "--ai-dir", str(ai_dir), "--context", context)
    return payload["session"]["id"]


def seed_p0_decision(
    ai_dir: Path,
    session_id: str,
    *,
    decision_id: str = "D-auth",
    title: str = "Auth mode",
    domain: str = "technical",
    question: str = "How should users sign in?",
) -> dict[str, Any]:
    return discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": decision_id,
            "title": title,
            "priority": "P0",
            "frontier": "now",
            "domain": domain,
            "resolvable_by": "human",
            "question": question,
        },
    )


def advance_session_cli(ai_dir: Path, session_id: str, repo_root: Path) -> dict[str, Any]:
    return run_cli(
        "advance-session",
        "--ai-dir",
        str(ai_dir),
        "--session-id",
        session_id,
        "--repo-root",
        str(repo_root),
    )


def handle_reply_cli(ai_dir: Path, session_id: str, reply: str, repo_root: Path) -> dict[str, Any]:
    return run_cli(
        "handle-reply",
        "--ai-dir",
        str(ai_dir),
        "--session-id",
        session_id,
        "--reply",
        reply,
        "--repo-root",
        str(repo_root),
    )


def close_session_cli(ai_dir: Path, session_id: str) -> dict[str, Any]:
    return run_cli("close-session", "--ai-dir", str(ai_dir), "--session-id", session_id)


def generate_plan_cli(ai_dir: Path, session_id: str) -> dict[str, Any]:
    return run_cli("generate-plan", "--ai-dir", str(ai_dir), "--session-id", session_id)


def rebuild_cli(ai_dir: Path) -> dict[str, Any]:
    return run_cli("rebuild-projections", "--ai-dir", str(ai_dir))


def validate_cli(ai_dir: Path) -> dict[str, Any]:
    return run_cli("validate-state", "--ai-dir", str(ai_dir))


def complete_ok_runtime(ai_dir: Path, repo_root: Path) -> dict[str, Any]:
    bootstrap_cli(ai_dir)
    session_id = create_session_cli(ai_dir)
    seed_p0_decision(ai_dir, session_id)
    question_turn = advance_session_cli(ai_dir, session_id, repo_root)
    accepted = handle_reply_cli(ai_dir, session_id, "OK", repo_root)
    closed = close_session_cli(ai_dir, session_id)
    plan = generate_plan_cli(ai_dir, session_id)
    validation = validate_cli(ai_dir)
    return {
        "session_id": session_id,
        "question_turn": question_turn,
        "accepted": accepted,
        "closed": closed,
        "plan": plan,
        "validation": validation,
    }


def load_bundle(ai_dir: Path) -> dict[str, Any]:
    return load_runtime(runtime_paths(ai_dir))


def event_types(ai_dir: Path) -> list[str]:
    return [event["event_type"] for event in events(ai_dir)]


def events(ai_dir: Path) -> list[dict[str, Any]]:
    return read_event_log(runtime_paths(ai_dir))


def assert_domain_neutral_event_types(testcase: Any, ai_dir: Path) -> None:
    testcase.assertTrue(set(event_types(ai_dir)).issubset(EVENT_TYPES))


def object_runtime_snapshot(ai_dir: Path, session_id: str) -> dict[str, Any]:
    bundle = load_bundle(ai_dir)
    return {
        "objects": sorted(bundle["project_state"]["objects"], key=lambda item: item["id"]),
        "links": sorted(bundle["project_state"]["links"], key=lambda item: item["id"]),
        "close_summary": bundle["sessions"][session_id]["close_summary"],
    }


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


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env
