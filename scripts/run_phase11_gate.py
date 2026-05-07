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
DEFAULT_PYTEST_MARKER = "phase_gate and not slow"
DEFAULT_SCENARIOS = "tests/scenarios"


@dataclass(frozen=True)
class GateCommand:
    label: str
    args: tuple[str, ...]

    def display(self) -> str:
        return shlex.join(self.args)


def build_gate_commands(
    *,
    python: str = sys.executable,
    pytest_marker: str = DEFAULT_PYTEST_MARKER,
    scenarios: str = DEFAULT_SCENARIOS,
    include_pytest: bool = True,
    include_evaluation: bool = True,
) -> list[GateCommand]:
    commands: list[GateCommand] = []
    if include_pytest:
        commands.append(
            GateCommand(
                "pytest phase gate",
                (python, "-m", "pytest", "-m", pytest_marker, "-q"),
            )
        )
    if include_evaluation:
        commands.append(
            GateCommand(
                "scenario evaluation",
                (
                    python,
                    "scripts/evaluate_scenarios.py",
                    "--scenarios",
                    scenarios,
                    "--format",
                    "json",
                ),
            )
        )
    return commands


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the Phase 11 release-readiness gate")
    parser.add_argument(
        "--pytest-marker",
        default=DEFAULT_PYTEST_MARKER,
        help=f"pytest marker expression for the first gate step (default: {DEFAULT_PYTEST_MARKER!r})",
    )
    parser.add_argument(
        "--scenarios",
        default=DEFAULT_SCENARIOS,
        help=f"scenario directory or scenario.yaml for evaluation (default: {DEFAULT_SCENARIOS})",
    )
    parser.add_argument("--skip-pytest", action="store_true", help="skip the pytest marker gate")
    parser.add_argument("--skip-evaluation", action="store_true", help="skip scenario evaluation")
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing them")
    args = parser.parse_args(argv)

    commands = build_gate_commands(
        pytest_marker=args.pytest_marker,
        scenarios=args.scenarios,
        include_pytest=not args.skip_pytest,
        include_evaluation=not args.skip_evaluation,
    )
    if not commands:
        parser.error("at least one gate step must be enabled")

    env = _gate_env()
    for command in commands:
        print(f"==> {command.label}", flush=True)
        if args.dry_run:
            print(f"$ {command.display()}", flush=True)
            continue

        command_to_run = _resolve_gate_command(command, env)
        print(f"$ {command_to_run.display()}", flush=True)
        completed = subprocess.run(command_to_run.args, cwd=REPO_ROOT, env=env, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _resolve_gate_command(command: GateCommand, env: dict[str, str]) -> GateCommand:
    if _is_pytest_command(command) and not _python_module_available(command.args[0], "pytest", env):
        print("pytest is unavailable for this Python; falling back to unittest discover", flush=True)
        return GateCommand("unittest phase gate fallback", (command.args[0], "-m", "unittest", "discover", "-v"))
    return command


def _is_pytest_command(command: GateCommand) -> bool:
    return len(command.args) >= 3 and command.args[1:3] == ("-m", "pytest")


def _python_module_available(python: str, module: str, env: dict[str, str]) -> bool:
    completed = subprocess.run(
        (python, "-c", f"import {module}"),
        cwd=REPO_ROOT,
        env=env,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _gate_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not current else f"{REPO_ROOT}{os.pathsep}{current}"
    return env


if __name__ == "__main__":
    raise SystemExit(main())
