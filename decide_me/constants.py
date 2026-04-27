from __future__ import annotations


ACCEPTED_VIA_VALUES = {"ok", "explicit", "evidence"}
DOMAIN_VALUES = {"product", "technical", "data", "ux", "ops", "legal", "other"}
EVIDENCE_SOURCES = {
    "codebase",
    "docs",
    "tests",
    "external",
    "existing-decisions",
    "close-summaries",
}

DISCOVERABLE_DECISION_FIELDS = {
    "id",
    "title",
    "kind",
    "domain",
    "priority",
    "frontier",
    "resolvable_by",
    "reversibility",
    "depends_on",
    "blocked_by",
    "question",
    "context",
    "notes",
    "bundle_id",
    "agent_relevant",
    "requirement_id",
}
DISCOVERABLE_DECISION_STATUSES = {"unresolved", "blocked"}
FORBIDDEN_DISCOVERED_DECISION_FIELDS = {
    "accepted_answer",
    "resolved_by_evidence",
    "invalidated_by",
    "recommendation",
    "evidence",
    "options",
    "revisit_triggers",
}
