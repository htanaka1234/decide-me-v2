from __future__ import annotations

import unittest

from decide_me.exporters.agents import build_agent_instructions_payload
from decide_me.projections import default_decision


class AgentInstructionFilterTests(unittest.TestCase):
    def test_filter_includes_only_final_agent_relevant_decisions(self) -> None:
        bundle = _bundle(
            [
                _accepted(
                    "D-typing",
                    "Python typing policy",
                    "technical",
                    "Require Python type hints for new runtime code.",
                ),
                _resolved(
                    "D-tests",
                    "Validation test policy",
                    "ops",
                    "Run `validate-state --full` before exporting plans.",
                ),
                _accepted(
                    "D-release",
                    "Release shape",
                    "product",
                    "Ship the planner-only release first.",
                ),
                _accepted(
                    "D-product-review",
                    "Codex review checks",
                    "product",
                    "Run `validate-state --full` before opening PRs.",
                ),
                _accepted(
                    "D-old",
                    "Old security policy",
                    "technical",
                    "Print secret values during debugging.",
                    status="invalidated",
                ),
                _accepted(
                    "D-deferred",
                    "Future dependency policy",
                    "technical",
                    "Require approval for new dependencies.",
                    status="deferred",
                ),
                _accepted(
                    "D-open",
                    "Open testing policy",
                    "technical",
                    "Run tests after changes.",
                    status="unresolved",
                ),
            ]
        )

        payload = build_agent_instructions_payload(bundle, [])

        self.assertEqual(
            ["D-tests", "D-typing", "D-product-review"],
            [rule["decision_id"] for rule in payload["rules"]],
        )
        self.assertEqual(
            {
                "D-tests": "Runtime Rules",
                "D-typing": "Development Rules",
                "D-product-review": "Review Checklist",
            },
            {rule["decision_id"]: rule["section"] for rule in payload["rules"]},
        )
        self.assertEqual(
            "Run `validate-state --full` before exporting plans.",
            payload["rules"][0]["text"],
        )

    def test_category_assignment_is_stable(self) -> None:
        bundle = _bundle(
            [
                _accepted(
                    "D-security",
                    "Secret handling",
                    "ops",
                    "Never print secrets or credential values.",
                ),
                _accepted(
                    "D-safety",
                    "Destructive operation policy",
                    "ops",
                    "Confirm before deleting or overwriting files.",
                ),
                _accepted(
                    "D-deps",
                    "Dependency policy",
                    "technical",
                    "Require approval before adding new dependencies.",
                ),
            ]
        )

        payload = build_agent_instructions_payload(bundle, [])

        self.assertEqual(
            {
                "D-deps": "Dependency Rules",
                "D-safety": "Safety Rules",
                "D-security": "Security Rules",
            },
            {rule["decision_id"]: rule["section"] for rule in payload["rules"]},
        )


def _bundle(decisions: list[dict]) -> dict:
    return {
        "project_state": {
            "state": {
                "updated_at": "2026-04-26T00:00:00Z",
                "project_head": "H-test",
            },
            "decisions": decisions,
        }
    }


def _accepted(
    decision_id: str,
    title: str,
    domain: str,
    summary: str,
    *,
    status: str = "accepted",
) -> dict:
    decision = default_decision(decision_id, title)
    decision["domain"] = domain
    decision["status"] = status
    decision["accepted_answer"] = {
        "summary": summary,
        "accepted_at": "2026-04-26T00:00:00Z",
        "accepted_via": "explicit",
        "proposal_id": "P-test",
    }
    return decision


def _resolved(decision_id: str, title: str, domain: str, summary: str) -> dict:
    decision = default_decision(decision_id, title)
    decision["domain"] = domain
    decision["status"] = "resolved-by-evidence"
    decision["accepted_answer"] = {
        "summary": summary,
        "accepted_at": "2026-04-26T00:00:00Z",
        "accepted_via": "evidence",
        "proposal_id": None,
    }
    decision["resolved_by_evidence"] = {
        "source": "docs",
        "summary": summary,
        "resolved_at": "2026-04-26T00:00:00Z",
        "evidence_refs": ["docs/policy.md"],
    }
    return decision
