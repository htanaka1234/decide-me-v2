from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_TIMEOUT_SECONDS = 30
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".mdc",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
PUBLIC_SURFACE_PATHS = (
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "agents" / "openai.yaml",
    REPO_ROOT / "decide_me",
    REPO_ROOT / "schemas",
    REPO_ROOT / "scripts" / "decide_me.py",
    REPO_ROOT / "scripts" / "build_artifact.py",
    REPO_ROOT / "references",
    REPO_ROOT / "templates",
    REPO_ROOT / "tests",
)
ALLOWED_LEGACY_TERM_PATHS = {
    "references/migration-from-legacy-model.md",
    "tests/integration/test_legacy_event_types_rejected.py",
    "tests/integration/test_legacy_schema_rejected.py",
}
CLI_HELP_COMMANDS = (
    (),
    ("bootstrap",),
    ("create-session",),
    ("list-sessions",),
    ("show-session",),
    ("resume-session",),
    ("close-session",),
    ("generate-plan",),
    ("rebuild-projections",),
    ("validate-state",),
    ("compact-runtime",),
    ("benchmark-runtime",),
    ("detect-merge-conflicts",),
    ("resolve-merge-conflict",),
    ("show-session-graph",),
    ("detect-session-conflicts",),
    ("resolve-decision-supersession",),
    ("export-adr",),
    ("export-structured-adr",),
    ("export-decision-register",),
    ("export-github-templates",),
    ("export-github-issues",),
    ("export-agent-instructions",),
    ("export-architecture-doc",),
    ("export-traceability",),
    ("export-verification-gaps",),
    ("advance-session",),
    ("handle-reply",),
)


def _snake(*parts: str) -> str:
    return "_".join(parts)


def _kebab(*parts: str) -> str:
    return "-".join(parts)


LEGACY_EVENT_TYPE_TERMS = (
    _snake("decision", "discovered"),
    _snake("decision", "enriched"),
    _snake("question", "asked"),
    _snake("proposal", "issued"),
    _snake("proposal", "accepted"),
    _snake("proposal", "rejected"),
    _snake("decision", "deferred"),
    _snake("decision", "resolved", "by", "evidence"),
    _snake("decision", "invalidated"),
    _snake("compatibility", "backfilled"),
    _snake("classification", "updated"),
    _snake("session", "linked"),
    _snake("semantic", "conflict", "resolved"),
)
LEGACY_CLOSE_SUMMARY_TERMS = (
    _snake("accepted", "decisions"),
    _snake("deferred", "decisions"),
    _snake("unresolved", "blockers"),
    _snake("unresolved", "risks"),
    _snake("candidate", "workstreams"),
    _snake("candidate", "action", "slices"),
    _snake("evidence", "refs"),
)
LEGACY_PLAN_TERMS = (
    _snake("action", "slices"),
    _snake("implementation", "ready", "slices"),
    _snake("action", "slice"),
    _kebab("action", "slice"),
    "Action " + "Slices",
    "Implementation-ready " + "Slices",
    "Implementation-Ready " + "Slices",
)
LEGACY_PROJECT_STATE_TERMS = (
    _snake("default", "bundles"),
)
LEGACY_DOMAIN_MODEL_TERMS = (
    *LEGACY_EVENT_TYPE_TERMS,
    *LEGACY_CLOSE_SUMMARY_TERMS,
    *LEGACY_PLAN_TERMS,
    *LEGACY_PROJECT_STATE_TERMS,
)


@dataclass(frozen=True)
class LegacyTermFinding:
    location: str
    term: str
    line: int | None = None

    def format(self) -> str:
        suffix = f":{self.line}" if self.line is not None else ""
        return f"{self.location}{suffix} contains {self.term!r}"


def source_legacy_term_findings(
    paths: Iterable[Path] = PUBLIC_SURFACE_PATHS,
    *,
    allowed_paths: set[str] = ALLOWED_LEGACY_TERM_PATHS,
) -> list[LegacyTermFinding]:
    findings: list[LegacyTermFinding] = []
    for path in scanned_source_files(paths):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in allowed_paths:
            continue
        findings.extend(scan_text(path.read_text(encoding="utf-8"), relative))
    return findings


def cli_help_legacy_term_findings(commands: Iterable[tuple[str, ...]] = CLI_HELP_COMMANDS) -> list[LegacyTermFinding]:
    findings: list[LegacyTermFinding] = []
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    for command in commands:
        result = subprocess.run(
            [sys.executable, "scripts/decide_me.py", *command, "--help"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        label = " ".join(command) or "<root>"
        findings.extend(scan_text(result.stdout, f"help {label}"))
    return findings


def zip_legacy_term_findings(
    archive: ZipFile,
    *,
    allowed_paths: set[str] | None = None,
) -> list[LegacyTermFinding]:
    allowed_paths = allowed_paths or set()
    findings: list[LegacyTermFinding] = []
    for name in archive.namelist():
        if name in allowed_paths or not is_text_file(name):
            continue
        text = archive.read(name).decode("utf-8")
        findings.extend(scan_text(text, name))
    return findings


def json_payload_legacy_term_findings(payload: Any, label: str) -> list[LegacyTermFinding]:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return scan_text(text, label)


def scan_text(
    text: str,
    location: str,
    *,
    terms: Iterable[str] = LEGACY_DOMAIN_MODEL_TERMS,
) -> list[LegacyTermFinding]:
    findings: list[LegacyTermFinding] = []
    for term in terms:
        pattern = _term_pattern(term)
        match = pattern.search(text)
        if match:
            findings.append(LegacyTermFinding(location, term, _line_number(text, match.start())))
    return findings


def scanned_source_files(paths: Iterable[Path] = PUBLIC_SURFACE_PATHS) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if is_text_file(path.name):
                files.append(path)
            continue
        files.extend(
            child
            for child in sorted(path.rglob("*"))
            if child.is_file()
            and "__pycache__" not in child.parts
            and child.suffix in TEXT_SUFFIXES
        )
    return files


def is_text_file(name: str) -> bool:
    return Path(name).suffix in TEXT_SUFFIXES


def format_findings(findings: Iterable[LegacyTermFinding]) -> list[str]:
    return [finding.format() for finding in findings]


def _term_pattern(term: str) -> re.Pattern[str]:
    if re.fullmatch(r"[A-Za-z0-9_]+", term):
        return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
    if re.fullmatch(r"[A-Za-z0-9_-]+", term):
        return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])")
    return re.compile(re.escape(term))


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
