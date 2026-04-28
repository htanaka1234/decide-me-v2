from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.impact_runtime import (
    build_impact_runtime,
    delete_derived_projection_files,
    run_json_cli,
    semantic_bounded_graph,
    semantic_candidates,
    semantic_impact,
)


class ImpactRebuildRoundtripTests(unittest.TestCase):
    def test_rebuild_recreates_graph_impact_candidates_and_bounded_graph(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = build_impact_runtime(Path(tmp))
            before_impact = _show_impact(ai_dir)
            before_candidates = _show_candidates(ai_dir)
            before_graph = _show_stack(ai_dir)

            delete_derived_projection_files(ai_dir)
            rebuilt = run_json_cli("rebuild-projections", "--ai-dir", str(ai_dir))
            validation = run_json_cli("validate-state", "--ai-dir", str(ai_dir))
            after_impact = _show_impact(ai_dir)
            after_candidates = _show_candidates(ai_dir)
            after_graph = _show_stack(ai_dir)

            self.assertIn("project_state", rebuilt)
            self.assertTrue(validation["ok"])
            self.assertEqual([], validation["issues"])
            self.assertEqual(semantic_impact(before_impact), semantic_impact(after_impact))
            self.assertEqual(semantic_candidates(before_candidates), semantic_candidates(after_candidates))
            self.assertEqual(semantic_bounded_graph(before_graph), semantic_bounded_graph(after_graph))


def _show_impact(ai_dir: Path) -> dict:
    return run_json_cli(
        "show-impact",
        "--ai-dir",
        str(ai_dir),
        "--object-id",
        "CON-001",
        "--change-kind",
        "changed",
        "--max-depth",
        "4",
    )


def _show_candidates(ai_dir: Path) -> dict:
    return run_json_cli(
        "show-invalidation-candidates",
        "--ai-dir",
        str(ai_dir),
        "--object-id",
        "CON-001",
        "--change-kind",
        "changed",
        "--max-depth",
        "4",
    )


def _show_stack(ai_dir: Path) -> dict:
    return run_json_cli(
        "show-decision-stack",
        "--ai-dir",
        str(ai_dir),
        "--object-id",
        "DEC-001",
        "--upstream-depth",
        "1",
        "--downstream-depth",
        "3",
    )


if __name__ == "__main__":
    unittest.main()
