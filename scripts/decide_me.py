#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT_STR = str(REPO_ROOT)
sys.path = [entry for entry in sys.path if entry != REPO_ROOT_STR]
sys.path.insert(0, REPO_ROOT_STR)

from decide_me.classification import classify_session
from decide_me.exports import export_adr
from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import close_session, create_session, list_sessions, resume_session, show_session
from decide_me.planner import generate_plan
from decide_me.protocol import invalidate_decision
from decide_me.store import bootstrap_runtime, rebuild_and_persist, validate_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="decide-me v2 runtime CLI")
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
    list_cmd.add_argument("--query")
    list_cmd.add_argument("--status", action="append", default=[])
    list_cmd.add_argument("--domain", action="append", default=[])
    list_cmd.add_argument("--abstraction-level", action="append", default=[])
    list_cmd.add_argument("--tag", action="append", default=[])

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

    classify = subparsers.add_parser("classify-session", help="classify a session deterministically")
    classify.add_argument("--ai-dir", required=True)
    classify.add_argument("--session-id", required=True)
    classify.add_argument("--domain")
    classify.add_argument("--abstraction-level")
    classify.add_argument("--candidate-term", action="append", default=[])
    classify.add_argument("--source-ref", action="append", default=[])
    classify.add_argument("--reason", default="classification-updated")

    advance = subparsers.add_parser("advance-session", help="advance a session by evidence scan and question selection")
    advance.add_argument("--ai-dir", required=True)
    advance.add_argument("--session-id", required=True)
    advance.add_argument("--repo-root", default=".")
    advance.add_argument("--max-auto-resolutions", type=int, default=20)

    reply = subparsers.add_parser("handle-reply", help="process a user reply and advance the session")
    reply.add_argument("--ai-dir", required=True)
    reply.add_argument("--session-id", required=True)
    reply.add_argument("--reply", required=True)
    reply.add_argument("--repo-root", default=".")

    invalidate = subparsers.add_parser("invalidate-decision", help="invalidate a decision explicitly")
    invalidate.add_argument("--ai-dir", required=True)
    invalidate.add_argument("--session-id", required=True)
    invalidate.add_argument("--decision-id", required=True)
    invalidate.add_argument("--invalidated-by", required=True)
    invalidate.add_argument("--reason", required=True)

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
            _print_json(
                list_sessions(
                    args.ai_dir,
                    query=args.query,
                    statuses=args.status,
                    domains=args.domain,
                    abstraction_levels=args.abstraction_level,
                    tag_terms=args.tag,
                )
            )
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
        elif args.command == "classify-session":
            _print_json(
                classify_session(
                    args.ai_dir,
                    args.session_id,
                    domain=args.domain,
                    abstraction_level=args.abstraction_level,
                    candidate_terms=args.candidate_term,
                    source_refs=args.source_ref,
                    reason=args.reason,
                )
            )
        elif args.command == "advance-session":
            _print_json(
                advance_session(
                    args.ai_dir,
                    args.session_id,
                    repo_root=args.repo_root,
                    max_auto_resolutions=args.max_auto_resolutions,
                )
            )
        elif args.command == "handle-reply":
            _print_json(
                handle_reply(
                    args.ai_dir,
                    args.session_id,
                    args.reply,
                    repo_root=args.repo_root,
                )
            )
        elif args.command == "invalidate-decision":
            _print_json(
                invalidate_decision(
                    args.ai_dir,
                    args.session_id,
                    decision_id=args.decision_id,
                    invalidated_by_decision_id=args.invalidated_by,
                    reason=args.reason,
                )
            )
    except Exception as exc:  # pragma: no cover - exercised via CLI integration in real use
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
