from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block
from decide_me.documents.builders.common import (
    FINAL_DECISION_STATUSES,
    diagnostic_link_ids,
    diagnostic_object_ids,
    link_ids_touching,
    metadata_value,
    object_label,
    objects_by_id,
    objects_of_type,
    objects_of_types,
    safety_link_ids,
    safety_object_ids,
    source_traceability_section,
)


def build_decision_brief_document(context: DocumentContext) -> dict[str, Any]:
    sections = [
        _project_section(context),
        _purpose_section(context),
        _decisions_section(context),
        _evidence_assumptions_section(context),
        _risks_safety_section(context),
        _actions_verification_section(context),
        _revisit_section(context),
        source_traceability_section(context, 80),
    ]
    return build_document(
        context,
        document_type="decision-brief",
        title="Decision Brief",
        sections=sections,
        diagnostic_types=[
            "evidence_register",
            "assumption_register",
            "risk_register",
            "safety_gates",
            "stale_assumptions",
            "stale_evidence",
            "verification_gaps",
            "revisit_due",
        ],
    )


def _project_section(context: DocumentContext) -> dict[str, Any]:
    project = context.project_state.get("project", {})
    rows = [
        ["Name", project.get("name")],
        ["Objective", project.get("objective")],
        ["Current Milestone", project.get("current_milestone")],
        ["Project Head", context.project_head],
    ]
    return section("project", "Project", 10, [table_block(["Field", "Value"], rows)])


