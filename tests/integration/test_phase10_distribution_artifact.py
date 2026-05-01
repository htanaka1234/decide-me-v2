from __future__ import annotations

import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


class Phase10DistributionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = BuiltArtifact()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact.cleanup()

    def test_distribution_contains_public_evaluation_contracts(self) -> None:
        names = self.artifact.names()

        required = {
            "decide-me/references/evaluation-suite.md",
            "decide-me/schemas/evaluation-scenario.schema.json",
            "decide-me/schemas/evaluation-report.schema.json",
        }

        self.assertEqual(set(), required - names)

    def test_distribution_excludes_development_evaluation_suite_files(self) -> None:
        names = self.artifact.names()

        self.assertNotIn("decide-me/scripts/evaluate_scenarios.py", names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any("tests/scenarios" in name for name in names))
        self.assertFalse(any("expected_outputs" in name for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))
        self.assertFalse(any("/.git/" in name or name.startswith("decide-me/.git/") for name in names))
        self.assertFalse(any("/dist/" in name or name.startswith("decide-me/dist/") for name in names))

    def test_distribution_reference_documents_phase10_boundary(self) -> None:
        reference = self.artifact.read_text("decide-me/references/evaluation-suite.md")

        for expected in [
            "include: `references/evaluation-suite.md`",
            "include: `schemas/evaluation-scenario.schema.json`",
            "include: `schemas/evaluation-report.schema.json`",
            "exclude: `tests/scenarios/**`",
            "exclude: `scripts/evaluate_scenarios.py`",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)


if __name__ == "__main__":
    unittest.main()
