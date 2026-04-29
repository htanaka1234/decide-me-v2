from __future__ import annotations

import json
import os
import stat
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
CLI_TIMEOUT_SECONDS = 30


class DistributionArtifactObjectNativeTests(unittest.TestCase):
    def test_distribution_contains_only_installable_skill_surface(self) -> None:
        with _built_artifact() as archive:
            names = set(archive.namelist())

        required = {
            "decide-me/SKILL.md",
            "decide-me/agents/openai.yaml",
            "decide-me/decide_me/__init__.py",
            "decide-me/decide_me/events.py",
            "decide-me/decide_me/impact_analysis.py",
            "decide-me/decide_me/impact_report.py",
            "decide-me/decide_me/invalidation_candidates.py",
            "decide-me/decide_me/interview.py",
            "decide-me/decide_me/lifecycle.py",
            "decide-me/decide_me/planner.py",
            "decide-me/decide_me/projections.py",
            "decide-me/decide_me/store.py",
            "decide-me/decide_me/validate.py",
            "decide-me/references/impact-analysis.md",
            "decide-me/references/invalidation-candidates.md",
            "decide-me/scripts/decide_me.py",
            "decide-me/schemas/close-summary.schema.json",
            "decide-me/schemas/impact-analysis.schema.json",
            "decide-me/schemas/invalidation-candidates.schema.json",
            "decide-me/schemas/plan.schema.json",
            "decide-me/templates/impact-report-template.md",
            "decide-me/templates/plan-template.md",
        }
        self.assertTrue(required.issubset(names))
        for forbidden in {
            "decide-me/README.md",
            "decide-me/AGENTS.md",
            "decide-me/references/migration-from-legacy-model.md",
        }:
            self.assertNotIn(forbidden, names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))
        self.assertFalse(any("/.git/" in name or name.startswith("decide-me/.git/") for name in names))

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

    def test_distribution_schemas_are_object_native(self) -> None:
        with _built_artifact() as archive:
            close_schema = json.loads(_read_text(archive, "decide-me/schemas/close-summary.schema.json"))
            plan_schema = json.loads(_read_text(archive, "decide-me/schemas/plan.schema.json"))

        self.assertEqual(
            {"work_item", "readiness", "object_ids", "link_ids", "generated_at"},
            set(close_schema["required"]),
        )
        self.assertFalse(close_schema.get("additionalProperties", True))

        action_plan_schema = _action_plan_object_schema(plan_schema)
        self.assertTrue(
            {
                "actions",
                "implementation_ready_actions",
                "evidence",
                "source_object_ids",
                "source_link_ids",
            }.issubset(set(action_plan_schema["required"]))
        )
        self.assertFalse(action_plan_schema.get("additionalProperties", True))
        action_plan_props = action_plan_schema["properties"]
        self.assertIn("actions", action_plan_props)
        self.assertIn("implementation_ready_actions", action_plan_props)
        self.assertIn("evidence", action_plan_props)
        self.assertIn("source_object_ids", action_plan_props)
        self.assertIn("source_link_ids", action_plan_props)
        self.assertNotIn("action" + "_slices", action_plan_props)
        self.assertNotIn("implementation" + "_ready_slices", action_plan_props)

    def test_distribution_file_modes_are_normalized(self) -> None:
        with _built_artifact() as archive:
            modes = {name: archive.getinfo(name).external_attr >> 16 for name in archive.namelist()}

        for name, mode in modes.items():
            with self.subTest(name=name):
                expected = stat.S_IFREG | (0o755 if name == "decide-me/scripts/decide_me.py" else 0o644)
                self.assertEqual(expected, mode)


def _read_text(archive: ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def _action_plan_object_schema(plan_schema: dict) -> dict:
    return next(
        option
        for option in plan_schema["properties"]["action_plan"]["oneOf"]
        if option.get("type") == "object"
    )


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
            timeout=CLI_TIMEOUT_SECONDS,
        )
        with ZipFile(dist_dir / "decide-me.zip") as archive:
            yield archive


if __name__ == "__main__":
    unittest.main()
