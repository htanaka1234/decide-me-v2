from __future__ import annotations

import unittest

from decide_me.exporters.agents import build_agent_instructions_payload
from decide_me.requirement_ids import require_requirement_id
from tests.helpers.typed_metadata import evidence_metadata, metadata_for_object_type


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
                    "D-auth-implementation",
                    "Auth implementation",
                    "technical",
                    "Use the existing auth implementation.",
                ),
                _accepted(
                    "D-audit-db",
                    "Audit log sink",
                    "ops",
                    "Place audit logs in the product database.",
                ),
                _accepted(
                    "D-service-architecture",
                    "Service architecture",
                    "technical",
                    "Use the service-layer architecture.",
                ),
                _accepted(
                    "D-postgres",
                    "Database engine",
                    "technical",
                    "Database must be PostgreSQL.",
                ),
                _accepted(
                    "D-local-export",
                    "Local export",
                    "product",
                    "The MVP must support local export.",
                ),
                _accepted(
                    "D-artifact-storage",
                    "Production artifact storage",
                    "technical",
                    "Use S3; do not use local disk for production artifacts.",
                ),
                _accepted(
                    "D-test-db",
                    "Test database",
                    "technical",
                    "Test database must be PostgreSQL.",
                ),
                _accepted(
                    "D-migration-fixture",
                    "Migration test fixture",
                    "technical",
                    "Migration tests must use fixture X.",
                ),
                _accepted(
                    "D-delete-policy",
                    "Delete policy",
                    "technical",
                    "Delete policy must be soft-delete.",
                ),
                _accepted(
                    "D-email-confirmation",
                    "Signup confirmation",
                    "product",
                    "Use email confirmation for signup.",
                ),
                _accepted(
                    "D-postgres-source",
                    "Canonical database",
                    "technical",
                    "PostgreSQL is the source of truth.",
                ),
                _accepted(
                    "D-audit-event-log",
                    "Audit storage",
                    "technical",
                    "Use an event log table for audit history.",
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

    def test_agent_relevant_flag_overrides_keyword_filter(self) -> None:
        inherited_keyword = _accepted(
            "D-inherited-keyword",
            "Python typing policy",
            "technical",
            "Require Python type hints for new runtime code.",
        )
        del inherited_keyword["agent_relevant"]
        bundle = _bundle(
            [
                _accepted(
                    "D-forced",
                    "Release shape",
                    "product",
                    "Ship the planner-only release first.",
                    agent_relevant=True,
                ),
                _accepted(
                    "D-excluded",
                    "Validation test policy",
                    "ops",
                    "Run tests after changes.",
                    agent_relevant=False,
                ),
                _accepted(
                    "D-null-release",
                    "Release shape",
                    "product",
                    "Ship the planner-only release first.",
                    agent_relevant=None,
                ),
                inherited_keyword,
                _accepted(
                    "D-open-forced",
                    "Open release rule",
                    "product",
                    "Ship the planner-only release first.",
                    status="unresolved",
                    agent_relevant=True,
                ),
            ]
        )

        payload = build_agent_instructions_payload(bundle, [])

        self.assertEqual(
            ["D-forced", "D-inherited-keyword"],
            [rule["decision_id"] for rule in payload["rules"]],
        )
        self.assertEqual(
            {
                "D-forced": "Development Rules",
                "D-inherited-keyword": "Development Rules",
            },
            {rule["decision_id"]: rule["section"] for rule in payload["rules"]},
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
    objects: list[dict] = []
    links: list[dict] = []
    for decision in decisions:
        objects.append(_decision_object(decision))
        if decision["status"] == "accepted":
            option_id = f"O-option-{decision['id']}"
            proposal_id = f"P-{decision['id']}"
            summary = decision["accepted_answer"]["summary"]
            objects.append(_object(option_id, "option", summary, status="active"))
            objects.append(_object(proposal_id, "proposal", summary, status="accepted", metadata={"accepted_via": "explicit"}))
            links.extend(
                [
                    _link(f"L-{proposal_id}-addresses-{decision['id']}", proposal_id, "addresses", decision["id"]),
                    _link(f"L-{proposal_id}-recommends-{option_id}", proposal_id, "recommends", option_id),
                    _link(f"L-{decision['id']}-accepts-{proposal_id}", decision["id"], "accepts", proposal_id),
                ]
            )
        if decision["status"] == "resolved-by-evidence":
            evidence_id = f"O-evidence-{decision['id']}"
            summary = decision["resolved_by_evidence"]["summary"]
            objects.append(
                _object(
                    evidence_id,
                    "evidence",
                    decision["resolved_by_evidence"]["evidence"][0],
                    body=summary,
                    metadata=evidence_metadata(
                        source_ref=decision["resolved_by_evidence"]["evidence"][0],
                        summary=summary,
                    ),
                )
            )
            links.append(_link(f"L-{evidence_id}-supports-{decision['id']}", evidence_id, "supports", decision["id"], summary))
    return {
        "project_state": {
            "state": {
                "updated_at": "2026-04-26T00:00:00Z",
                "project_head": "H-test",
            },
            "objects": objects,
            "links": links,
        }
    }


def _decision_object(decision: dict) -> dict:
    metadata = {
        key: value
        for key, value in decision.items()
        if key
        not in {
            "id",
            "title",
            "status",
            "accepted_answer",
            "resolved_by_evidence",
            "evidence",
            "options",
            "recommendation",
            "revisit_triggers",
        }
    }
    return {
        "id": decision["id"],
        "type": "decision",
        "title": decision["title"],
        "body": decision.get("context") or decision["title"],
        "status": decision["status"],
        "created_at": "2026-04-26T00:00:00Z",
        "updated_at": "2026-04-26T00:00:00Z",
        "source_event_ids": [f"E-{decision['id']}"],
        "metadata": metadata,
    }


def _object(
    object_id: str,
    object_type: str,
    title: str,
    *,
    status: str = "active",
    body: str | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": title,
        "body": body,
        "status": status,
        "created_at": "2026-04-26T00:00:00Z",
        "updated_at": "2026-04-26T00:00:00Z",
        "source_event_ids": [f"E-{object_id}"],
        "metadata": metadata if metadata is not None else metadata_for_object_type(object_type),
    }


def _link(
    link_id: str,
    source_object_id: str,
    relation: str,
    target_object_id: str,
    rationale: str | None = None,
) -> dict:
    return {
        "id": link_id,
        "source_object_id": source_object_id,
        "relation": relation,
        "target_object_id": target_object_id,
        "rationale": rationale,
        "created_at": "2026-04-26T00:00:00Z",
        "source_event_ids": [f"E-{link_id}"],
    }


def _accepted(
    decision_id: str,
    title: str,
    domain: str,
    summary: str,
    *,
    status: str = "accepted",
    agent_relevant: bool | None | object = Ellipsis,
) -> dict:
    decision = default_decision(decision_id, _requirement_id(decision_id), title)
    decision["domain"] = domain
    decision["status"] = status
    if agent_relevant is not Ellipsis:
        decision["agent_relevant"] = agent_relevant
    decision["accepted_answer"] = {
        "summary": summary,
        "accepted_at": "2026-04-26T00:00:00Z",
        "accepted_via": "explicit",
        "proposal_id": "P-test",
    }
    return decision


def default_decision(decision_id: str, requirement_id: str, title: str | None = None) -> dict:
    return {
        "id": decision_id,
        "requirement_id": require_requirement_id(requirement_id),
        "title": title,
        "kind": "choice",
        "domain": "other",
        "priority": "P1",
        "frontier": "later",
        "status": "unresolved",
        "resolvable_by": "human",
        "reversibility": "reversible",
        "depends_on": [],
        "blocked_by": [],
        "question": None,
        "context": None,
        "options": [],
        "recommendation": {
            "proposal_id": None,
            "version": 0,
            "summary": None,
            "rationale_short": None,
            "confidence": "medium",
            "proposed_at": None,
            "based_on_project_head": None,
        },
        "accepted_answer": {
            "summary": None,
            "accepted_at": None,
            "accepted_via": None,
            "proposal_id": None,
        },
        "resolved_by_evidence": {
            "source": None,
            "summary": None,
            "resolved_at": None,
            "evidence": [],
        },
        "evidence": [],
        "revisit_triggers": [],
        "notes": [],
        "bundle_id": None,
        "agent_relevant": None,
        "invalidated_by": None,
    }


def _resolved(decision_id: str, title: str, domain: str, summary: str) -> dict:
    decision = default_decision(decision_id, _requirement_id(decision_id), title)
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
        "evidence": ["docs/policy.md"],
    }
    return decision


def _requirement_id(decision_id: str) -> str:
    return f"R-{sum(ord(char) for char in decision_id):03d}"
