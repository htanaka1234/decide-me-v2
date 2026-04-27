from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BANNED_TERMS = (
    "accepted" + "_decisions",
    "deferred" + "_decisions",
    "evidence" + "_refs",
    "proposal" + "_issued",
    "proposal" + "_accepted",
    "decision" + "_discovered",
    "decision" + "_resolved_by_evidence",
    "compatibility" + "_backfilled",
    "action" + "_slices",
    "candidate" + "_action" + "_slices",
    "implementation" + "_ready_slices",
    "candidate" + "_workstreams",
    "unresolved" + "_blockers",
    "unresolved" + "_risks",
    "action" + "_slice",
    "action" + "-slice",
    "Action " + "Slices",
    "Implementation-ready " + "Slices",
    "Implementation-Ready " + "Slices",
)
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
ALLOWED_LEGACY_PATHS = {
    "references/migration-from-legacy-model.md",
    "tests/integration/test_legacy_event_types_rejected.py",
    "tests/integration/test_legacy_schema_rejected.py",
    "tests/integration/test_no_legacy_close_summary_keys.py",
    "tests/unit/test_events.py",
    "tests/unit/test_project_state_schema.py",
}
CLI_COMMANDS = (
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


class NoLegacyDomainModelTermsTests(unittest.TestCase):
    def test_public_source_surfaces_do_not_expose_legacy_terms(self) -> None:
        findings = []
        for path in _scanned_files():
            if path.relative_to(REPO_ROOT).as_posix() in ALLOWED_LEGACY_PATHS:
                continue
            text = path.read_text(encoding="utf-8")
            for term in BANNED_TERMS:
                if term in text:
                    findings.append(f"{path.relative_to(REPO_ROOT)} contains {term!r}")

        self.assertEqual([], findings)

    def test_cli_help_does_not_expose_legacy_terms(self) -> None:
        findings = []
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        for command in CLI_COMMANDS:
            result = subprocess.run(
                [sys.executable, "scripts/decide_me.py", *command, "--help"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            label = " ".join(command) or "<root>"
            for term in BANNED_TERMS:
                if term in result.stdout:
                    findings.append(f"help {label} contains {term!r}")

        self.assertEqual([], findings)


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for path in PUBLIC_SURFACE_PATHS:
        if path.is_file():
            files.append(path)
        else:
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and child.suffix in {".json", ".md", ".mdc", ".py", ".yaml", ".yml"}
            )
    return files


if __name__ == "__main__":
    unittest.main()
