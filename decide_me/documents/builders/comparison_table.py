from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, section, table_block
from decide_me.documents.builders.common import link_ids_touching, object_label, objects_by_id, objects_of_type, related_object_ids
from decide_me.taxonomy import stable_unique


def build_comparison_table_document(context: DocumentContext) -> dict[str, Any]:
    options = objects_of_type(context, "option")
    object_ids = [option["id"] for option in options]
    sections = [
        section(
            "comparison",
            "Comparison Table",
            10,
            [_comparison_table(context, options)],
            source_object_ids=object_ids,
            source_link_ids=link_ids_touching(context, object_ids),
        )
    ]
    return build_document(
        context,
        document_type="comparison-table",
        title="Comparison Table",
        sections=sections,
        diagnostic_types=["object_link_graph"],
    )


def _comparison_table(context: DocumentContext, options: list[dict[str, Any]]) -> dict[str, Any]:
    return table_block(
        [
            "Option",
            "Recommended By",
            "Criteria Fit",
            "Evidence",
            "Risks",
            "Constraints",
            "Status",
            "Notes",
        ],
        [_option_row(context, option) for option in options],
    )


def _option_row(context: DocumentContext, option: dict[str, Any]) -> list[Any]:
    proposal_ids = _proposal_ids_for_option(context, option["id"])
    decision_ids = _decision_ids_for_proposals(context, proposal_ids)
    related_scope = stable_unique([option["id"], *proposal_ids, *decision_ids])
    return [
        option.get("title") or option["id"],
        ", ".join(proposal_ids),
        _criteria_fit(context, related_scope),
        ", ".join(_related_ids(context, related_scope, {"evidence"})),
        ", ".join(_related_ids(context, related_scope, {"risk"})),
        ", ".join(_related_ids(context, related_scope, {"constraint"})),
        _option_status(context, option, proposal_ids, decision_ids),
        option.get("body"),
    ]


def _proposal_ids_for_option(context: DocumentContext, option_id: str) -> list[str]:
    by_id = objects_by_id(context)
    return sorted(
        stable_unique(
            link["source_object_id"]
            for link in context.project_state.get("links", [])
            if link.get("relation") == "recommends"
            and link.get("target_object_id") == option_id
            and by_id.get(link.get("source_object_id"), {}).get("type") == "proposal"
        )
    )


def _decision_ids_for_proposals(context: DocumentContext, proposal_ids: list[str]) -> list[str]:
    by_id = objects_by_id(context)
    proposal_set = set(proposal_ids)
    return sorted(
        stable_unique(
            link["target_object_id"]
            for link in context.project_state.get("links", [])
            if link.get("relation") == "addresses"
            and link.get("source_object_id") in proposal_set
            and by_id.get(link.get("target_object_id"), {}).get("type") == "decision"
        )
    )


def _criteria_fit(context: DocumentContext, object_ids: list[str]) -> str:
    criterion_ids = _related_ids(context, object_ids, {"criterion"})
    if not criterion_ids:
        return ""
    labels = []
    by_id = objects_by_id(context)
    scope = set(object_ids)
    for criterion_id in criterion_ids:
        relations = sorted(
            stable_unique(
                link["relation"]
                for link in context.project_state.get("links", [])
                if criterion_id in {link.get("source_object_id"), link.get("target_object_id")}
                and (link.get("source_object_id") in scope or link.get("target_object_id") in scope)
            )
        )
        labels.append(f"{object_label(by_id.get(criterion_id)) or criterion_id} ({', '.join(relations)})")
    return "; ".join(labels)


def _related_ids(context: DocumentContext, object_ids: list[str], types: set[str]) -> list[str]:
    related: list[str] = []
    for object_id in object_ids:
        related.extend(related_object_ids(context, object_id, types=types))
    return sorted(stable_unique(related))


def _option_status(
    context: DocumentContext,
    option: dict[str, Any],
    proposal_ids: list[str],
    decision_ids: list[str],
) -> str:
    proposal_set = set(proposal_ids)
    accepted = []
    for link in context.project_state.get("links", []):
        if link.get("relation") == "accepts" and link.get("target_object_id") in proposal_set:
            accepted.append(link.get("source_object_id"))
    if accepted:
        return f"accepted by {', '.join(sorted(stable_unique(accepted)))}"
    by_id = objects_by_id(context)
    decision_statuses = [
        by_id[decision_id].get("status")
        for decision_id in decision_ids
        if decision_id in by_id
    ]
    if "deferred" in decision_statuses:
        return "deferred"
    if option.get("status") in {"rejected", "invalidated"}:
        return option.get("status")
    return "open"
