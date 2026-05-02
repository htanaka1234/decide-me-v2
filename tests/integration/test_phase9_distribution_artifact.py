from __future__ import annotations

import stat
import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


class Phase9DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_domain_pack_files(self) -> None:
        names = self.artifact.names()

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
            "decide-me/decide_me/domains/packs/operations.yaml",
            "decide-me/decide_me/domains/packs/personal_planning.yaml",
            "decide-me/decide_me/domains/packs/writing.yaml",
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
        modes = self.artifact.modes()
        requirements = self.artifact.read_text("decide-me/requirements.txt").splitlines()

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
        ai_dir = self.artifact.root / ".ai" / "decide-me"

        listed = self.artifact.run_packaged_json(
            "list-domain-packs",
            "--ai-dir",
            str(ai_dir),
        )
        shown = self.artifact.run_packaged_json(
            "show-domain-pack",
            "--ai-dir",
            str(ai_dir),
            "--pack-id",
            "research",
        )
        help_result = self.artifact.run_packaged_cli("export-document", "--help")
        self.artifact.run_packaged_json(
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
        exported = self.artifact.run_packaged_json(
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
            [
                "generic",
                "operations",
                "personal_planning",
                "procurement",
                "research",
                "software",
                "writing",
            ],
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


if __name__ == "__main__":
    unittest.main()
