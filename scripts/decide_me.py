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

from decide_me.conflicts import detect_merge_conflicts, resolve_merge_conflict
from decide_me.exports import (
    export_adr,
    export_agent_instructions,
    export_architecture_doc,
    export_decision_register,
    export_github_issues,
    export_github_templates,
    export_impact_report,
    export_structured_adr,
    export_traceability,
    export_verification_gaps,
)
from decide_me.graph_traversal import bounded_subgraph, build_graph_index
from decide_me.impact_analysis import CHANGE_KINDS, analyze_impact
from decide_me.interview import advance_session, handle_reply
from decide_me.invalidation_candidates import generate_invalidation_candidates
from decide_me.lifecycle import close_session, create_session, list_sessions, resume_session, show_session
from decide_me.planner import generate_plan
from decide_me.protocol import resolve_decision_supersession
from decide_me.registers import build_assumption_register, build_evidence_register, build_risk_register
from decide_me.session_graph import (
    detect_session_conflicts,
    show_session_graph,
)
from decide_me.store import (
    benchmark_runtime,
    bootstrap_runtime,
    compact_runtime,
    load_runtime,
    rebuild_and_persist,
    runtime_paths,
    validate_runtime,
)


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)

    parser = argparse.ArgumentParser(description="decide-me v2 object/link runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="initialize an object/link runtime")
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

    close = subparsers.add_parser("close-session", help="close a session and emit object/link summary refs")
    close.add_argument("--ai-dir", required=True)
    close.add_argument("--session-id", required=True)

    plan = subparsers.add_parser("generate-plan", help="generate actions from closed object/link sessions")
    plan.add_argument("--ai-dir", required=True)
    plan.add_argument("--session-id", action="append", required=True)

    rebuild = subparsers.add_parser("rebuild-projections", help="rebuild object/link projections")
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

    compact = subparsers.add_parser("compact-runtime", help="refresh the object/link projection checkpoint index")
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

    resolve_supersession = subparsers.add_parser(
        "resolve-decision-supersession",
        help="resolve a decision replacement by choosing the superseding decision",
    )
    resolve_supersession.add_argument("--ai-dir", required=True)
    resolve_supersession.add_argument("--session-id", required=True)
    resolve_supersession.add_argument("--superseded-decision-id", required=True)
    resolve_supersession.add_argument("--superseding-decision-id", required=True)
    resolve_supersession.add_argument("--reason", required=True)
    resolve_supersession.set_defaults(handler_command="resolve-decision-supersession")

    show_impact = subparsers.add_parser("show-impact", help="show read-only impact analysis for an object")
    show_impact.add_argument("--ai-dir", required=True)
    show_impact.add_argument("--object-id", required=True)
    show_impact.add_argument("--change-kind", required=True, choices=sorted(CHANGE_KINDS))
    show_impact.add_argument("--max-depth", type=int)
    show_impact.add_argument("--include-invalidated", action="store_true")

    show_invalidation_candidates = subparsers.add_parser(
        "show-invalidation-candidates",
        help="show read-only invalidation candidates for an object",
    )
    show_invalidation_candidates.add_argument("--ai-dir", required=True)
    show_invalidation_candidates.add_argument("--object-id", required=True)
    show_invalidation_candidates.add_argument("--change-kind", required=True, choices=sorted(CHANGE_KINDS))
    show_invalidation_candidates.add_argument("--max-depth", type=int)
    show_invalidation_candidates.add_argument("--include-low-severity", action="store_true")
    show_invalidation_candidates.add_argument("--include-invalidated", action="store_true")

    show_decision_stack = subparsers.add_parser(
        "show-decision-stack",
        help="show a bounded Decision Stack Graph around an object",
    )
    show_decision_stack.add_argument("--ai-dir", required=True)
    show_decision_stack.add_argument("--object-id", required=True)
    show_decision_stack.add_argument("--upstream-depth", type=int, default=1)
    show_decision_stack.add_argument("--downstream-depth", type=int, default=2)

    show_evidence_register = subparsers.add_parser(
        "show-evidence-register",
        help="show a read-only evidence register projection",
    )
    show_evidence_register.add_argument("--ai-dir", required=True)

    show_assumption_register = subparsers.add_parser(
        "show-assumption-register",
        help="show a read-only assumption register projection",
    )
    show_assumption_register.add_argument("--ai-dir", required=True)

    show_risk_register = subparsers.add_parser(
        "show-risk-register",
        help="show a read-only risk register projection",
    )
    show_risk_register.add_argument("--ai-dir", required=True)

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
        "export-decision-register", help="export a derived software decision register"
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
        "export-github-issues", help="export local GitHub issue drafts from derived plan actions"
    )
    github_issues.add_argument("--ai-dir", required=True)
    github_issues.add_argument("--session-id", action="append", required=True)
    github_issues.add_argument("--output-dir", required=True)

    agent_instructions = subparsers.add_parser(
        "export-agent-instructions", help="export derived local agent instruction files"
    )
    agent_instructions.add_argument("--ai-dir", required=True)
    agent_instructions.add_argument(
        "--target",
        required=True,
        choices=("agents-md", "cursor", "claude-skill-fragment", "codex-profile-fragment"),
    )
    agent_instructions.add_argument("--output")
    agent_instructions.add_argument("--force", action="store_true")

    architecture_doc = subparsers.add_parser(
        "export-architecture-doc",
        help="export a derived architecture documentation markdown file",
    )
    architecture_doc.add_argument("--ai-dir", required=True)
    architecture_doc.add_argument("--format", choices=("arc42",), required=True)
    architecture_doc.add_argument("--output", required=True)
    architecture_doc.add_argument("--session-id", action="append")

    traceability = subparsers.add_parser(
        "export-traceability",
        help="export a derived traceability matrix",
    )
    traceability.add_argument("--ai-dir", required=True)
    traceability.add_argument("--format", choices=("csv", "markdown"), required=True)
    traceability.add_argument("--output", required=True)
    traceability.add_argument("--session-id", action="append")

    verification_gaps = subparsers.add_parser(
        "export-verification-gaps",
        help="export a derived verification gap report",
    )
    verification_gaps.add_argument("--ai-dir", required=True)
    verification_gaps.add_argument("--output", required=True)
    verification_gaps.add_argument("--session-id", action="append")

    impact_report = subparsers.add_parser(
        "export-impact-report",
        help="export a read-only impact analysis Markdown report",
    )
    impact_report.add_argument("--ai-dir", required=True)
    impact_report.add_argument("--object-id", required=True)
    impact_report.add_argument("--change-kind", required=True, choices=sorted(CHANGE_KINDS))
    impact_report.add_argument("--max-depth", type=int)
    impact_report.add_argument("--include-low-severity", action="store_true")
    impact_report.add_argument("--include-invalidated", action="store_true")
    impact_report.add_argument("--output", required=True)

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
        elif args.command == "show-impact":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(
                analyze_impact(
                    bundle["project_state"],
                    args.object_id,
                    change_kind=args.change_kind,
                    max_depth=args.max_depth,
                    include_invalidated=args.include_invalidated,
                )
            )
        elif args.command == "show-invalidation-candidates":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(
                generate_invalidation_candidates(
                    bundle["project_state"],
                    args.object_id,
                    change_kind=args.change_kind,
                    max_depth=args.max_depth,
                    include_low_severity=args.include_low_severity,
                    include_invalidated=args.include_invalidated,
                )
            )
        elif args.command == "show-decision-stack":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            index = build_graph_index(bundle["project_state"])
            _print_json(
                bounded_subgraph(
                    index,
                    args.object_id,
                    upstream_depth=args.upstream_depth,
                    downstream_depth=args.downstream_depth,
                )
            )
        elif args.command == "show-evidence-register":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(build_evidence_register(bundle["project_state"]))
        elif args.command == "show-assumption-register":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(build_assumption_register(bundle["project_state"]))
        elif args.command == "show-risk-register":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(build_risk_register(bundle["project_state"]))
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
        elif args.command == "export-agent-instructions":
            result = export_agent_instructions(
                args.ai_dir,
                args.target,
                output=args.output,
                force=args.force,
            )
            _print_json(
                {
                    "path": str(result["path"]),
                    "target": result["target"],
                    "rule_count": result["rule_count"],
                }
            )
        elif args.command == "export-architecture-doc":
            path = export_architecture_doc(
                args.ai_dir,
                format=args.format,
                output=args.output,
                session_ids=args.session_id,
            )
            _print_json({"path": str(path), "format": args.format})
        elif args.command == "export-traceability":
            path = export_traceability(
                args.ai_dir,
                format=args.format,
                output=args.output,
                session_ids=args.session_id,
            )
            _print_json({"path": str(path), "format": args.format})
        elif args.command == "export-verification-gaps":
            path = export_verification_gaps(
                args.ai_dir,
                output=args.output,
                session_ids=args.session_id,
            )
            _print_json({"path": str(path)})
        elif args.command == "export-impact-report":
            path = export_impact_report(
                args.ai_dir,
                args.object_id,
                change_kind=args.change_kind,
                max_depth=args.max_depth,
                include_low_severity=args.include_low_severity,
                include_invalidated=args.include_invalidated,
                output=args.output,
            )
            _print_json({"path": str(path)})
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


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
