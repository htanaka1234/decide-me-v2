from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import run_phase10_gate


REPO_ROOT = Path(__file__).resolve().parents[2]


class Phase10GateScriptTests(unittest.TestCase):
    def test_default_gate_commands_run_pytest_then_scenario_evaluation(self) -> None:
        commands = run_phase10_gate.build_gate_commands(python="python3")

        self.assertEqual(["pytest phase gate", "scenario evaluation"], [command.label for command in commands])
        self.assertEqual(
            ("python3", "-m", "pytest", "-m", "unit or phase_gate", "-q"),
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
            [sys.executable, "scripts/run_phase10_gate.py", "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("==> pytest phase gate", result.stdout)
        self.assertIn("-m pytest -m 'unit or phase_gate' -q", result.stdout)
        self.assertIn("==> scenario evaluation", result.stdout)
        self.assertIn("scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json", result.stdout)


if __name__ == "__main__":
    unittest.main()
