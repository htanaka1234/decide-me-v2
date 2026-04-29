from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, list_block, section, table_block


def build_action_plan_document(context: DocumentContext) -> dict[str, Any]:
    if context.action_plan is None:
        raise ValueError("action-plan document export requires action plan context")
    action_plan = context.action_plan
    sections = [
        _summary_section(action_plan),
        _implementation_ready_section(action_plan),
        _actions_section(action_plan),
        _blockers_section(action_plan),
        _risks_section(action_plan),
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


def _implementation_ready_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    actions = action_plan.get("implementation_ready_actions", [])
    return section(
        "implementation-ready-actions",
        "Implementation-Ready Actions",
        20,
        [_action_table(actions)],
        source_object_ids=[item["id"] for item in actions if item.get("id")],
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _actions_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    actions = action_plan.get("actions", [])
    return section(
        "actions",
        "Actions",
        30,
        [_action_table(actions)],
        source_object_ids=[item["id"] for item in actions if item.get("id")],
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _blockers_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    blockers = action_plan.get("blockers", [])
    return section(
        "blockers",
        "Blockers",
        40,
        [
            table_block(
                ["ID", "Title", "Status", "Priority", "Frontier", "Evidence"],
                [
                    [
                        item.get("id"),
                        item.get("title"),
                        item.get("status"),
                        item.get("priority"),
                        item.get("frontier"),
                        ", ".join(item.get("evidence_ids", [])),
                    ]
                    for item in blockers
                ],
            )
        ],
        source_object_ids=[item["id"] for item in blockers if item.get("id")],
        source_link_ids=action_plan.get("source_link_ids", []),
    )


def _risks_section(action_plan: dict[str, Any]) -> dict[str, Any]:
    risks = action_plan.get("risks", [])
    return section(
        "risks",
        "Risks",
        50,
        [
            table_block(
                ["ID", "Title", "Status", "Priority", "Evidence"],
                [
                    [
                        item.get("id"),
                        item.get("title"),
                        item.get("status"),
                        item.get("priority"),
                        ", ".join(item.get("evidence_ids", [])),
                    ]
                    for item in risks
                ],
            )
        ],
        source_object_ids=[item["id"] for item in risks if item.get("id")],
        source_link_ids=action_plan.get("source_link_ids", []),
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


def _action_table(actions: list[dict[str, Any]]) -> dict[str, Any]:
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
        [
            [
                item.get("id"),
                item.get("name"),
                item.get("decision_id"),
                item.get("status"),
                item.get("priority"),
                item.get("implementation_ready"),
                (item.get("safety_gate") or {}).get("gate_status"),
                item.get("next_step") or item.get("summary"),
            ]
            for item in actions
        ],
    )
