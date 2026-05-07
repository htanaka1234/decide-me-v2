from __future__ import annotations


ACCEPTED_VIA_VALUES = {"ok", "explicit", "evidence"}
DOMAIN_VALUES = {"product", "technical", "data", "ux", "ops", "legal", "other"}
OBJECT_TYPES = {
    "objective",
    "constraint",
    "criterion",
    "option",
    "proposal",
    "decision",
    "assumption",
    "evidence",
    "risk",
    "action",
    "verification",
    "revisit_trigger",
    "artifact",
}
ACTION_TYPE_VALUES = {
    "research",
    "analysis",
    "writing",
    "communication",
    "execution",
    "review",
    "verification",
    "monitoring",
    "decision",
}
LINK_RELATIONS = {
    "depends_on",
    "supports",
    "challenges",
    "recommends",
    "accepts",
    "addresses",
    "verifies",
    "revisits",
    "supersedes",
    "blocked_by",
    "constrains",
    "enables",
    "requires",
    "invalidates",
    "mitigates",
    "derived_from",
}
DECISION_STACK_LAYER_ORDER = (
    "purpose",
    "principle",
    "constraint",
    "strategy",
    "design",
    "execution",
    "verification",
    "review",
)
DECISION_STACK_LAYERS = set(DECISION_STACK_LAYER_ORDER)
INFLUENCE_REVERSED_RELATIONS = {
    "depends_on",
    "blocked_by",
    "requires",
    "addresses",
    "accepts",
    "derived_from",
    "verifies",
}
INFLUENCE_FORWARD_RELATIONS = {
    "constrains",
    "enables",
    "invalidates",
    "mitigates",
    "supports",
    "challenges",
    "revisits",
    "supersedes",
    "recommends",
}
GRAPH_TRAVERSAL_DIRECTIONS = {"raw", "influence"}
DEFAULT_LAYER_BY_OBJECT_TYPE = {
    "objective": "purpose",
    "assumption": "constraint",
    "constraint": "constraint",
    "risk": "constraint",
    "proposal": "strategy",
    "decision": "strategy",
    "option": "strategy",
    "action": "execution",
    "artifact": "design",
    "criterion": "principle",
    "evidence": "verification",
    "verification": "verification",
    "revisit_trigger": "review",
}
EVIDENCE_SOURCES = {
    "codebase",
    "docs",
    "tests",
    "external",
    "existing-decisions",
    "close-summaries",
    "source-store",
}
METADATA_CONFIDENCE_VALUES = {"low", "medium", "high"}
EVIDENCE_FRESHNESS_VALUES = {"current", "stale", "unknown"}
RISK_SEVERITY_VALUES = {"low", "medium", "high", "critical"}
RISK_LIKELIHOOD_VALUES = {"low", "medium", "high"}
RISK_TIER_VALUES = {"low", "medium", "high", "critical"}
RISK_REVERSIBILITY_VALUES = {"reversible", "partially_reversible", "irreversible"}
APPROVAL_LEVEL_VALUES = {"explicit_acceptance", "human_review", "external_review"}
APPROVAL_THRESHOLD_VALUES = {"none", *APPROVAL_LEVEL_VALUES}
VERIFICATION_METHOD_VALUES = {"inspection", "test", "review", "analysis", "monitoring"}
VERIFICATION_RESULT_VALUES = {"pass", "fail", "inconclusive", "pending"}
REVISIT_TRIGGER_TYPE_VALUES = {"time", "evidence", "outcome", "dependency"}

DISCOVERABLE_DECISION_FIELDS = {
    "id",
    "title",
    "kind",
    "domain",
    "priority",
    "frontier",
    "resolvable_by",
    "reversibility",
    "domain_pack_id",
    "domain_pack_version",
    "domain_pack_digest",
    "domain_decision_type",
    "domain_criteria",
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
