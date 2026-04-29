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


class Phase7DistributionArtifactTests(unittest.TestCase):
    def test_distribution_contains_phase7_safety_files(self) -> None:
        with _built_artifact() as archive:
            names = set(archive.namelist())

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
                [sys.executable, str(skill_dir / "scripts" / "decide_me.py"), "approve-safety-gate", "--help"],
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
