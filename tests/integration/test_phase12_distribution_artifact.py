from __future__ import annotations

import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


class Phase12DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_source_store_runtime_contracts(self) -> None:
        names = self.artifact.names()

        required = {
            "decide-me/decide_me/sources/__init__.py",
            "decide-me/decide_me/sources/decompose.py",
            "decide-me/decide_me/sources/index.py",
            "decide-me/decide_me/sources/model.py",
            "decide-me/decide_me/sources/runtime.py",
            "decide-me/decide_me/sources/store.py",
            "decide-me/references/evidence-source-store.md",
            "decide-me/schemas/evidence-search.schema.json",
            "decide-me/schemas/normative-unit.schema.json",
            "decide-me/schemas/source-document.schema.json",
            "decide-me/schemas/source-registry.schema.json",
        }

        self.assertEqual(set(), required - names)

    def test_distribution_documents_phase12_source_store_boundary(self) -> None:
        skill = self.artifact.read_text("decide-me/SKILL.md")
        reference = self.artifact.read_text("decide-me/references/evidence-source-store.md")

        for expected in (
            "references/evidence-source-store.md",
            "source_document_imported",
            "normative_units_extracted",
            "source_version_updated",
            "evidence_linked_to_object",
            "metadata.source = \"source-store\"",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, skill + "\n" + reference)

    def test_distribution_excludes_phase12_development_gate(self) -> None:
        names = self.artifact.names()

        self.assertNotIn("decide-me/scripts/run_phase12_gate.py", names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))


if __name__ == "__main__":
    unittest.main()
