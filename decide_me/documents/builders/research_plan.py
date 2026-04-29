from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, section, table_block, text_block
from decide_me.documents.builders.common import (
    diagnostic_link_ids,
    diagnostic_object_ids,
    link_ids_touching,
    metadata_value,
    object_label,
    objects_of_type,
    objects_of_types,
    source_traceability_section,
)


def build_research_plan_document(context: DocumentContext) -> dict[str, Any]:
    decisions = _research_first(objects_of_type(context, "decision"))
    sections = [
        _objective_section(context),
        _decision_targets_section(context, decisions),
        _object_table_section(context, "constraints", "Constraints", 30, {"constraint"}),
        _object_table_section(context, "assumptions", "Assumptions", 40, {"assumption"}),
        _evidence_section(context),
        _object_table_section(context, "planned-work-units", "Planned Work Units", 60, {"action"}),
        _verification_section(context),
        _object_table_section(context, "risks-and-mitigations", "Risks and Mitigations", 80, {"risk"}),
        _object_table_section(context, "revisit-conditions", "Revisit Conditions", 90, {"revisit_trigger"}),
        source_traceability_section(context, 100),
    ]
    return build_document(
        context,
        document_type="research-plan",
        title="Research Plan",
        sections=sections,
        diagnostic_types=["evidence_register", "assumption_register", "risk_register", "verification_gaps", "revisit_due"],
    )


def _objective_section(context: DocumentContext) -> dict[str, Any]:
    objectives = objects_of_type(context, "objective")
    object_ids = [obj["id"] for obj in objectives]
    project = context.project_state.get("project", {})
    return section(
        "objective",
        "Objective",
        10,
        [
            text_block(project.get("objective")),
            table_block(
                ["Objective ID", "Title", "Status", "Body"],
                [[obj["id"], object_label(obj), obj.get("status"), obj.get("body")] for obj in objectives],
            ),
        ],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _decision_targets_section(
    context: DocumentContext,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    object_ids = [obj["id"] for obj in decisions]
    return section(
        "research-question-decision-targets",
        "Research Question / Decision Targets",
        20,
        [
            table_block(
                ["Decision ID", "Title", "Status", "Priority", "Question"],
                [
                    [
                        obj["id"],
                        object_label(obj),
                        obj.get("status"),
                        metadata_value(obj, "priority"),
                        metadata_value(obj, "question") or obj.get("body"),
                    ]
                    for obj in decisions
                ],
            )
        ],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _object_table_section(
    context: DocumentContext,
    section_id: str,
    title: str,
    order: int,
    object_types: set[str],
) -> dict[str, Any]:
    objects = objects_of_types(context, object_types)
    object_ids = [obj["id"] for obj in objects]
    return section(
        section_id,
        title,
        order,
        [
            table_block(
                ["ID", "Type", "Title", "Status", "Statement"],
                [
                    [
                        obj["id"],
                        obj.get("type"),
                        object_label(obj),
                        obj.get("status"),
                        metadata_value(obj, "statement") or metadata_value(obj, "condition") or obj.get("body"),
                    ]
                    for obj in objects
                ],
            )
        ],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _evidence_section(context: DocumentContext) -> dict[str, Any]:
    items = context.evidence_register.get("items", [])
    object_ids = [item["object_id"] for item in items]
    return section(
        "evidence-base",
        "Evidence Base",
        50,
        [
            table_block(
                ["Evidence ID", "Source", "Ref", "Confidence", "Freshness", "Summary"],
                [
                    [
                        item.get("object_id"),
                        item.get("source"),
                        item.get("source_ref"),
                        item.get("confidence"),
                        item.get("freshness"),
                        item.get("summary"),
                    ]
                    for item in items
                ],
            )
        ],
        source_object_ids=object_ids,
        source_link_ids=link_ids_touching(context, object_ids),
    )


def _verification_section(context: DocumentContext) -> dict[str, Any]:
    verifications = objects_of_type(context, "verification")
    object_ids = [obj["id"] for obj in verifications]
    gap_object_ids = diagnostic_object_ids(context.verification_gaps)
    return section(
        "analysis-verification-plan",
        "Analysis / Verification Plan",
        70,
        [
            table_block(
                ["Verification ID", "Method", "Expected Result", "Result"],
                [
                    [
                        obj["id"],
                        metadata_value(obj, "method"),
                        metadata_value(obj, "expected_result"),
                        metadata_value(obj, "result"),
                    ]
                    for obj in verifications
                ],
            ),
            table_block(
                ["Action ID", "Gap Severity", "Gap Reason"],
                [
                    [item.get("object_id"), item.get("gap_severity"), item.get("gap_reason")]
                    for item in context.verification_gaps.get("items", [])
                ],
            ),
        ],
        source_object_ids=[*object_ids, *gap_object_ids],
        source_link_ids=[*link_ids_touching(context, object_ids), *diagnostic_link_ids(context.verification_gaps)],
    )


def _research_first(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = [obj for obj in decisions if obj.get("metadata", {}).get("domain") == "research"]
    return research or decisions
