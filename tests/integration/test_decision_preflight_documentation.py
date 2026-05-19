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


def _squash_ws(text: str) -> str:
    return " ".join(text.split())


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
        self.assertIn("schema_version: 2", skill)
        self.assertIn("exploration_contract", skill)
        self.assertIn("Coverage matrices, coverage summaries, convergence, frontier queues", skill)
        self.assertIn("Create decision preflight from goal", user_facing_commands_section)
        self.assertIn("Run decision preflight", user_facing_commands_section)
        self.assertIn("Show decision preflight DS-...", user_facing_commands_section)
        self.assertIn("Export decision preflight DS-...", user_facing_commands_section)
        self.assertIn("create-draft-set", skill)
        self.assertIn("export-draft-set", skill)

    def test_decision_preflight_reference_documents_autopilot_cli_boundary(self) -> None:
        ref = (REPO_ROOT / "references" / "decision-preflight.md").read_text(encoding="utf-8")
        normalized_ref = _squash_ws(ref)

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
        self.assertIn("`draft-set.json` is the source sidecar", normalized_ref)
        self.assertIn(
            "`goal`, `source_context`, `draft_decisions`, and the Phase 1 `exploration_contract`",
            normalized_ref,
        )
        self.assertIn("must not store derived diagnostic state", normalized_ref)
        self.assertIn("coverage matrices, gap classifiers, convergence, frontier queues, or review queues", normalized_ref)
        self.assertIn("`draft-projection.json` is a derived sidecar", normalized_ref)
        self.assertIn(
            "`coverage_matrix`, `coverage_summary`, the Phase 5 derived `frontier_queue`",
            normalized_ref,
        )
        self.assertIn("Diagnostics and coverage are never written back into `draft-set.json`", normalized_ref)
        self.assertIn("DraftProjection uses `schema_version: 3`", normalized_ref)
        self.assertIn("`review-queue.json` is a derived promotion handoff queue", normalized_ref)
        self.assertIn(
            "The canonical event log, `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` "
            "are immutable during Decision Preflight.",
            normalized_ref,
        )
        self.assertIn("Blocking derived gaps force blocked convergence and reporting", normalized_ref)
        self.assertIn("Decision Preflight must not call promotion commands", normalized_ref)
        self.assertIn("Decision Preflight fails closed", normalized_ref)
        self.assertIn(
            "must not infer convergence, sufficient evidence, or bulk promotability from missing diagnostics",
            normalized_ref,
        )
        self.assertIn("DraftDecisionSet uses `schema_version: 2`", normalized_ref)
        self.assertIn("`exploration_contract` is defaulted as source input", normalized_ref)
        self.assertIn("`core.layer.strategy`", normalized_ref)
        self.assertIn("`autopilot-draft` records the actual CLI budgets", normalized_ref)
        self.assertIn("`project-draft-set` builds `coverage_matrix`", normalized_ref)
        self.assertIn("Required P0/P1 rows with `status=partial` or `status=missing`", normalized_ref)
        self.assertIn("Low-risk P2/P3 non-required rows do not block convergence", normalized_ref)
        self.assertIn("derives `frontier_queue` from blocking coverage gap diagnostics", normalized_ref)
        self.assertIn("must not upgrade evidence coverage", normalized_ref)
        self.assertIn("Coverage summary: required=N, covered=N, partial=N, missing=N, blocking=N", ref)

    def test_draft_set_reference_documents_sidecar_boundary(self) -> None:
        ref = (REPO_ROOT / "references" / "draft-decision-sets.md").read_text(encoding="utf-8")
        normalized_ref = _squash_ws(ref)

        self.assertIn("sidecar", ref)
        self.assertIn("not canonical", ref)
        self.assertIn("promotion-log.jsonl", ref)
        self.assertIn("draft-projection.json", ref)
        self.assertIn("draft_origin", ref)
        self.assertIn("DRAFT / NOT ACCEPTED", ref)
        self.assertIn("reconcile-draft-promotions", ref)
        self.assertIn("Projection convergence is fail-closed", ref)
        self.assertIn("`schema_version: 2`", normalized_ref)
        self.assertIn("require top-level `exploration_contract`", normalized_ref)
        self.assertIn("Partial or malformed explicit contracts fail schema validation", normalized_ref)
        self.assertIn("convergence, frontier queues, and review queues remain derived artifacts", normalized_ref)
        self.assertIn("DraftProjection uses `schema_version: 3`", normalized_ref)
        self.assertIn("`coverage_summary`, `coverage_matrix`, `gap_diagnostics`, `frontier_queue`, and `convergence`", normalized_ref)
        self.assertIn("`frontier_queue` is derived from blocking required P0/P1 coverage gaps", normalized_ref)
        self.assertIn("`observed_value` separately", normalized_ref)
        self.assertIn("`coverage_targets[].axis_id` values must be unique", normalized_ref)
        self.assertIn("cannot shadow a core diagnostic with a different meaning or weaker blocking policy", normalized_ref)
        self.assertIn("P2/P3 non-required rows do not", normalized_ref)
        self.assertIn("`review-queue.json` with `schema_version: 2`", normalized_ref)
        self.assertIn("`target_id` and `target_kind`", normalized_ref)
        self.assertIn("coverage blockers use `target_kind=coverage_gap`", normalized_ref)
        self.assertIn("If any coverage blocker exists, `bulk_promotable=true` draft decisions are excluded from bulk", normalized_ref)

    def test_related_references_document_pr4_boundaries(self) -> None:
        output_contract = (REPO_ROOT / "references" / "output-contract.md").read_text(encoding="utf-8")
        event_model = (REPO_ROOT / "references" / "event-and-projection-model.md").read_text(encoding="utf-8")
        document_compiler = (REPO_ROOT / "references" / "document-compiler.md").read_text(encoding="utf-8")
        draft_sidecar_commands = _section(
            output_contract,
            "Draft sidecar commands:",
            "Draft promotion commands:",
        )
        normalized_output_contract = _squash_ws(output_contract)

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
        self.assertIn("`schema_version: 2`", normalized_output_contract)
        self.assertIn("`exploration_contract`, and `draft_decisions`", normalized_output_contract)
        self.assertIn(
            "Derived coverage summaries, matrices, gap diagnostics, convergence, frontier queues, and review queues",
            normalized_output_contract,
        )
        self.assertIn("`coverage_summary`, and `canonical_events_created=false`", normalized_output_contract)
        self.assertIn(
            "`coverage_summary`, `coverage_matrix`, `gap_diagnostics`, `frontier_queue`, and `convergence`",
            normalized_output_contract,
        )
        self.assertIn("`projection_path`, `persisted`, `stale`", normalized_output_contract)
        self.assertIn("`persisted=false` and `projection_path` is the would-be sidecar path", normalized_output_contract)
        self.assertIn("P2/P3 non-required coverage gaps must not block convergence", normalized_output_contract)
        self.assertIn(
            "Coverage rows include `axis_id`, `axis_type`, `value`, `observed_value`, `priority`, `required`",
            normalized_output_contract,
        )
        self.assertIn("`value` is the requested target value", normalized_output_contract)
        self.assertIn("`observed_value` is the projection-derived value", normalized_output_contract)
        self.assertIn("must render `Coverage Summary`, `Coverage Matrix`, and `Frontier Queue`", normalized_output_contract)
        self.assertIn("Frontier items are derived from blocking required P0/P1 coverage gaps", normalized_output_contract)
        self.assertIn("derive the current draft projection in memory", normalized_output_contract)
        self.assertIn("`review-queue.json` uses `schema_version: 2`", normalized_output_contract)
        self.assertIn("general review targets with `target_id` and `target_kind`", normalized_output_contract)
        self.assertIn("coverage blockers, and blocked draft fields must not enter the bulk candidate list", normalized_output_contract)
        self.assertIn("`missing_required_layer`", normalized_output_contract)
        self.assertIn("`verification_without_observable_command`", normalized_output_contract)
        self.assertIn("must not render empty convergence from missing diagnostics", normalized_output_contract)

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
        self.assertIn("`schema_version: 2`", readme)
        self.assertIn("`exploration_contract`", readme)
        self.assertIn("Derived coverage matrices", readme)
        self.assertIn("`frontier_queue`; required P0/P1 missing or partial coverage blocks convergence", readme)

    def test_distribution_contains_decision_preflight_references(self) -> None:
        with BuiltArtifact() as artifact:
            names = artifact.names()

        self.assertIn("decide-me/references/decision-preflight.md", names)
        self.assertNotIn("decide-me/references/goal-autopilot-drafting.md", names)
        self.assertIn("decide-me/references/draft-decision-sets.md", names)


if __name__ == "__main__":
    unittest.main()
