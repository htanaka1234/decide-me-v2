from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block
from decide_me.documents.builders.common import Trace, objects_by_id, related_object_ids
from decide_me.taxonomy import stable_unique


def build_risk_register_document(context: DocumentContext) -> dict[str, Any]:
    items = context.risk_register.get("items", [])
    rows, trace = _risk_rows(context, items)
    sections = [
        section(
            "summary",
            "Summary",
            10,
            [
                list_block(
                    [
                        f"Risk count: {context.risk_register.get('summary', {}).get('item_count', 0)}",
                        f"By risk tier: {context.risk_register.get('summary', {}).get('by_risk_tier', {})}",
                        f"By approval threshold: {context.risk_register.get('summary', {}).get('by_approval_threshold', {})}",
                    ]
                )
            ],
            source_object_ids=trace.object_ids,
            source_link_ids=trace.link_ids,
        ),
        section(
            "risks",
            "Risks",
            20,
            [_risk_table(rows)],
            source_object_ids=trace.object_ids,
            source_link_ids=trace.link_ids,
        ),
    ]
    return build_document(
        context,
        document_type="risk-register",
        title="Risk Register",
        sections=sections,
        diagnostic_types=["risk_register", "safety_gates"],
    )


def _risk_rows(context: DocumentContext, items: list[dict[str, Any]]) -> tuple[list[list[Any]], Trace]:
    rows = []
    trace = Trace()
    for item in items:
        row, row_trace = _risk_row(context, item)
        rows.append(row)
        trace.merge(row_trace)
    return rows, trace


def _risk_table(rows: list[list[Any]]) -> dict[str, Any]:
    return table_block(
        [
            "Risk ID",
            "Statement",
            "Severity",
            "Likelihood",
            "Risk Tier",
            "Reversibility",
            "Approval Threshold",
            "Mitigations",
            "Related Decisions / Actions",
            "Gate Status",
        ],
        rows,
    )


def _risk_row(context: DocumentContext, item: dict[str, Any]) -> tuple[list[Any], Trace]:
    trace = Trace()
    risk_id = item["object_id"]
    trace.add_object(risk_id)
    by_id = objects_by_id(context)
    mitigation_ids = sorted(
        stable_unique(
            mitigation_id
            for mitigation_id in [
                *item.get("mitigation_object_ids", []),
                *item.get("mitigated_by_object_ids", []),
            ]
            if mitigation_id in by_id
        )
    )
    related_ids = related_object_ids(context, risk_id, types={"decision", "action"})
    gate_status, gate_trace = _gate_status_for_related_objects(context, risk_id)
    trace.add_objects([*mitigation_ids, *related_ids])
    trace.add_links(item.get("mitigation_link_ids", []))
    trace.add_links(item.get("related_link_ids", []))
    trace.add_links(_links_between(context, risk_id, [*mitigation_ids, *related_ids]))
    trace.merge(gate_trace)
    return [
        item.get("object_id"),
        item.get("statement") or item.get("title"),
        item.get("severity"),
        item.get("likelihood"),
        item.get("risk_tier"),
        item.get("reversibility"),
        item.get("approval_threshold"),
        ", ".join(mitigation_ids),
        ", ".join(related_ids),
        gate_status,
    ], trace


def _links_between(context: DocumentContext, object_id: str, related_ids: list[str]) -> list[str]:
    related = set(related_ids)
    return sorted(
        stable_unique(
            link["id"]
            for link in context.scoped_project_state.get("links", [])
            if (
                link.get("source_object_id") == object_id
                and link.get("target_object_id") in related
            )
            or (
                link.get("target_object_id") == object_id
                and link.get("source_object_id") in related
            )
        )
    )


def _gate_status_for_related_objects(context: DocumentContext, risk_id: str) -> tuple[str, Trace]:
    trace = Trace()
    related = set(related_object_ids(context, risk_id, types={"decision", "action"}))
    statuses = []
    for result in context.safety_gates.get("results", []):
        if result.get("object_id") in related:
            statuses.append(f"{result['object_id']}={result.get('gate_status')}")
            trace.add_object(result.get("object_id"))
            trace.add_objects([item.get("object_id") for item in result.get("evidence", [])])
            trace.add_objects([item.get("object_id") for item in result.get("assumptions", [])])
            trace.add_objects([item.get("object_id") for item in result.get("risks", [])])
            trace.add_links(result.get("source_link_ids", []))
    return ", ".join(statuses), trace
