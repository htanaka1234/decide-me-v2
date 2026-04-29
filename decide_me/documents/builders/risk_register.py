from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block
from decide_me.documents.builders.common import link_ids_touching, related_object_ids


def build_risk_register_document(context: DocumentContext) -> dict[str, Any]:
    items = context.risk_register.get("items", [])
    object_ids = [item["object_id"] for item in items]
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
            source_object_ids=object_ids,
            source_link_ids=link_ids_touching(context, object_ids),
        ),
        section(
            "risks",
            "Risks",
            20,
            [_risk_table(context, items)],
            source_object_ids=object_ids,
            source_link_ids=link_ids_touching(context, object_ids),
        ),
    ]
    return build_document(
        context,
        document_type="risk-register",
        title="Risk Register",
        sections=sections,
        diagnostic_types=["risk_register", "safety_gates"],
    )


def _risk_table(context: DocumentContext, items: list[dict[str, Any]]) -> dict[str, Any]:
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
        [
            [
                item.get("object_id"),
                item.get("statement") or item.get("title"),
                item.get("severity"),
                item.get("likelihood"),
                item.get("risk_tier"),
                item.get("reversibility"),
                item.get("approval_threshold"),
                ", ".join(
                    [
                        *item.get("mitigation_object_ids", []),
                        *item.get("mitigated_by_object_ids", []),
                    ]
                ),
                ", ".join(related_object_ids(context, item["object_id"], types={"decision", "action"})),
                _gate_status_for_related_objects(context, item["object_id"]),
            ]
            for item in items
        ],
    )


def _gate_status_for_related_objects(context: DocumentContext, risk_id: str) -> str:
    related = set(related_object_ids(context, risk_id, types={"decision", "action"}))
    statuses = []
    for result in context.safety_gates.get("results", []):
        if result.get("object_id") in related:
            statuses.append(f"{result['object_id']}={result.get('gate_status')}")
    return ", ".join(statuses)
