from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_TIMEOUT_SECONDS = 30


class Phase9DistributionArtifactTests(unittest.TestCase):
    def test_distribution_contains_domain_pack_files(self) -> None:
        with _built_artifact() as archive:
            names = set(archive.namelist())

        required = {
            "decide-me/requirements.txt",
            "decide-me/decide_me/domains/__init__.py",
            "decide-me/decide_me/domains/apply.py",
            "decide-me/decide_me/domains/infer.py",
            "decide-me/decide_me/domains/loader.py",
            "decide-me/decide_me/domains/model.py",
            "decide-me/decide_me/domains/registry.py",
            "decide-me/decide_me/domains/validate.py",
            "decide-me/decide_me/domains/packs/generic.yaml",
            "decide-me/decide_me/domains/packs/software.yaml",
            "decide-me/decide_me/domains/packs/research.yaml",
            "decide-me/decide_me/domains/packs/procurement.yaml",
            "decide-me/schemas/domain-pack.schema.json",
            "decide-me/references/domain-packs.md",
            "decide-me/templates/documents/action-plan.md",
            "decide-me/templates/documents/comparison-table.md",
            "decide-me/templates/documents/decision-brief.md",
            "decide-me/templates/documents/research-plan.md",
            "decide-me/templates/documents/review-memo.md",
            "decide-me/templates/documents/risk-register.md",
        }
        self.assertEqual(set(), required - names)
        self.assertNotIn("decide-me/requirements-dev.txt", names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))
        self.assertFalse(any("/.git/" in name or name.startswith("decide-me/.git/") for name in names))

    def test_distribution_declares_runtime_dependency_and_normal_file_modes(self) -> None:
        with _built_artifact() as archive:
            modes = {name: archive.getinfo(name).external_attr >> 16 for name in archive.namelist()}
            requirements = _read_text(archive, "decide-me/requirements.txt").splitlines()

        checked_names = [
            name
            for name in modes
            if name == "decide-me/requirements.txt"
            or name.startswith("decide-me/decide_me/domains/")
            or name == "decide-me/schemas/domain-pack.schema.json"
            or name == "decide-me/references/domain-packs.md"
            or name.startswith("decide-me/templates/documents/")
        ]
        self.assertIn("PyYAML>=6.0", requirements)
        self.assertTrue(checked_names)
        for name in checked_names:
            with self.subTest(name=name):
                self.assertEqual(stat.S_IFREG | 0o644, modes[name])

    def test_distribution_supports_domain_pack_cli_smoke(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dist_dir = Path(temp_dir) / "dist"
            extract_dir = Path(temp_dir) / "extracted"
            ai_dir = Path(temp_dir) / ".ai" / "decide-me"
            zip_path = _build_artifact(dist_dir)
            with ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            skill_dir = extract_dir / "decide-me"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(skill_dir)
            cli = skill_dir / "scripts" / "decide_me.py"

            listed = _run_json(
                cli,
                env,
                "list-domain-packs",
                "--ai-dir",
                str(ai_dir),
            )
            shown = _run_json(
                cli,
                env,
                "show-domain-pack",
                "--ai-dir",
                str(ai_dir),
                "--pack-id",
                "research",
            )
            help_result = _run_cli(cli, env, "export-document", "--help")
            _run_json(
                cli,
                env,
                "bootstrap",
                "--ai-dir",
                str(ai_dir),
                "--project-name",
                "Artifact Smoke",
                "--objective",
                "Exercise packaged Domain Pack export.",
                "--current-milestone",
                "Phase 9 distribution",
            )
            output = ai_dir / "exports" / "documents" / "research-plan.md"
            exported = _run_json(
                cli,
                env,
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "research-plan",
                "--domain-pack",
                "research",
                "--format",
                "markdown",
                "--output",
                str(output),
            )
            exported_path_exists = output.is_file()

        self.assertEqual("ok", listed["status"])
        self.assertEqual(
            ["generic", "procurement", "research", "software"],
            [item["pack_id"] for item in listed["packs"]],
        )
        self.assertEqual("ok", shown["status"])
        self.assertEqual("research", shown["pack"]["pack_id"])
        self.assertTrue(shown["digest"].startswith("DP-"))
        self.assertIn("--domain-pack", help_result.stdout)
        self.assertEqual(str(output), exported["path"])
        self.assertTrue(exported_path_exists)
        self.assertTrue(exported["domain_pack_applied"])
        self.assertEqual("research", exported["domain_pack_id"])
        self.assertEqual("research_protocol", exported["document_profile_id"])


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


def _run_json(cli: Path, env: dict[str, str], *args: str) -> dict:
    return json.loads(_run_cli(cli, env, *args).stdout)


def _run_cli(cli: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(cli), *args],
        cwd=cli.parents[1],
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=CLI_TIMEOUT_SECONDS,
    )


def _read_text(archive: ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


if __name__ == "__main__":
    unittest.main()
