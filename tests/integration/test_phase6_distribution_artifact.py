from __future__ import annotations

import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]


class Phase6DistributionArtifactTests(unittest.TestCase):
    def test_distribution_contains_phase6_graph_impact_files(self) -> None:
        with _built_artifact() as archive:
            names = set(archive.namelist())

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
        self.assertTrue(required.issubset(names))

    def test_distribution_cli_has_phase6_impact_imports(self) -> None:
        with _built_artifact() as archive:
            script = archive.read("decide-me/scripts/decide_me.py").decode("utf-8")
            exports = archive.read("decide-me/decide_me/exports.py").decode("utf-8")

        self.assertIn("from decide_me.graph_traversal import bounded_subgraph, build_graph_index", script)
        self.assertIn("from decide_me.impact_analysis import CHANGE_KINDS, analyze_impact", script)
        self.assertIn("from decide_me.invalidation_candidates import generate_invalidation_candidates", script)
        self.assertIn("export_impact_report", script)
        self.assertIn("from decide_me.impact_report import render_impact_report", exports)
        self.assertIn("from decide_me.impact_analysis import analyze_impact", exports)
        self.assertIn("from decide_me.invalidation_candidates import generate_invalidation_candidates", exports)


@contextmanager
def _built_artifact() -> Iterator[ZipFile]:
    with TemporaryDirectory() as temp_dir:
        dist_dir = Path(temp_dir) / "dist"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        subprocess.run(
            [sys.executable, "scripts/build_artifact.py", "--dist-dir", str(dist_dir)],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with ZipFile(dist_dir / "decide-me.zip") as archive:
            yield archive


if __name__ == "__main__":
    unittest.main()
