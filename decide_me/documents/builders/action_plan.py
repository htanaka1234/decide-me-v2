from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block
from decide_me.documents.builders.common import Trace
from decide_me.taxonomy import stable_unique


def build_action_plan_document(context: DocumentContext) -> dict[str, Any]:
    if context.action_plan is None:
        raise ValueError("action-plan document export requires action plan context")
    action_plan = context.action_plan
    sections = [
        _summary_section(action_plan),
        _implementation_ready_section(context, action_plan),
        _actions_section(context, action_plan),
        _blockers_section(context, action_plan),
        _risks_section(context, action_plan),
        _evidence_section(action_plan),
        _source_section(context, action_plan),
    ]
    return build_document(
        context,
        document_type="action-plan",
        title="Action Plan",
        sections=sections,
        diagnostic_types=["action_plan"],
        metadata={"readiness": action_plan.get("readiness")},
    )


def _summary_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    return section(
        "summary",
        "Summary",
        10,
        [
            list_block(
                [
                    f"Readiness: {action_plan.get('readiness') or 'unknown'}",
                    f"Action count: {len(action_plan.get('actions', []))}",
                    f"Implementation-ready count: {len(action_plan.get('implementation_ready_actions', []))}",
                ]
            ),
            list_block(action_plan.get("goals", [])),
        ],
        source_object_ids=action_plan.get("source_object_ids", []),
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _implementation_ready_section(context: DocumentContext, action_plan: dict[str, Any]) -> dict[str, Any]:
    actions = action_plan.get("implementation_ready_actions", [])
    rows, trace = _action_rows_and_trace(context, actions)
    return section(
        "implementation-ready-actions",
        "Implementation-Ready Actions",
        20,
        [_action_table(rows)],
        source_object_ids=trace.object_ids,
        source_link_ids=trace.link_ids,
    )


def _actions_section(context: DocumentContext, action_plan: dict[str, Any]) -> dict[str, Any]:
    actions = action_plan.get("actions", [])
    rows, trace = _action_rows_and_trace(context, actions)
    return section(
        "actions",
        "Actions",
        30,
        [_action_table(rows)],
        source_object_ids=trace.object_ids,
        source_link_ids=trace.link_ids,
    )


def _blockers_section(context: DocumentContext, action_plan: dict[str, Any]) -> dict[str, Any]:
    blockers = action_plan.get("blockers", [])
    rows, trace = _decision_like_rows_and_trace(context, blockers)
    return section(
        "blockers",
        "Blockers",
        40,
        [table_block(["ID", "Title", "Status", "Priority", "Frontier", "Evidence"], rows)],
        source_object_ids=trace.object_ids,
        source_link_ids=trace.link_ids,
    )


def _risks_section(context: DocumentContext, action_plan: dict[str, Any]) -> dict[str, Any]:
    risks = action_plan.get("risks", [])
    rows, trace = _risk_rows_and_trace(context, risks)
    return section(
        "risks",
        "Risks",
        50,
        [table_block(["ID", "Title", "Status", "Priority", "Evidence"], rows)],
        source_object_ids=trace.object_ids,
        source_link_ids=trace.link_ids,
    )


def _evidence_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    evidence = action_plan.get("evidence", [])
    return section(
        "evidence",
        "Evidence",
        60,
        [
            table_block(
                ["ID", "Source", "Ref", "Status", "Summary"],
                [
                    [item.get("id"), item.get("source"), item.get("ref"), item.get("status"), item.get("summary")]
                    for item in evidence
                ],
            )
        ],
        source_object_ids=[item["id"] for item in evidence if item.get("id")],
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _source_section(context: DocumentContext, action_plan: dict[str, Any]) -> dict[str, Any]:
    return section(
        "source-traceability",
        "Source Traceability",
        70,
        [
            list_block(
                [
                    f"Sessions: {', '.join(context.source_session_ids) if context.source_session_ids else 'none recorded'}",
                    f"Objects: {', '.join(action_plan.get('source_object_ids', [])) or 'none recorded'}",
                    f"Links: {', '.join(action_plan.get('source_link_ids', [])) or 'none recorded'}",
                ]
            )
        ],
        source_object_ids=action_plan.get("source_object_ids", []),
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _action_table(rows: list[list[Any]]) -> dict[str, Any]:
    return table_block(
        [
            "ID",
            "Name",
            "Decision ID",
            "Status",
            "Priority",
            "Ready",
            "Gate",
            "Next Step",
        ],
        rows,
    )


def _action_rows_and_trace(
    context: DocumentContext,
    actions: list[dict[str, Any]],
) -> tuple[list[list[Any]], Trace]:
    rows = []
    trace = Trace()
    for item in actions:
        action_id = item.get("id")
        decision_id = item.get("decision_id")
        row_object_ids = stable_unique([value for value in (action_id, decision_id) if value])
        row_trace = Trace()
        row_trace.add_objects(row_object_ids)
        row_trace.add_links(_links_between(context, row_object_ids))
        row_trace.merge(_safety_trace(context, [action_id] if action_id else []))
        rows.append(
            [
                action_id,
                item.get("name"),
                decision_id,
                item.get("status"),
                item.get("priority"),
                item.get("implementation_ready"),
                (item.get("safety_gate") or {}).get("gate_status"),
                item.get("next_step") or item.get("summary"),
            ]
        )
        trace.merge(row_trace)
    return rows, trace


def _decision_like_rows_and_trace(
    context: DocumentContext,
    items: list[dict[str, Any]],
) -> tuple[list[list[Any]], Trace]:
    rows = []
    trace = Trace()
    for item in items:
        item_id = item.get("id")
        evidence_ids = item.get("evidence_ids", [])
        row_object_ids = stable_unique([value for value in [item_id, *evidence_ids] if value])
        trace.add_objects(row_object_ids)
        trace.add_links(_links_between(context, row_object_ids))
        rows.append(
            [
                item_id,
                item.get("title"),
                item.get("status"),
                item.get("priority"),
                item.get("frontier"),
                ", ".join(evidence_ids),
            ]
        )
    return rows, trace


def _risk_rows_and_trace(
    context: DocumentContext,
    items: list[dict[str, Any]],
) -> tuple[list[list[Any]], Trace]:
    rows = []
    trace = Trace()
    for item in items:
        item_id = item.get("id")
        evidence_ids = item.get("evidence_ids", [])
        row_object_ids = stable_unique([value for value in [item_id, *evidence_ids] if value])
        trace.add_objects(row_object_ids)
        trace.add_links(_links_between(context, row_object_ids))
        rows.append(
            [
                item_id,
                item.get("title"),
                item.get("status"),
                item.get("priority"),
                ", ".join(evidence_ids),
            ]
        )
    return rows, trace


def _safety_trace(context: DocumentContext, object_ids: list[str]) -> Trace:
    target_ids = set(object_ids)
    trace = Trace()
    for result in context.safety_gates.get("results", []):
        if result.get("object_id") not in target_ids:
            continue
        trace.add_object(result.get("object_id"))
        trace.add_objects([item.get("object_id") for item in result.get("evidence", [])])
        trace.add_objects([item.get("object_id") for item in result.get("assumptions", [])])
        trace.add_objects([item.get("object_id") for item in result.get("risks", [])])
        trace.add_links(result.get("source_link_ids", []))
    return trace


def _links_between(context: DocumentContext, object_ids: list[str]) -> list[str]:
    ids = set(object_ids)
    return sorted(
        stable_unique(
            link["id"]
            for link in context.scoped_project_state.get("links", [])
            if link.get("source_object_id") in ids and link.get("target_object_id") in ids
        )
    )
