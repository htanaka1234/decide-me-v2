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


class Phase8DistributionArtifactTests(unittest.TestCase):
    def test_distribution_contains_document_compiler_files(self) -> None:
        with _built_artifact() as archive:
            names = set(archive.namelist())

        required = {
            "decide-me/decide_me/documents/__init__.py",
            "decide-me/decide_me/documents/context.py",
            "decide-me/decide_me/documents/model.py",
            "decide-me/decide_me/documents/compiler.py",
            "decide-me/decide_me/documents/registry.py",
            "decide-me/decide_me/documents/merge.py",
            "decide-me/decide_me/documents/render_markdown.py",
            "decide-me/decide_me/documents/render_json.py",
            "decide-me/decide_me/documents/render_csv.py",
            "decide-me/decide_me/exporters/documents.py",
            "decide-me/schemas/document-model.schema.json",
            "decide-me/references/document-compiler.md",
            "decide-me/templates/documents/decision-brief.md",
            "decide-me/templates/documents/action-plan.md",
            "decide-me/templates/documents/risk-register.md",
            "decide-me/templates/documents/review-memo.md",
            "decide-me/templates/documents/research-plan.md",
            "decide-me/templates/documents/comparison-table.md",
        }
        self.assertEqual(set(), required - names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))
        self.assertFalse(any("/.git/" in name or name.startswith("decide-me/.git/") for name in names))

    def test_distribution_supports_export_document_help(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dist_dir = Path(temp_dir) / "dist"
            extract_dir = Path(temp_dir) / "extracted"
            zip_path = _build_artifact(dist_dir)
            with ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            skill_dir = extract_dir / "decide-me"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(skill_dir)

            result = subprocess.run(
                [sys.executable, str(skill_dir / "scripts" / "decide_me.py"), "export-document", "--help"],
                cwd=skill_dir,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=CLI_TIMEOUT_SECONDS,
            )
            self.assertIn("decision-brief", result.stdout)
            self.assertIn("comparison-table", result.stdout)


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
