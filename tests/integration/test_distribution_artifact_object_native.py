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
BANNED_TERMS = (
    "accepted" + "_decisions",
    "deferred" + "_decisions",
    "evidence" + "_refs",
    "proposal" + "_issued",
    "proposal" + "_accepted",
    "decision" + "_discovered",
    "decision" + "_resolved_by_evidence",
    "compatibility" + "_backfilled",
    "action" + "_slices",
    "candidate" + "_action" + "_slices",
    "implementation" + "_ready_slices",
    "candidate" + "_workstreams",
    "unresolved" + "_blockers",
    "unresolved" + "_risks",
    "action" + "_slice",
    "action" + "-slice",
    "Action " + "Slices",
    "Implementation-ready " + "Slices",
    "Implementation-Ready " + "Slices",
)


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
        findings = []
        with _built_artifact() as archive:
            for name in archive.namelist():
                if not _is_text_file(name):
                    continue
                text = archive.read(name).decode("utf-8")
                for term in BANNED_TERMS:
                    if term in text:
                        findings.append(f"{name} contains {term!r}")

        self.assertEqual([], findings)


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


def _is_text_file(name: str) -> bool:
    return Path(name).suffix in {
        ".json",
        ".md",
        ".mdc",
        ".py",
        ".txt",
        ".yaml",
        ".yml",
    }


if __name__ == "__main__":
    unittest.main()
