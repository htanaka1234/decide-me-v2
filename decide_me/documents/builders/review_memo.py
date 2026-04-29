from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block
from decide_me.documents.builders.common import (
    diagnostic_link_ids,
    diagnostic_object_ids,
    safety_link_ids,
    safety_object_ids,
)


def build_review_memo_document(context: DocumentContext) -> dict[str, Any]:
    sections = [
        _summary_section(context),
        _required_decisions_section(context),
        _stale_inputs_section(context),
        _verification_gaps_section(context),
        _revisit_due_section(context),
        _recommended_actions_section(context),
    ]
    return build_document(
        context,
        document_type="review-memo",
        title="Review Memo",
        sections=sections,
        diagnostic_types=[
            "safety_gates",
            "stale_assumptions",
            "stale_evidence",
            "verification_gaps",
            "revisit_due",
        ],
    )


def _summary_section(context: DocumentContext) -> dict[str, Any]:
    safety_summary = context.safety_gates.get("summary", {})
    rows = [
        ["Blocking gates", safety_summary.get("blocking_count", 0)],
        ["Approval required", safety_summary.get("approval_required_count", 0)],
        ["Stale evidence", context.stale_evidence.get("summary", {}).get("item_count", 0)],
        ["Expired assumptions", context.stale_assumptions.get("summary", {}).get("item_count", 0)],
        ["Verification gaps", context.verification_gaps.get("summary", {}).get("item_count", 0)],
        ["Due revisits", context.revisit_due.get("summary", {}).get("item_count", 0)],
    ]
    return section(
        "review-summary",
        "Review Summary",
        10,
        [table_block(["Metric", "Count"], rows)],
        source_object_ids=[
            *safety_object_ids(context.safety_gates),
            *diagnostic_object_ids(context.stale_evidence),
            *diagnostic_object_ids(context.stale_assumptions),
            *diagnostic_object_ids(context.verification_gaps),
            *diagnostic_object_ids(context.revisit_due),
        ],
        source_link_ids=[
            *safety_link_ids(context.safety_gates),
            *diagnostic_link_ids(context.stale_evidence),
            *diagnostic_link_ids(context.stale_assumptions),
            *diagnostic_link_ids(context.verification_gaps),
            *diagnostic_link_ids(context.revisit_due),
        ],
    )


def _required_decisions_section(context: DocumentContext) -> dict[str, Any]:
    rows = [
        [
            result.get("object_id"),
            result.get("title"),
            result.get("gate_status"),
            result.get("approval_required"),
            ", ".join(result.get("blocking_reasons", [])),
            ", ".join(result.get("approval_reasons", [])),
        ]
        for result in context.safety_gates.get("results", [])
        if result.get("gate_status") == "blocked" or result.get("approval_required")
    ]
    object_ids = safety_object_ids(context.safety_gates)
    return section(
        "required-decisions",
        "Required Decisions",
        20,
        [
            table_block(
                ["Object ID", "Title", "Gate Status", "Approval Required", "Blocking Reasons", "Approval Reasons"],
                rows,
            )
        ],
        source_object_ids=object_ids,
        source_link_ids=safety_link_ids(context.safety_gates),
    )


def _stale_inputs_section(context: DocumentContext) -> dict[str, Any]:
    rows = [
        [
            "assumption",
            item.get("object_id"),
            item.get("stale_reason"),
            item.get("expires_at"),
            ", ".join(item.get("related_object_ids", [])),
        ]
        for item in context.stale_assumptions.get("items", [])
    ] + [
        [
            "evidence",
            item.get("object_id"),
            ", ".join(item.get("stale_reasons", [])),
            item.get("valid_until"),
            ", ".join(item.get("affected_decision_ids", [])),
        ]
        for item in context.stale_evidence.get("items", [])
    ]
    return section(
        "stale-inputs",
        "Stale Inputs",
        30,
        [table_block(["Kind", "Object ID", "Reason", "Timestamp", "Affected Objects"], rows)],
        source_object_ids=[
            *diagnostic_object_ids(context.stale_assumptions, "related_object_ids"),
            *diagnostic_object_ids(context.stale_evidence, "affected_object_ids", "affected_decision_ids"),
        ],
        source_link_ids=[
            *diagnostic_link_ids(context.stale_assumptions),
            *diagnostic_link_ids(context.stale_evidence),
        ],
    )


def _verification_gaps_section(context: DocumentContext) -> dict[str, Any]:
    rows = [
        [
            item.get("object_id"),
            item.get("title"),
            item.get("gap_severity"),
            item.get("gap_reason"),
        ]
        for item in context.verification_gaps.get("items", [])
    ]
    return section(
        "verification-gaps",
        "Verification Gaps",
        40,
        [table_block(["Action ID", "Title", "Gap Severity", "Gap Reason"], rows)],
        source_object_ids=diagnostic_object_ids(context.verification_gaps),
        source_link_ids=diagnostic_link_ids(context.verification_gaps),
    )


def _revisit_due_section(context: DocumentContext) -> dict[str, Any]:
    rows = [
        [
            item.get("object_id"),
            item.get("trigger_type"),
            item.get("due_at"),
            ", ".join(item.get("target_object_ids", [])),
            item.get("condition"),
        ]
        for item in context.revisit_due.get("items", [])
    ]
    return section(
        "revisit-due",
        "Revisit Due",
        50,
        [table_block(["Trigger ID", "Type", "Due At", "Targets", "Condition"], rows)],
        source_object_ids=diagnostic_object_ids(context.revisit_due, "target_object_ids"),
        source_link_ids=diagnostic_link_ids(context.revisit_due),
    )


def _recommended_actions_section(context: DocumentContext) -> dict[str, Any]:
    actions = []
    if context.safety_gates.get("summary", {}).get("blocking_count", 0):
        actions.append("Review blocked safety gates before implementation.")
    if context.safety_gates.get("summary", {}).get("approval_required_count", 0):
        actions.append("Record or refresh required safety approvals.")
    if context.stale_evidence.get("items"):
        actions.append("Collect current evidence for stale evidence objects.")
    if context.stale_assumptions.get("items"):
        actions.append("Refresh or invalidate expired assumptions.")
    if context.verification_gaps.get("items"):
        actions.append("Define verification evidence for actions with gaps.")
    if context.revisit_due.get("items"):
        actions.append("Revisit due trigger targets and update affected objects.")
    return section(
        "recommended-next-actions",
        "Recommended Next Actions",
        60,
        [list_block(actions)],
    )
