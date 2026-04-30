from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from scripts.decide_me import main


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CliResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def run_cli(
    *args: str,
    check: bool = True,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> CliResult:
    previous_cwd = Path.cwd()
    stdout = StringIO()
    stderr = StringIO()
    merged_env = _test_env(env)
    previous_env = os.environ.copy()
    previous_argv = sys.argv[:]

    try:
        os.environ.clear()
        os.environ.update(merged_env)
        sys.argv = [str(REPO_ROOT / "scripts" / "decide_me.py"), *args]
        if cwd is not None:
            os.chdir(cwd)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                returncode = main(list(args))
            except SystemExit as exc:
                returncode = _system_exit_code(exc)
    finally:
        if cwd is not None:
            os.chdir(previous_cwd)
        sys.argv = previous_argv
        os.environ.clear()
        os.environ.update(previous_env)

    result = CliResult(
        args=tuple(args),
        returncode=int(returncode or 0),
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"CLI failed with {result.returncode}: {' '.join(result.args)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return result


def run_json_cli(
    *args: str,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = run_cli(*args, check=True, cwd=cwd, env=env)
    if not result.stdout.strip():
        raise AssertionError(
            f"CLI produced no JSON stdout: {' '.join(result.args)}\n"
            f"STDERR:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def _test_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.setdefault("DECIDE_ME_EVENT_DISCOVERY", "python")
    if overrides:
        env.update(overrides)
    return env


def _system_exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1
