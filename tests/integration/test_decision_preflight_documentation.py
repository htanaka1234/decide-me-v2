from __future__ import annotations

import unittest
from pathlib import Path

from tests.helpers.distribution_artifact import BuiltArtifact
from tests.helpers.cli import run_cli


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_NOTE = (
    "Interpreting this as Decision Preflight. In Codex CLI, raw /goal belongs to Codex; "
    "decide-me uses Decision Preflight / decide-me:preflight."
)


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class DecisionPreflightDocumentationTests(unittest.TestCase):
    def test_skill_lists_decision_preflight_without_public_goal_command(self) -> None:
        skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        startup_checklist_section = _section(
            skill,
            "Startup checklist:",
            "Read only the reference file needed for the turn:",
        )
        user_facing_commands_section = _section(skill, "User-facing commands:", "Runtime invariants:")

        self.assertIn("references/decision-preflight.md", skill)
        self.assertNotIn("references/goal-autopilot-drafting.md", skill)
        self.assertIn("references/draft-decision-sets.md", skill)
        self.assertNotIn("- `/goal`", user_facing_commands_section)
        self.assertNotIn("`/goal`", user_facing_commands_section)
        self.assertNotIn("When the user starts with `/goal`", startup_checklist_section)
        self.assertIn("When the user asks for `Decision Preflight`", startup_checklist_section)
        self.assertIn("do not treat it as a silent legacy alias", startup_checklist_section)
        self.assertIn("clearly asks for draft decision", startup_checklist_section)
        self.assertIn("expansion", startup_checklist_section)
        self.assertIn("Otherwise, treat raw `/goal` as", startup_checklist_section)
        self.assertIn("Codex-owned syntax", startup_checklist_section)
        self.assertIn("Interpreting this as Decision Preflight", startup_checklist_section)
        self.assertIn("Decision Preflight", skill)
        self.assertIn("decide-me:preflight", skill)
        self.assertIn("Create decision preflight from goal", user_facing_commands_section)
        self.assertIn("Run decision preflight", user_facing_commands_section)
        self.assertIn("Show decision preflight DS-...", user_facing_commands_section)
        self.assertIn("Export decision preflight DS-...", user_facing_commands_section)
        self.assertIn("create-draft-set", skill)
        self.assertIn("export-draft-set", skill)

    def test_decision_preflight_reference_documents_autopilot_cli_boundary(self) -> None:
        ref = (REPO_ROOT / "references" / "decision-preflight.md").read_text(encoding="utf-8")

        self.assertIn("# Decision Preflight", ref)
        self.assertIn(
            "It may run inside a Codex native `/goal`, but it is not itself named `/goal`.",
            ref,
        )
        self.assertIn("Codex native `/goal`:", ref)
        self.assertIn("outer durable objective mechanism", ref)
        self.assertIn("Decision Preflight:", ref)
        self.assertIn("inner decide-me draft decision set flow", ref)
        self.assertIn("Raw `/goal` is retired as a public decide-me command.", ref)
        self.assertIn("do not treat it as a silent legacy alias", ref)
        self.assertIn("clearly asks for draft decision expansion", ref)
        self.assertIn("Otherwise, treat raw `/goal` as", ref)
        self.assertIn("Codex-owned syntax", ref)
        self.assertIn(MIGRATION_NOTE, ref)
        self.assertIn("Do not include the note in normal Decision Preflight responses", ref)
        self.assertNotIn("# Goal Autopilot Drafting", ref)
        self.assertNotIn("goal-autopilot-drafting", ref)
        self.assertIn("create-draft-set", ref)
        self.assertIn("export-draft-set", ref)
        self.assertIn("autopilot-draft", ref)
        self.assertIn("deterministic gap iteration", ref)
        self.assertIn("DRAFT / NOT ACCEPTED", ref)
        self.assertIn("does not create accepted decisions", ref)
        self.assertIn("canonical event count is unchanged", ref)
        self.assertIn("## State Ownership", ref)
        self.assertIn("`draft-set.json` is the source sidecar", ref)
        self.assertIn("`goal`, `source_context`, `draft_decisions`, and the Phase 1 `exploration_contract`", ref)
        self.assertIn("must not store\n" "derived diagnostic state", ref)
        self.assertIn("`draft-projection.json` is a derived sidecar", ref)
        self.assertIn("`coverage_matrix`, `coverage_summary`, the Phase 5 derived `frontier_queue`", ref)
        self.assertIn("Diagnostics and coverage are never written back into\n" "`draft-set.json`", ref)
        self.assertIn("`review-queue.json` is a derived promotion handoff queue", ref)
        self.assertIn(
            "The canonical event log, `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` are\n"
            "immutable during Decision Preflight.",
            ref,
        )
        self.assertIn("Blocking derived gaps\nforce blocked convergence and reporting", ref)
        self.assertIn("Decision Preflight must not call promotion commands", ref)

    def test_draft_set_reference_documents_sidecar_boundary(self) -> None:
        ref = (REPO_ROOT / "references" / "draft-decision-sets.md").read_text(encoding="utf-8")

        self.assertIn("sidecar", ref)
        self.assertIn("not canonical", ref)
        self.assertIn("promotion-log.jsonl", ref)
        self.assertIn("draft-projection.json", ref)
        self.assertIn("draft_origin", ref)
        self.assertIn("DRAFT / NOT ACCEPTED", ref)
        self.assertIn("reconcile-draft-promotions", ref)
        self.assertIn("Projection convergence is fail-closed", ref)

    def test_related_references_document_pr4_boundaries(self) -> None:
        output_contract = (REPO_ROOT / "references" / "output-contract.md").read_text(encoding="utf-8")
        event_model = (REPO_ROOT / "references" / "event-and-projection-model.md").read_text(encoding="utf-8")
        document_compiler = (REPO_ROOT / "references" / "document-compiler.md").read_text(encoding="utf-8")
        draft_sidecar_commands = _section(
            output_contract,
            "Draft sidecar commands:",
            "Draft promotion commands:",
        )

        self.assertIn("Codex native `/goal` may wrap decide-me Decision Preflight", output_contract)
        self.assertIn("Decision Preflight is the decide-me Skill flow", output_contract)
        self.assertNotIn("goal-autopilot-drafting", output_contract)
        self.assertIn("Raw `/goal` is a Codex CLI namespace", output_contract)
        self.assertIn("do not treat\nit as a silent legacy alias", output_contract)
        self.assertIn("clearly asks for draft decision expansion", output_contract)
        self.assertIn("Otherwise, treat raw `/goal` as Codex-owned syntax", output_contract)
        self.assertIn(MIGRATION_NOTE, output_contract)
        self.assertNotIn("`/goal`", draft_sidecar_commands)
        self.assertNotIn("/goal", draft_sidecar_commands)
        self.assertIn("Projection convergence must fail closed", output_contract)
        self.assertIn("canonical event count unchanged", output_contract)
        self.assertIn("autopilot-draft", output_contract)
        self.assertIn("project-draft-set", output_contract)
        self.assertIn("Draft sidecar commands:", output_contract)
        self.assertIn("Draft promotion commands:", output_contract)
        self.assertIn("reconcile-draft-promotions", output_contract)
        self.assertIn("Other derived export commands:", output_contract)
        self.assertIn("create-draft-set", output_contract)
        self.assertIn("User-facing Decision Preflight requests:", output_contract)
        self.assertIn("Create decision preflight from goal:", output_contract)
        self.assertIn("/goal Run decide-me Decision Preflight for <objective>.", output_contract)
        self.assertIn(
            "/goal Run decide-me Decision Preflight for <objective>.\n"
            "Done when:\n"
            "- validate-state --cached passes\n"
            "- draft sidecars and Markdown exports are generated\n"
            "- review queue summary is reported\n"
            "- canonical event count is unchanged",
            output_contract,
        )
        self.assertNotIn(
            "/goal Use decide-me to create a DRAFT / NOT ACCEPTED decision set for",
            output_contract,
        )
        self.assertNotIn("- Codex native `/goal`", output_contract)
        self.assertIn("Draft set files under `.ai/decide-me/draft-sets/` are not canonical", event_model)
        self.assertIn("draft projection", event_model)
        self.assertIn("promotion-log.jsonl", event_model)
        self.assertIn("not produced by the generic Document Compiler", document_compiler)

    def test_root_cli_help_exposes_autopilot_draft_command_after_pr5(self) -> None:
        result = run_cli("--help", cwd=REPO_ROOT)

        self.assertIn("autopilot-draft", result.stdout + result.stderr)
        self.assertIn("project-draft-set", result.stdout + result.stderr)

    def test_readme_documents_goal_quick_start(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("### Decision Preflight Draft Decision Sets", readme)
        self.assertIn("Create decision preflight from goal:", readme)
        self.assertIn(
            "Use decide-me to create a DRAFT / NOT ACCEPTED decision set for",
            readme,
        )
        self.assertIn("Codex native `/goal` can wrap Decision Preflight", readme)
        self.assertIn("/goal Run decide-me Decision Preflight for", readme)
        self.assertIn(
            "/goal Run decide-me Decision Preflight for Add goal-based draft decision sets to decide-me.\n"
            "Done when:\n"
            "- validate-state --cached passes\n"
            "- draft sidecars and Markdown exports are generated\n"
            "- review queue summary is reported\n"
            "- canonical event count is unchanged",
            readme,
        )
        self.assertNotIn(
            "/goal Use decide-me to create a DRAFT / NOT ACCEPTED decision set for",
            readme,
        )
        self.assertIn("DRAFT / NOT ACCEPTED", readme)
        self.assertIn("create-draft-set", readme)
        self.assertIn("show-draft-set", readme)
        self.assertIn("list-draft-sets", readme)

    def test_distribution_contains_decision_preflight_references(self) -> None:
        with BuiltArtifact() as artifact:
            names = artifact.names()

        self.assertIn("decide-me/references/decision-preflight.md", names)
        self.assertNotIn("decide-me/references/goal-autopilot-drafting.md", names)
        self.assertIn("decide-me/references/draft-decision-sets.md", names)


if __name__ == "__main__":
    unittest.main()
