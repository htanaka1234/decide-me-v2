#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from decide_me.exports import export_adr
from decide_me.lifecycle import close_session, create_session, list_sessions, resume_session, show_session
from decide_me.planner import generate_plan
from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="decide-me v3 runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="initialize a runtime")
    bootstrap.add_argument("--ai-dir", required=True)
    bootstrap.add_argument("--project-name", required=True)
    bootstrap.add_argument("--objective", required=True)
    bootstrap.add_argument("--current-milestone", default="Current milestone")
    bootstrap.add_argument("--stop-rule")

    create = subparsers.add_parser("create-session", help="create a session")
    create.add_argument("--ai-dir", required=True)
    create.add_argument("--context")

    list_cmd = subparsers.add_parser("list-sessions", help="list sessions")
    list_cmd.add_argument("--ai-dir", required=True)

    show = subparsers.add_parser("show-session", help="show one session")
    show.add_argument("--ai-dir", required=True)
    show.add_argument("--session-id", required=True)

    resume = subparsers.add_parser("resume-session", help="resume a session")
    resume.add_argument("--ai-dir", required=True)
    resume.add_argument("--session-id", required=True)

    close = subparsers.add_parser("close-session", help="close a session")
    close.add_argument("--ai-dir", required=True)
    close.add_argument("--session-id", required=True)

    plan = subparsers.add_parser("generate-plan", help="generate a plan from closed sessions")
    plan.add_argument("--ai-dir", required=True)
    plan.add_argument("--session-id", action="append", required=True)

    rebuild = subparsers.add_parser("rebuild-projections", help="rebuild derived state")
    rebuild.add_argument("--ai-dir", required=True)

    validate = subparsers.add_parser("validate-state", help="validate runtime consistency")
    validate.add_argument("--ai-dir", required=True)

    adr = subparsers.add_parser("export-adr", help="export an ADR markdown file")
    adr.add_argument("--ai-dir", required=True)
    adr.add_argument("--decision-id", required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "bootstrap":
            result = bootstrap_runtime(
                args.ai_dir,
                project_name=args.project_name,
                objective=args.objective,
                current_milestone=args.current_milestone,
                stop_rule=args.stop_rule,
            )
            _print_json(result)
        elif args.command == "create-session":
            _print_json(create_session(args.ai_dir, context=args.context))
        elif args.command == "list-sessions":
            _print_json(list_sessions(args.ai_dir))
        elif args.command == "show-session":
            _print_json(show_session(args.ai_dir, args.session_id))
        elif args.command == "resume-session":
            _print_json(resume_session(args.ai_dir, args.session_id))
        elif args.command == "close-session":
            _print_json(close_session(args.ai_dir, args.session_id))
        elif args.command == "generate-plan":
            _print_json(generate_plan(args.ai_dir, args.session_id))
        elif args.command == "rebuild-projections":
            _print_json(rebuild_and_persist(args.ai_dir))
        elif args.command == "validate-state":
            issues = validate_runtime(args.ai_dir)
            _print_json({"ok": not issues, "issues": issues})
            return 0 if not issues else 1
        elif args.command == "export-adr":
            path = export_adr(args.ai_dir, args.decision_id)
            _print_json({"path": str(path)})
    except Exception as exc:  # pragma: no cover - exercised via CLI integration in real use
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
