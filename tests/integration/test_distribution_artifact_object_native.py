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

from tests.helpers.legacy_term_policy import format_findings, zip_legacy_term_findings


REPO_ROOT = Path(__file__).resolve().parents[2]


class DistributionArtifactObjectNativeTests(unittest.TestCase):
    def test_distribution_documents_object_native_contracts(self) -> None:
        with _built_artifact() as archive:
            skill = _read_text(archive, "decide-me/SKILL.md")
            plan_template = _read_text(archive, "decide-me/templates/plan-template.md")

        self.assertIn("close_summary.object_ids", skill)
        self.assertIn("close_summary.link_ids", skill)
        self.assertIn("action_plan.actions", skill)
        self.assertIn("action_plan.implementation_ready_actions", skill)
        self.assertIn("## Actions", plan_template)
        self.assertIn("## Implementation-Ready Actions", plan_template)

    def test_distribution_text_files_do_not_expose_legacy_terms(self) -> None:
        with _built_artifact() as archive:
            findings = zip_legacy_term_findings(archive)

        self.assertEqual([], format_findings(findings))

    def test_distribution_excludes_migration_reference(self) -> None:
        with _built_artifact() as archive:
            self.assertNotIn("decide-me/references/migration-from-legacy-model.md", archive.namelist())


def _read_text(archive: ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


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
