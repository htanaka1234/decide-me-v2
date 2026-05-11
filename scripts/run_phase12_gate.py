#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = (
    "tests.unit.test_phase12_source_store",
    "tests.integration.test_phase12_evidence_source_store",
    "tests.integration.test_phase12_distribution_artifact",
)


@dataclass(frozen=True)
class GateCommand:
    label: str
    args: tuple[str, ...]

    def display(self) -> str:
        return shlex.join(self.args)


def build_gate_commands(*, python: str = sys.executable, tests: Sequence[str] = DEFAULT_TESTS) -> list[GateCommand]:
    return [
        GateCommand(
            "phase 12 source-store unittest gate",
            (python, "-m", "unittest", *tests, "-v"),
        )
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the Phase 12 source-store gate")
    parser.add_argument(
        "--test",
        action="append",
        dest="tests",
        help="unittest module or test name to run; may be passed multiple times",
    )
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing them")
    args = parser.parse_args(argv)

    commands = build_gate_commands(tests=tuple(args.tests or DEFAULT_TESTS))
    env = _gate_env()
    for command in commands:
        print(f"==> {command.label}", flush=True)
        print(f"$ {command.display()}", flush=True)
        if args.dry_run:
            continue
        completed = subprocess.run(command.args, cwd=REPO_ROOT, env=env, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _gate_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not current else f"{REPO_ROOT}{os.pathsep}{current}"
    return env


if __name__ == "__main__":
    raise SystemExit(main())
