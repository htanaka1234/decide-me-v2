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
CLI_TIMEOUT_SECONDS = 30


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
        self.assertEqual(set(), required - names)

    def test_distribution_artifact_supports_phase6_cli_and_import_smoke(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dist_dir = Path(temp_dir) / "dist"
            extract_dir = Path(temp_dir) / "extracted"
            zip_path = _build_artifact(dist_dir)
            with ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            skill_dir = extract_dir / "decide-me"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(skill_dir)

            subprocess.run(
                [sys.executable, str(skill_dir / "scripts" / "decide_me.py"), "show-impact", "--help"],
                cwd=skill_dir,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=CLI_TIMEOUT_SECONDS,
            )
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


@contextmanager
def _built_artifact() -> Iterator[ZipFile]:
    with TemporaryDirectory() as temp_dir:
        dist_dir = Path(temp_dir) / "dist"
        with ZipFile(_build_artifact(dist_dir)) as archive:
            yield archive


def _build_artifact(dist_dir: Path) -> Path:
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
        timeout=CLI_TIMEOUT_SECONDS,
    )
    return dist_dir / "decide-me.zip"


if __name__ == "__main__":
    unittest.main()
