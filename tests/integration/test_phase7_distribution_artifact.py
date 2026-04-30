from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests.helpers.distribution_artifact import BuiltArtifact

CLI_TIMEOUT_SECONDS = 30


class Phase7DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_phase7_safety_files(self) -> None:
        names = self.artifact.names()

        required = {
            "decide-me/decide_me/safety_approval.py",
            "decide-me/decide_me/safety_gate.py",
            "decide-me/decide_me/registers.py",
            "decide-me/decide_me/stale_detection.py",
            "decide-me/schemas/safety-approval.schema.json",
            "decide-me/schemas/safety-gates.schema.json",
            "decide-me/schemas/registers.schema.json",
            "decide-me/schemas/stale-diagnostics.schema.json",
            "decide-me/references/safety-approvals.md",
            "decide-me/references/safety-gates.md",
            "decide-me/references/registers.md",
            "decide-me/references/stale-detection.md",
        }
        self.assertEqual(set(), required - names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))

    def test_distribution_supports_phase7_cli_and_import_smoke(self) -> None:
        skill_dir = self.artifact.extract_once()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(skill_dir)

        self.artifact.run_packaged_cli("approve-safety-gate", "--help")
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from decide_me.safety_approval import approve_safety_gate; from decide_me.safety_gate import evaluate_safety_gate",
            ],
            cwd=skill_dir,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
