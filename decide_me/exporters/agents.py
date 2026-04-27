from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from decide_me.exporters.common import (
    DecisionEventIndex,
    build_decision_event_index,
    decision_views,
    decision_summary,
    project_head,
    referenced_evidence,
    snapshot_generated_at,
)
from decide_me.store import load_runtime, read_event_log, runtime_paths


AGENT_INSTRUCTIONS_SCHEMA_VERSION = 1
AGENT_INSTRUCTION_TARGETS = {
    "agents-md",
    "cursor",
    "claude-skill-fragment",
    "codex-profile-fragment",
}
DEFAULT_OUTPUT_FILENAMES = {
    "agents-md": "AGENTS.md",
    "cursor": "cursor-decisions.mdc",
    "claude-skill-fragment": "claude-skill-fragment.md",
    "codex-profile-fragment": "codex-profile-fragment.md",
}
SECTION_ORDER = (
    "Runtime Rules",
    "Development Rules",
    "Testing Rules",
    "Dependency Rules",
    "Safety Rules",
    "Security Rules",
    "Repository Layout",
    "Review Checklist",
)
MARKER_START = "<!-- decide-me:start -->"
MARKER_END = "<!-- decide-me:end -->"
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "agents"

EXPORTABLE_STATUSES = {"accepted", "resolved-by-evidence"}
SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Security Rules",
        (
            "secret",
            "secrets",
            "credential",
            "credentials",
            "token",
            "password",
            "api key",
            "private key",
            "security",
            "redact",
            "pii",
        ),
    ),
    (
        "Dependency Rules",
        (
            "dependency policy",
            "dependencies",
            "new dependency",
            "new dependencies",
            "adding dependencies",
            "add dependencies",
            "pnpm",
            "uv",
            "pip",
            "npm",
            "lock file",
            "lockfile",
        ),
    ),
    (
        "Safety Rules",
        (
            "destructive",
            "delete",
            "deletion",
            "overwrite",
            "overwriting",
            "drop table",
            "truncate",
            "confirmation",
            "confirm before",
            "approval",
            "force",
        ),
    ),
    (
        "Review Checklist",
        (
            "review",
            "pull request",
            "pr",
            "prs",
            "before merge",
            "before merging",
            "before commit",
            "checklist",
        ),
    ),
    (
        "Development Rules",
        (
            "coding convention",
            "coding conventions",
            "code style",
            "typing",
            "type hint",
            "type hints",
            "lint",
            "formatter",
            "formatting",
            "naming",
            "naming convention",
            "naming conventions",
        ),
    ),
    (
        "Runtime Rules",
        (
            "runtime",
            "event log",
            "events/**/*.jsonl",
            ".ai/decide-me/events",
            "source event",
            "source events",
            "projections",
            "source of truth",
            "validate-state",
            "rebuild-projections",
            "decide-me",
        ),
    ),
    (
        "Testing Rules",
        (
            "testing policy",
            "test policy",
            "test",
            "tests",
            "testing",
            "pytest",
            "unittest",
            "ci",
            "check",
            "checks",
        ),
    ),
    (
        "Repository Layout",
        (
            "repository layout",
            "repo layout",
            "layout",
            ".ai/decide-me",
        ),
    ),
)
AGENT_POLICY_KEYWORDS = (
    "agent",
    "agents.md",
    "cursor",
    "claude",
    "codex",
    "coding convention",
    "coding conventions",
    "code style",
    "typing",
    "type hint",
    "type hints",
    "testing policy",
    "test policy",
    "run tests",
    "validate-state",
    "dependency policy",
    "new dependency",
    "new dependencies",
    "adding dependencies",
    "add dependencies",
    "print secret",
    "print secrets",
    "secret values",
    "credential values",
    "redact",
    "redaction",
    "destructive operation",
    "destructive operations",
    "confirm before",
    "require approval",
    "requires approval",
    "approval before",
    "before opening pr",
    "before opening prs",
    "before merge",
    "before merging",
    "before commit",
    "after changes",
    "after code changes",
    "review checklist",
    "pull request review",
    "pr review",
    "pr checklist",
    "repository layout",
    "repo layout",
    "events/**/*.jsonl",
    ".ai/decide-me/events",
)
RUNTIME_POLICY_KEYWORDS = (
    "source of truth",
    "event log",
)
RUNTIME_POLICY_CONTEXT_KEYWORDS = (
    "agent",
    "agents.md",
    "codex",
    "decide-me",
    "runtime",
    "repository layout",
    "repo layout",
    "validate-state",
    "rebuild-projections",
    "projections",
    "events/**/*.jsonl",
    ".ai/decide-me",
    ".ai/decide-me/events",
)
POLICY_MODAL_KEYWORDS = (
    "required",
    "require",
    "must",
    "always",
    "never",
    "do not",
)
POLICY_MODAL_CONTEXT_KEYWORDS = (
    "agent",
    "agents.md",
    "cursor",
    "claude",
    "codex",
    "testing policy",
    "test policy",
    "run tests",
    "validate-state",
    "after code changes",
    "new dependency",
    "new dependencies",
    "adding dependencies",
    "add dependencies",
    "dependency policy",
    "print secret",
    "print secrets",
    "secret values",
    "credential values",
    "redact",
    "redaction",
    "destructive operation",
    "destructive operations",
    "confirm before",
    "before deleting",
    "before overwriting",
    "review checklist",
    "pull request review",
    "pr review",
    "pr checklist",
    "before opening pr",
    "before opening prs",
    "before merge",
    "before merging",
    "before commit",
    "type hint",
    "type hints",
    "coding convention",
    "code style",
    "repository layout",
    "repo layout",
    "events/**/*.jsonl",
    ".ai/decide-me/events",
)


