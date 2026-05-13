from __future__ import annotations

import unittest
from pathlib import Path

from tests.helpers.distribution_artifact import BuiltArtifact
from tests.helpers.cli import run_cli


REPO_ROOT = Path(__file__).resolve().parents[2]


class PR4GoalSkillDocumentationTests(unittest.TestCase):
    def test_skill_lists_goal_draft_references_and_command(self) -> None:
        skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("references/goal-autopilot-drafting.md", skill)
        self.assertIn("references/draft-decision-sets.md", skill)
        self.assertIn("`/goal`", skill)
        self.assertIn("create-draft-set", skill)
        self.assertIn("export-draft-set", skill)

    def test_goal_reference_documents_existing_cli_not_future_cli(self) -> None:
        ref = (REPO_ROOT / "references" / "goal-autopilot-drafting.md").read_text(encoding="utf-8")

        self.assertIn("create-draft-set", ref)
        self.assertIn("export-draft-set", ref)
        self.assertIn("DRAFT / NOT ACCEPTED", ref)
        self.assertIn("Skill-only", ref)
        self.assertIn("An `autopilot-draft` CLI does not exist", ref)

    def test_draft_set_reference_documents_sidecar_boundary(self) -> None:
        ref = (REPO_ROOT / "references" / "draft-decision-sets.md").read_text(encoding="utf-8")

        self.assertIn("sidecar", ref)
        self.assertIn("not canonical", ref)
        self.assertIn("promotion-log.jsonl", ref)
        self.assertIn("draft_origin", ref)
        self.assertIn("DRAFT / NOT ACCEPTED", ref)

    def test_related_references_document_pr4_boundaries(self) -> None:
        output_contract = (REPO_ROOT / "references" / "output-contract.md").read_text(encoding="utf-8")
        event_model = (REPO_ROOT / "references" / "event-and-projection-model.md").read_text(encoding="utf-8")
        document_compiler = (REPO_ROOT / "references" / "document-compiler.md").read_text(encoding="utf-8")

        self.assertIn("`/goal` Skill command, not a CLI subcommand", output_contract)
        self.assertIn("Draft sidecar commands:", output_contract)
        self.assertIn("Draft promotion commands:", output_contract)
        self.assertIn("Other derived export commands:", output_contract)
        self.assertIn("create-draft-set", output_contract)
        self.assertIn("Draft set files under `.ai/decide-me/draft-sets/` are not canonical", event_model)
        self.assertIn("promotion-log.jsonl", event_model)
        self.assertIn("not produced by the generic Document Compiler", document_compiler)

    def test_root_cli_help_does_not_expose_autopilot_draft_command(self) -> None:
        result = run_cli("--help", cwd=REPO_ROOT)

        self.assertNotIn("autopilot-draft", result.stdout + result.stderr)

    def test_readme_documents_goal_quick_start(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("### Goal-based draft decision sets", readme)
        self.assertIn("`/goal`", readme)
        self.assertIn("DRAFT / NOT ACCEPTED", readme)
        self.assertIn("create-draft-set", readme)
        self.assertIn("show-draft-set", readme)
        self.assertIn("list-draft-sets", readme)

    def test_distribution_contains_pr4_goal_references(self) -> None:
        with BuiltArtifact() as artifact:
            names = artifact.names()

        self.assertIn("decide-me/references/goal-autopilot-drafting.md", names)
        self.assertIn("decide-me/references/draft-decision-sets.md", names)


if __name__ == "__main__":
    unittest.main()