def _purpose_section(context: DocumentContext) -> dict[str, Any]:
    objects = objects_of_types(context, {"objective", "criterion", "constraint", "assumption"})
    rows = [
        [
            obj["id"],
            obj.get("type"),
            object_label(obj),
            obj.get("status"),
            metadata_value(obj, "statement") or obj.get("body"),
        ]
        for obj in objects
    ]
    object_ids = [obj["id"] for obj in objects]
    return section(
        "purpose-principles-constraints",
        "Purpose / Principles / Constraints",
        20,
        [table_block(["ID", "Type", "Title", "Status", "Statement"], rows)],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _decisions_section(context: DocumentContext) -> dict[str, Any]:
    decisions = objects_of_type(context, "decision")
    rows = [
        [
            obj["id"],
            object_label(obj),
            obj.get("status"),
            metadata_value(obj, "priority"),
            metadata_value(obj, "frontier"),
            _decision_summary(context, obj),
        ]
        for obj in decisions
    ]
    object_ids = [obj["id"] for obj in decisions]
    return section(
        "current-decisions",
        "Current Decisions",
        30,
        [table_block(["ID", "Title", "Status", "Priority", "Frontier", "Summary"], rows)],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _evidence_assumptions_section(context: DocumentContext) -> dict[str, Any]:
    evidence_rows = [
        [
            item["object_id"],
            item.get("source"),
            item.get("source_ref"),
            item.get("confidence"),
            item.get("freshness"),
            item.get("summary"),
        ]
        for item in context.evidence_register.get("items", [])
    ]
    assumption_rows = [
        [
            item["object_id"],
            item.get("statement"),
            item.get("confidence"),
            item.get("expires_at"),
            item.get("owner"),
        ]
        for item in context.assumption_register.get("items", [])
    ]
    stale_rows = [
        [
            item["object_id"],
            item.get("stale_reason") or ", ".join(item.get("stale_reasons", [])),
            item.get("expires_at") or item.get("valid_until"),
        ]
        for payload in (context.stale_assumptions, context.stale_evidence)
        for item in payload.get("items", [])
    ]
    object_ids = [
        *(item["object_id"] for item in context.evidence_register.get("items", [])),
        *(item["object_id"] for item in context.assumption_register.get("items", [])),
        *diagnostic_object_ids(context.stale_assumptions, "related_object_ids"),
        *diagnostic_object_ids(context.stale_evidence, "affected_object_ids", "affected_decision_ids"),
    ]
    return section(
        "evidence-and-assumptions",
        "Evidence and Assumptions",
        40,
        [
            table_block(["Evidence ID", "Source", "Ref", "Confidence", "Freshness", "Summary"], evidence_rows),
            table_block(["Assumption ID", "Statement", "Confidence", "Expires At", "Owner"], assumption_rows),
            table_block(["Input ID", "Reason", "Until"], stale_rows),
        ],
        source_object_ids=object_ids,
        source_link_ids=[
            *link_ids_touching(context, object_ids),
            *diagnostic_link_ids(context.stale_assumptions),
            *diagnostic_link_ids(context.stale_evidence),
        ],
    )


def _risks_safety_section(context: DocumentContext) -> dict[str, Any]:
    risk_rows = [
        [
            item["object_id"],
            item.get("statement"),
            item.get("risk_tier"),
            item.get("reversibility"),
            item.get("approval_threshold"),
            ", ".join(item.get("mitigated_by_object_ids", [])),
        ]
        for item in context.risk_register.get("items", [])
    ]
    gate_rows = [
        [
            result["object_id"],
            result.get("gate_status"),
            result.get("risk_tier"),
            result.get("reversibility"),
            result.get("approval_required"),
            ", ".join(result.get("blocking_reasons", [])),
        ]
        for result in context.safety_gates.get("results", [])
    ]
    object_ids = [
        *(item["object_id"] for item in context.risk_register.get("items", [])),
        *safety_object_ids(context.safety_gates),
    ]
    return section(
        "risks-and-safety",
        "Risks and Safety",
        50,
        [
            table_block(
                ["Risk ID", "Statement", "Risk Tier", "Reversibility", "Approval Threshold", "Mitigated By"],
                risk_rows,
            ),
            table_block(
                ["Object ID", "Gate Status", "Risk Tier", "Reversibility", "Approval Required", "Blocking Reasons"],
                gate_rows,
            ),
        ],
        source_object_ids=object_ids,
        source_link_ids=[*link_ids_touching(context, object_ids), *safety_link_ids(context.safety_gates)],
    )


def _actions_verification_section(context: DocumentContext) -> dict[str, Any]:
    actions = objects_of_type(context, "action")
    action_rows = [
        [
            action["id"],
            object_label(action),
            action.get("status"),
            metadata_value(action, "responsibility"),
            metadata_value(action, "implementation_ready"),
            metadata_value(action, "next_step") or action.get("body"),
        ]
        for action in actions
    ]
    gap_rows = [
        [
            item["object_id"],
            item.get("gap_severity"),
            item.get("gap_reason"),
        ]
        for item in context.verification_gaps.get("items", [])
    ]
    object_ids = [*(action["id"] for action in actions), *diagnostic_object_ids(context.verification_gaps)]
    return section(
        "actions-and-verification",
        "Actions and Verification",
        60,
        [
            table_block(["Action ID", "Title", "Status", "Responsibility", "Ready", "Next Step"], action_rows),
            table_block(["Action ID", "Gap Severity", "Gap Reason"], gap_rows),
        ],
        source_object_ids=object_ids,
        source_link_ids=[*link_ids_touching(context, object_ids), *diagnostic_link_ids(context.verification_gaps)],
    )


def _revisit_section(context: DocumentContext) -> dict[str, Any]:
    triggers = objects_of_type(context, "revisit_trigger")
    due_ids = {item["object_id"] for item in context.revisit_due.get("items", [])}
    rows = [
        [
            trigger["id"],
            object_label(trigger),
            metadata_value(trigger, "trigger_type"),
            metadata_value(trigger, "due_at"),
            "due" if trigger["id"] in due_ids else "future",
            metadata_value(trigger, "condition") or trigger.get("body"),
        ]
        for trigger in triggers
    ]
    object_ids = [*(trigger["id"] for trigger in triggers), *diagnostic_object_ids(context.revisit_due, "target_object_ids")]
    return section(
        "revisit-triggers",
        "Revisit Triggers",
        70,
        [table_block(["Trigger ID", "Title", "Type", "Due At", "Status", "Condition"], rows)],
        source_object_ids=object_ids,
        source_link_ids=[*link_ids_touching(context, object_ids), *diagnostic_link_ids(context.revisit_due)],
    )


def _decision_summary(context: DocumentContext, decision: dict[str, Any]) -> str | None:
    if decision.get("status") not in FINAL_DECISION_STATUSES:
        return decision.get("body")
    by_id = objects_by_id(context)
    for link in context.scoped_project_state.get("links", []):
        if link.get("source_object_id") == decision["id"] and link.get("relation") == "accepts":
            proposal = by_id.get(link.get("target_object_id"))
            if proposal:
                return object_label(proposal)
    return decision.get("body")