def export_agent_instructions(
    ai_dir: str | Path,
    target: str,
    *,
    output: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if target not in AGENT_INSTRUCTION_TARGETS:
        raise ValueError(f"unsupported agent instruction target: {target}")

    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    events = read_event_log(paths)
    payload = build_agent_instructions_payload(bundle, events)
    output_path = Path(output) if output is not None else _default_output_path(paths.exports_dir, target)

    if target == "agents-md":
        _write_agents_md(output_path, payload, force=force)
    else:
        _write_text(output_path, render_agent_instructions(payload, target))

    return {"path": output_path, "target": target, "rule_count": len(payload["rules"])}


def build_agent_instructions_payload(
    bundle: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    index = build_decision_event_index(events)
    rules = [
        rule
        for decision in sorted(decision_views(bundle["project_state"]), key=lambda item: item["id"])
        for rule in [_agent_rule(decision, index)]
        if rule is not None
    ]
    rules.sort(key=lambda rule: (SECTION_ORDER.index(rule["section"]), rule["decision_id"]))
    return {
        "schema_version": AGENT_INSTRUCTIONS_SCHEMA_VERSION,
        "generated_at": snapshot_generated_at(bundle, events),
        "project_head": project_head(bundle),
        "rules": rules,
    }


def render_agent_instructions(payload: dict[str, Any], target: str) -> str:
    if target not in AGENT_INSTRUCTION_TARGETS:
        raise ValueError(f"unsupported agent instruction target: {target}")
    template_name = {
        "agents-md": "AGENTS.md",
        "cursor": "cursor-rule.mdc",
        "claude-skill-fragment": "claude-skill-fragment.md",
        "codex-profile-fragment": "codex-profile-fragment.md",
    }[target]
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    return _render_template(template, _generated_block(payload))


def _agent_rule(decision: dict[str, Any], index: DecisionEventIndex) -> dict[str, Any] | None:
    if decision.get("status") not in EXPORTABLE_STATUSES:
        return None
    agent_relevant = decision.get("agent_relevant")
    if agent_relevant is False:
        return None

    summary = _normalize_rule_text(decision_summary(decision))
    if not summary:
        return None

    search_text = _decision_search_text(decision, summary)
    forced = agent_relevant is True
    if not forced and not _is_agent_policy_decision(search_text):
        return None

    section = _section_for_text(search_text) or ("Development Rules" if forced else None)
    if section is None:
        return None

    decision_id = decision["id"]
    return {
        "decision_id": decision_id,
        "section": section,
        "text": summary,
        "source": {
            "decision_id": decision_id,
            "session_id": index.session_ids.get(decision_id),
            "title": decision.get("title"),
            "status": decision.get("status"),
            "domain": decision.get("domain"),
            "kind": decision.get("kind"),
            "accepted_via": decision.get("accepted_answer", {}).get("accepted_via"),
            "evidence": referenced_evidence(decision),
        },
    }


def _section_for_text(text: str) -> str | None:
    for section, keywords in SECTION_KEYWORDS:
        if _has_any(text, keywords):
            return section
    return None


def _is_agent_policy_decision(text: str) -> bool:
    return (
        _has_any(text, AGENT_POLICY_KEYWORDS)
        or (
            _has_any(text, RUNTIME_POLICY_KEYWORDS)
            and _has_any(text, RUNTIME_POLICY_CONTEXT_KEYWORDS)
        )
    ) or (
        _has_any(text, POLICY_MODAL_KEYWORDS)
        and _has_any(text, POLICY_MODAL_CONTEXT_KEYWORDS)
    )


def _decision_search_text(decision: dict[str, Any], summary: str) -> str:
    values: list[Any] = [
        decision.get("id"),
        decision.get("title"),
        decision.get("kind"),
        decision.get("domain"),
        decision.get("question"),
        decision.get("context"),
        summary,
        decision.get("recommendation", {}).get("summary"),
        decision.get("recommendation", {}).get("rationale_short"),
        *decision.get("notes", []),
        *decision.get("revisit_triggers", []),
        *decision.get("evidence", []),
        *decision.get("resolved_by_evidence", {}).get("evidence", []),
    ]
    return "\n".join(str(value) for value in values if value is not None).casefold()


def _normalize_rule_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        normalized = keyword.casefold()
        if normalized.isalnum():
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            if re.search(pattern, text):
                return True
        elif normalized in text:
            return True
    return False


def _default_output_path(exports_dir: Path, target: str) -> Path:
    return exports_dir / "agents" / DEFAULT_OUTPUT_FILENAMES[target]


def _write_agents_md(output_path: Path, payload: dict[str, Any], *, force: bool) -> None:
    generated_block = _generated_block(payload)
    full_body = render_agent_instructions(payload, "agents-md")
    if force or not output_path.exists():
        _write_text(output_path, full_body)
        return

    if output_path.is_dir():
        raise ValueError(f"agent instruction output path is a directory: {output_path}")

    existing = output_path.read_text(encoding="utf-8")
    if MARKER_START not in existing or MARKER_END not in existing:
        raise ValueError(
            f"{output_path} already exists without decide-me markers; pass --force to overwrite it"
        )
    _write_text(output_path, _replace_marked_block(existing, generated_block))


def _replace_marked_block(existing: str, generated_block: str) -> str:
    if existing.count(MARKER_START) != 1 or existing.count(MARKER_END) != 1:
        raise ValueError("AGENTS.md must contain exactly one decide-me marker block")
    start_index = existing.index(MARKER_START)
    end_index = existing.index(MARKER_END)
    if end_index < start_index:
        raise ValueError("AGENTS.md decide-me end marker appears before start marker")
    prefix = existing[: start_index + len(MARKER_START)]
    suffix = existing[end_index:]
    return f"{prefix}\n{generated_block.rstrip()}\n{suffix}"


def _generated_block(payload: dict[str, Any]) -> str:
    lines = [
        f"Generated at: {_render_scalar(payload.get('generated_at'))}",
        f"Project head: {_render_scalar(payload.get('project_head'))}",
        f"Rule count: {len(payload['rules'])}",
        "",
        _render_sections(payload["rules"]),
    ]
    return "\n".join(lines).rstrip()


def _render_sections(rules: list[dict[str, Any]]) -> str:
    if not rules:
        return "No agent-relevant decisions found."

    lines: list[str] = []
    for section in SECTION_ORDER:
        section_rules = [rule for rule in rules if rule["section"] == section]
        if not section_rules:
            continue
        if lines:
            lines.append("")
        lines.append(f"## {section}")
        lines.append("")
        for rule in section_rules:
            lines.append(f"- {rule['text']} (Source: {rule['decision_id']})")
    return "\n".join(lines)


def _render_template(template: str, generated_block: str) -> str:
    return template.replace("{{generated_block}}", generated_block).rstrip() + "\n"


def _render_scalar(value: Any) -> str:
    if value is None:
        return "null"
    return str(value)


def _write_text(path: Path, body: str) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(f"agent instruction output path is a directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
