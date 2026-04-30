from __future__ import annotations

import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


class Phase8DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_document_compiler_files(self) -> None:
        names = self.artifact.names()

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
        result = self.artifact.run_packaged_cli("export-document", "--help")
        self.assertIn("decision-brief", result.stdout)
        self.assertIn("comparison-table", result.stdout)


if __name__ == "__main__":
    unittest.main()
