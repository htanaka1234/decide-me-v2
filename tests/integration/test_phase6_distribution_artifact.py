from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


CLI_TIMEOUT_SECONDS = 30


class Phase6DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_phase6_graph_impact_files(self) -> None:
        names = self.artifact.names()

        required = {
            "decide-me/schemas/impact-analysis.schema.json",
            "decide-me/schemas/invalidation-candidates.schema.json",
            "decide-me/templates/impact-report-template.md",
            "decide-me/references/impact-analysis.md",
            "decide-me/references/invalidation-candidates.md",
            "decide-me/references/decision-stack-graph.md",
            "decide-me/decide_me/impact_analysis.py",
            "decide-me/decide_me/invalidation_candidates.py",
            "decide-me/decide_me/impact_report.py",
            "decide-me/decide_me/graph_traversal.py",
        }
        self.assertEqual(set(), required - names)

    def test_distribution_artifact_supports_phase6_cli_and_import_smoke(self) -> None:
        skill_dir = self.artifact.extract_once()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(skill_dir)

        self.artifact.run_packaged_cli("show-impact", "--help")
        self.artifact.run_packaged_cli("apply-invalidation-candidate", "--help")
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from decide_me.exports import export_impact_report; "
                    "from decide_me.graph_traversal import bounded_subgraph"
                ),
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
