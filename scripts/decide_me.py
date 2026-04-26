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
from decide_me.conflicts import detect_merge_conflicts, resolve_merge_conflict
from decide_me.exports import (
    export_adr,
    export_decision_register,
    export_github_issues,
    export_github_templates,
    export_structured_adr,
)
from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import close_session, create_session, list_sessions, resume_session, show_session
from decide_me.planner import generate_plan
from decide_me.protocol import invalidate_decision, resolve_decision_supersession
from decide_me.session_graph import (
    detect_session_conflicts,
    link_session,
    resolve_session_conflict,
    show_session_graph,
)
from decide_me.store import benchmark_runtime, bootstrap_runtime, compact_runtime, rebuild_and_persist, validate_runtime


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    if raw_argv and raw_argv[0] == "invalidate-decision":
        return _run_legacy_invalidate(raw_argv[1:])

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
    validate_mode = validate.add_mutually_exclusive_group()
    validate_mode.add_argument(
        "--full",
        action="store_true",
        help="scan the full event log and compare projections (default)",
    )
    validate_mode.add_argument(
        "--cached",
        "--fast",
        dest="cached",
        action="store_true",
        help="validate only the persisted projection checkpoint and runtime index",
    )

    compact = subparsers.add_parser("compact-runtime", help="refresh the projection checkpoint index")
    compact.add_argument("--ai-dir", required=True)

    benchmark = subparsers.add_parser("benchmark-runtime", help="run opt-in runtime performance checks")
    benchmark.add_argument("--ai-dir", required=True)

    detect_conflicts = subparsers.add_parser(
        "detect-merge-conflicts",
        help="detect unresolved same-session transaction merge conflicts",
    )
    detect_conflicts.add_argument("--ai-dir", required=True)

    resolve_conflict = subparsers.add_parser(
        "resolve-merge-conflict",
        help="resolve a same-session transaction merge conflict by rejecting selected transactions",
    )
    resolve_conflict.add_argument("--ai-dir", required=True)
    resolve_conflict.add_argument("--session-id", required=True)
    resolve_conflict.add_argument("--keep-tx-id", required=True)
    resolve_conflict.add_argument("--reject-tx-id", action="append", required=True)
    resolve_conflict.add_argument("--reason", required=True)

    link = subparsers.add_parser("link-session", help="record an explicit semantic parent-child session link")
    link.add_argument("--ai-dir", required=True)
    link.add_argument("--parent-session-id", required=True)
    link.add_argument("--child-session-id", required=True)
    link.add_argument("--relationship", required=True)
    link.add_argument("--reason", required=True)
    link.add_argument("--evidence-ref", action="append", default=[])

    show_graph = subparsers.add_parser("show-session-graph", help="show explicit and inferred session graph context")
    show_graph.add_argument("--ai-dir", required=True)
    show_graph.add_argument("--session-id")
    show_graph.add_argument("--include-inferred", action="store_true")

    detect_session = subparsers.add_parser(
        "detect-session-conflicts",
        help="detect semantic conflicts across explicitly related sessions",
    )
    detect_session.add_argument("--ai-dir", required=True)
    detect_session.add_argument("--session-id", action="append", required=True)
    detect_session.add_argument("--include-related", action="store_true")

    resolve_session = subparsers.add_parser(
        "resolve-session-conflict",
        help="resolve a semantic conflict across explicitly related sessions",
    )
    resolve_session.add_argument("--ai-dir", required=True)
    resolve_session.add_argument("--conflict-id", required=True)
    resolve_session.add_argument("--winning-session-id", required=True)
    resolve_session.add_argument("--reject-session-id", action="append", required=True)
    resolve_session.add_argument("--reason", required=True)

    resolve_supersession = subparsers.add_parser(
        "resolve-decision-supersession",
        aliases=["supersede-decision"],
        help="resolve a decision replacement by choosing the superseding decision",
    )
    resolve_supersession.add_argument("--ai-dir", required=True)
    resolve_supersession.add_argument("--session-id", required=True)
    resolve_supersession.add_argument("--superseded-decision-id", required=True)
    resolve_supersession.add_argument("--superseding-decision-id", required=True)
    resolve_supersession.add_argument("--reason", required=True)
    resolve_supersession.set_defaults(handler_command="resolve-decision-supersession")

    adr = subparsers.add_parser("export-adr", help="export an ADR markdown file")
    adr.add_argument("--ai-dir", required=True)
    adr.add_argument("--decision-id", required=True)

    structured_adr = subparsers.add_parser(
        "export-structured-adr", help="export a structured ADR markdown file"
    )
    structured_adr.add_argument("--ai-dir", required=True)
    structured_adr.add_argument("--decision-id", required=True)
    structured_adr.add_argument("--include-invalidated", action="store_true")

    decision_register = subparsers.add_parser(
        "export-decision-register", help="export the decision register"
    )
    decision_register.add_argument("--ai-dir", required=True)
    decision_register.add_argument("--format", choices=("yaml", "markdown"), default="yaml")
    decision_register.add_argument("--include-invalidated", action="store_true")

    github_templates = subparsers.add_parser(
        "export-github-templates", help="export GitHub issue form templates"
    )
    github_templates.add_argument("--ai-dir", default=".ai/decide-me")
    github_templates.add_argument("--output-dir", required=True)

    github_issues = subparsers.add_parser(
        "export-github-issues", help="export local GitHub issue draft files"
    )
    github_issues.add_argument("--ai-dir", required=True)
    github_issues.add_argument("--session-id", action="append", required=True)
    github_issues.add_argument("--output-dir", required=True)

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

    args = parser.parse_args(raw_argv)

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
            issues = validate_runtime(args.ai_dir, full=not args.cached)
            _print_json({"ok": not issues, "issues": issues})
            return 0 if not issues else 1
        elif args.command == "compact-runtime":
            _print_json(compact_runtime(args.ai_dir))
        elif args.command == "benchmark-runtime":
            _print_json(benchmark_runtime(args.ai_dir))
        elif args.command == "detect-merge-conflicts":
            conflicts = detect_merge_conflicts(args.ai_dir)
            _print_json({"ok": not conflicts, "conflicts": conflicts})
            return 0
        elif args.command == "resolve-merge-conflict":
            _print_json(
                resolve_merge_conflict(
                    args.ai_dir,
                    session_id=args.session_id,
                    keep_tx_id=args.keep_tx_id,
                    reject_tx_ids=args.reject_tx_id,
                    reason=args.reason,
                )
            )
        elif args.command == "link-session":
            _print_json(
                link_session(
                    args.ai_dir,
                    parent_session_id=args.parent_session_id,
                    child_session_id=args.child_session_id,
                    relationship=args.relationship,
                    reason=args.reason,
                    evidence_refs=args.evidence_ref,
                )
            )
        elif args.command == "show-session-graph":
            _print_json(
                show_session_graph(
                    args.ai_dir,
                    session_id=args.session_id,
                    include_inferred=args.include_inferred,
                )
            )
        elif args.command == "detect-session-conflicts":
            _print_json(
                detect_session_conflicts(
                    args.ai_dir,
                    session_ids=args.session_id,
                    include_related=args.include_related,
                )
            )
        elif args.command == "resolve-session-conflict":
            _print_json(
                resolve_session_conflict(
                    args.ai_dir,
                    conflict_id=args.conflict_id,
                    winning_session_id=args.winning_session_id,
                    rejected_session_ids=args.reject_session_id,
                    reason=args.reason,
                )
            )
        elif getattr(args, "handler_command", args.command) == "resolve-decision-supersession":
            _print_json(
                resolve_decision_supersession(
                    args.ai_dir,
                    args.session_id,
                    superseded_decision_id=args.superseded_decision_id,
                    superseding_decision_id=args.superseding_decision_id,
                    reason=args.reason,
                )
            )
        elif args.command == "export-adr":
            path = export_adr(args.ai_dir, args.decision_id)
            _print_json({"path": str(path)})
        elif args.command == "export-structured-adr":
            path = export_structured_adr(
                args.ai_dir,
                args.decision_id,
                include_invalidated=args.include_invalidated,
            )
            _print_json({"path": str(path)})
        elif args.command == "export-decision-register":
            path = export_decision_register(
                args.ai_dir,
                format=args.format,
                include_invalidated=args.include_invalidated,
            )
            _print_json({"path": str(path)})
        elif args.command == "export-github-templates":
            paths = export_github_templates(args.output_dir, ai_dir=args.ai_dir)
            _print_json({"paths": [str(path) for path in paths]})
        elif args.command == "export-github-issues":
            path = export_github_issues(args.ai_dir, args.session_id, args.output_dir)
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            _print_json({"path": str(path), "issue_count": len(payload["issues"])})
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
    except Exception as exc:  # pragma: no cover - exercised via CLI integration in real use
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def _run_legacy_invalidate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="legacy alias for resolve-decision-supersession")
    parser.add_argument("--ai-dir", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--invalidated-by", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    try:
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
