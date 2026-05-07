from __future__ import annotations

from pathlib import PurePosixPath
import unittest

from tests.helpers.distribution_artifact import BuiltArtifact


class Phase11DistributionArtifactTests(unittest.TestCase):
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
        script_names = {name for name in names if name.startswith("decide-me/scripts/")}

        self.assertEqual({"decide-me/scripts/decide_me.py"}, script_names)
        self.assertNotIn("decide-me/scripts/evaluate_scenarios.py", names)
        self.assertFalse(any(name.startswith("decide-me/tests/") for name in names))
        self.assertFalse(any(_is_scenario_fixture_path(name) for name in names))
        self.assertFalse(any(_has_path_part(name, "expected_outputs") for name in names))
        self.assertFalse(any("/.ai/" in name or name.startswith("decide-me/.ai/") for name in names))
        self.assertFalse(any("/.git/" in name or name.startswith("decide-me/.git/") for name in names))
        self.assertFalse(any("/dist/" in name or name.startswith("decide-me/dist/") for name in names))
        self.assertFalse(any(_has_path_part(name, "__pycache__") for name in names))
        self.assertFalse(any(name.endswith((".pyc", ".pyo")) for name in names))

    def test_distribution_reference_documents_phase11_boundary(self) -> None:
        reference = self.artifact.read_text("decide-me/references/evaluation-suite.md")

        for expected in [
            "include: `references/evaluation-suite.md`",
            "include: `schemas/evaluation-scenario.schema.json`",
            "include: `schemas/evaluation-report.schema.json`",
            "exclude: `tests/scenarios/**`",
            "exclude: `scripts/evaluate_scenarios.py`",
            "exclude: `__pycache__/**`",
            "exclude: `*.pyc`",
            "exclude: `*.pyo`",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)


def _has_path_part(name: str, part: str) -> bool:
    return part in PurePosixPath(name).parts


def _is_scenario_fixture_path(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return len(parts) >= 3 and parts[:3] == ("decide-me", "tests", "scenarios")


if __name__ == "__main__":
    unittest.main()
