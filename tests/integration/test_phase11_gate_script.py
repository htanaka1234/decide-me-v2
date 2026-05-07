from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_phase11_gate


REPO_ROOT = Path(__file__).resolve().parents[2]


class Phase11GateScriptTests(unittest.TestCase):
    def test_default_gate_commands_run_pytest_then_scenario_evaluation(self) -> None:
        commands = run_phase11_gate.build_gate_commands(python="python3")

        self.assertEqual(["pytest phase gate", "scenario evaluation"], [command.label for command in commands])
        self.assertEqual(
            ("python3", "-m", "pytest", "-m", "phase_gate and not slow", "-q"),
            commands[0].args,
        )
        self.assertEqual(
            (
                "python3",
                "scripts/evaluate_scenarios.py",
                "--scenarios",
                "tests/scenarios",
                "--format",
                "json",
            ),
            commands[1].args,
        )

    def test_dry_run_reports_commands_without_running_gate(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)

        result = subprocess.run(
            [sys.executable, "scripts/run_phase11_gate.py", "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("==> pytest phase gate", result.stdout)
        self.assertIn("-m pytest -m 'phase_gate and not slow' -q", result.stdout)
        self.assertIn("==> scenario evaluation", result.stdout)
        self.assertIn("scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json", result.stdout)

    def test_pytest_step_falls_back_to_unittest_when_pytest_is_unavailable(self) -> None:
        command = run_phase11_gate.GateCommand(
            "pytest phase gate",
            ("python3", "-m", "pytest", "-m", "phase_gate and not slow", "-q"),
        )

        with patch.object(run_phase11_gate, "_python_module_available", return_value=False):
            resolved = run_phase11_gate._resolve_gate_command(command, {})

        self.assertEqual("unittest phase gate fallback", resolved.label)
        self.assertEqual(("python3", "-m", "unittest", "discover", "-v"), resolved.args)

    def test_github_actions_gate_has_runtime_timeout(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/phase11-gate.yml").read_text(encoding="utf-8")

        self.assertIn("timeout-minutes: 5", workflow)

    def test_github_actions_gate_uses_node24_action_versions(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/phase11-gate.yml").read_text(encoding="utf-8")

        self.assertIn("uses: actions/checkout@v6", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)


if __name__ == "__main__":
    unittest.main()
