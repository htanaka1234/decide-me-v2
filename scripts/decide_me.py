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
from decide_me.domains import DomainPack, domain_pack_digest, load_domain_registry
from decide_me.exports import (
    export_adr,
    export_agent_instructions,
    export_architecture_doc,
    export_decision_register,
    export_document_detailed,
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
from decide_me.safety_approval import approve_safety_gate, show_safety_approvals
from decide_me.safety_gate import build_safety_gate_report, evaluate_safety_gate
from decide_me.session_graph import (
    detect_session_conflicts,
    show_session_graph,
)
from decide_me.stale_detection import (
    detect_revisit_due,
    detect_stale_assumptions,
    detect_stale_evidence,
    detect_verification_gaps,
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
    create.add_argument("--domain-pack")

    list_cmd = subparsers.add_parser("list-sessions", help="list sessions")
    list_cmd.add_argument("--ai-dir", required=True)
    list_cmd.add_argument("--query")
    list_cmd.add_argument("--status", action="append", default=[])
    list_cmd.add_argument("--domain", action="append", default=[])
    list_cmd.add_argument("--domain-pack", action="append", default=[])
    list_cmd.add_argument("--abstraction-level", action="append", default=[])
    list_cmd.add_argument("--tag", action="append", default=[])

    list_domain_packs = subparsers.add_parser("list-domain-packs", help="list available domain packs")
    list_domain_packs.add_argument("--ai-dir", required=True)

    show_domain_pack = subparsers.add_parser("show-domain-pack", help="show one domain pack")
    show_domain_pack.add_argument("--ai-dir", required=True)
    show_domain_pack.add_argument("--pack-id", required=True)

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

    show_safety_gate = subparsers.add_parser(
        "show-safety-gate",
        help="show a read-only safety gate result for one object",
    )
    show_safety_gate.add_argument("--ai-dir", required=True)
    show_safety_gate.add_argument("--object-id", required=True)
    show_safety_gate.add_argument("--now")

    show_safety_gates = subparsers.add_parser(
        "show-safety-gates",
        help="show read-only safety gate results for live decisions and actions",
    )
    show_safety_gates.add_argument("--ai-dir", required=True)
    show_safety_gates.add_argument("--now")

    approve_gate = subparsers.add_parser(
        "approve-safety-gate",
        help="record an approval artifact for a safety gate that needs approval",
    )
    approve_gate.add_argument("--ai-dir", required=True)
    approve_gate.add_argument("--session-id", required=True)
    approve_gate.add_argument("--object-id", required=True)
    approve_gate.add_argument("--approved-by", required=True)
    approve_gate.add_argument("--reason", required=True)
    approve_gate.add_argument("--expires-at")

    show_approvals = subparsers.add_parser(
        "show-safety-approvals",
        help="show safety approval artifacts",
    )
    show_approvals.add_argument("--ai-dir", required=True)
    show_approvals.add_argument("--object-id")
    show_approvals.add_argument("--now")

    show_stale_assumptions = subparsers.add_parser(
        "show-stale-assumptions",
        help="show read-only stale assumption diagnostics",
    )
    show_stale_assumptions.add_argument("--ai-dir", required=True)
    show_stale_assumptions.add_argument("--now")

    show_stale_evidence = subparsers.add_parser(
        "show-stale-evidence",
        help="show read-only stale evidence diagnostics",
    )
    show_stale_evidence.add_argument("--ai-dir", required=True)
    show_stale_evidence.add_argument("--now")

    show_verification_gaps = subparsers.add_parser(
        "show-verification-gaps",
        help="show read-only structured verification gap diagnostics",
    )
    show_verification_gaps.add_argument("--ai-dir", required=True)
    show_verification_gaps.add_argument("--now")

    show_revisit_due = subparsers.add_parser(
        "show-revisit-due",
        help="show read-only due revisit trigger diagnostics",
    )
    show_revisit_due.add_argument("--ai-dir", required=True)
    show_revisit_due.add_argument("--now")

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

    document = subparsers.add_parser(
        "export-document",
        help="export a derived generic document from the object/link runtime",
    )
    document.add_argument("--ai-dir", required=True)
    document.add_argument(
        "--type",
        required=True,
        choices=(
            "decision-brief",
            "action-plan",
            "risk-register",
            "review-memo",
            "research-plan",
            "comparison-table",
        ),
    )
    document.add_argument("--format", required=True, choices=("markdown", "json", "csv"))
    document.add_argument("--output", required=True)
    document.add_argument("--session-id", action="append")
    document.add_argument("--object-id", action="append")
    document.add_argument("--domain-pack")
    document.add_argument("--include-invalidated", action="store_true")
    document.add_argument("--now")
    document.add_argument("--force", action="store_true")
    document_region = document.add_mutually_exclusive_group()
    document_region.add_argument("--managed-region", dest="managed_region", action="store_true", default=True)
    document_region.add_argument("--no-managed-region", dest="managed_region", action="store_false")

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
            _print_json(create_session(args.ai_dir, context=args.context, domain_pack_id=args.domain_pack))
        elif args.command == "list-sessions":
            domain_packs = _require_domain_pack_filters(args.ai_dir, args.domain_pack)
            _print_json(
                list_sessions(
                    args.ai_dir,
                    query=args.query,
                    statuses=args.status,
                    domains=args.domain,
                    domain_packs=domain_packs,
                    abstraction_levels=args.abstraction_level,
                    tag_terms=args.tag,
                )
            )
        elif args.command == "list-domain-packs":
            _print_json(_list_domain_packs(args.ai_dir))
        elif args.command == "show-domain-pack":
            pack = _require_domain_pack(args.ai_dir, args.pack_id)
            _print_json({"status": "ok", "digest": domain_pack_digest(pack), "pack": pack.to_dict()})
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
        elif args.command == "show-safety-gate":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(
                evaluate_safety_gate(
                    bundle["project_state"],
                    args.object_id,
                    now=args.now,
                    domain_registry=load_domain_registry(args.ai_dir),
                )
            )
        elif args.command == "show-safety-gates":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(
                build_safety_gate_report(
                    bundle["project_state"],
                    now=args.now,
                    domain_registry=load_domain_registry(args.ai_dir),
                )
            )
        elif args.command == "approve-safety-gate":
            _print_json(
                approve_safety_gate(
                    args.ai_dir,
                    args.session_id,
                    args.object_id,
                    approved_by=args.approved_by,
                    reason=args.reason,
                    expires_at=args.expires_at,
                )
            )
        elif args.command == "show-safety-approvals":
            _print_json(show_safety_approvals(args.ai_dir, object_id=args.object_id, now=args.now))
        elif args.command == "show-stale-assumptions":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(detect_stale_assumptions(bundle["project_state"], now=args.now))
        elif args.command == "show-stale-evidence":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(detect_stale_evidence(bundle["project_state"], now=args.now))
        elif args.command == "show-verification-gaps":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(detect_verification_gaps(bundle["project_state"], now=args.now))
        elif args.command == "show-revisit-due":
            bundle = load_runtime(runtime_paths(args.ai_dir))
            _print_json(detect_revisit_due(bundle["project_state"], now=args.now))
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
        elif args.command == "export-document":
            domain_pack_id = None
            if args.domain_pack is not None:
                pack = _require_domain_pack(args.ai_dir, args.domain_pack)
                domain_pack_id = pack.pack_id
            export_result = export_document_detailed(
                args.ai_dir,
                document_type=args.type,
                format=args.format,
                output=args.output,
                session_ids=args.session_id,
                object_ids=args.object_id,
                domain_pack_id=domain_pack_id,
                include_invalidated=args.include_invalidated,
                now=args.now,
                force=args.force,
                managed_region=args.managed_region,
            )
            metadata = export_result.get("metadata", {})
            applied = all(
                isinstance(metadata.get(key), str)
                for key in ("domain_pack_id", "document_profile_id")
            )
            result = {
                "path": str(export_result["path"]),
                "type": args.type,
                "format": args.format,
                "domain_pack_applied": applied,
            }
            if applied:
                result.update(
                    {
                        "domain_pack_id": metadata["domain_pack_id"],
                        "document_profile_id": metadata["document_profile_id"],
                        "domain_pack_selection": "explicit" if domain_pack_id is not None else "inferred_from_sessions",
                    }
                )
            _print_json(result)
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


def _list_domain_packs(ai_dir: str) -> dict[str, object]:
    packs = [
        {
            "pack_id": pack.pack_id,
            "version": pack.version,
            "label": pack.label,
            "description": pack.description,
            "default_core_domain": pack.default_core_domain,
            "digest": domain_pack_digest(pack),
        }
        for pack in load_domain_registry(ai_dir).list()
    ]
    return {"status": "ok", "count": len(packs), "packs": packs}


def _require_domain_pack(ai_dir: str, pack_id: str) -> DomainPack:
    pack_id = pack_id.strip()
    if not pack_id:
        raise ValueError("domain pack must be a non-empty string")
    try:
        return load_domain_registry(ai_dir).get(pack_id)
    except KeyError as exc:
        raise ValueError(f"unknown domain pack: {pack_id}") from exc


def _require_domain_pack_filters(ai_dir: str, pack_ids: list[str]) -> list[str]:
    if not pack_ids:
        return []
    registry = load_domain_registry(ai_dir)
    normalized: list[str] = []
    for pack_id in pack_ids:
        pack_id = pack_id.strip()
        if not pack_id:
            raise ValueError("domain pack must be a non-empty string")
        try:
            normalized.append(registry.get(pack_id).pack_id)
        except KeyError as exc:
            raise ValueError(f"unknown domain pack: {pack_id}") from exc
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
