from __future__ import annotations

from typing import Any

from decide_me.documents.context import DocumentContext
from decide_me.documents.model import build_document, section, table_block
from decide_me.documents.builders.common import Trace, links_for, object_label, objects_by_id, objects_of_type
from decide_me.taxonomy import stable_unique


def build_comparison_table_document(context: DocumentContext) -> dict[str, Any]:
    options = objects_of_type(context, "option")
    rows, trace = _comparison_rows(context, options)
    sections = [
        section(
            "comparison",
            "Comparison Table",
            10,
            [_comparison_table(rows)],
            source_object_ids=trace.object_ids,
            source_link_ids=trace.link_ids,
        )
    ]
    return build_document(
        context,
        document_type="comparison-table",
        title="Comparison Table",
        sections=sections,
        diagnostic_types=["object_link_graph"],
    )


def _comparison_rows(context: DocumentContext, options: list[dict[str, Any]]) -> tuple[list[list[Any]], Trace]:
    rows = []
    trace = Trace()
    for option in options:
        row, row_trace = _option_row(context, option)
        rows.append(row)
        trace.merge(row_trace)
    return rows, trace


def _comparison_table(rows: list[list[Any]]) -> dict[str, Any]:
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
        rows,
    )


def _option_row(context: DocumentContext, option: dict[str, Any]) -> tuple[list[Any], Trace]:
    trace = Trace()
    trace.add_object(option["id"])
    proposal_ids, proposal_link_ids = _proposal_ids_for_option(context, option["id"])
    trace.add_objects(proposal_ids)
    trace.add_links(proposal_link_ids)
    decision_ids, decision_link_ids = _decision_ids_for_proposals(context, proposal_ids)
    trace.add_objects(decision_ids)
    trace.add_links(decision_link_ids)
    accepted_status, accepted_trace = _option_status(context, option, proposal_ids, decision_ids)
    trace.merge(accepted_trace)
    related_scope = stable_unique([option["id"], *proposal_ids, *decision_ids])
    criteria_fit, criteria_trace = _criteria_fit(context, related_scope)
    evidence_ids, evidence_link_ids = _related_ids(context, related_scope, {"evidence"})
    risk_ids, risk_link_ids = _related_ids(context, related_scope, {"risk"})
    constraint_ids, constraint_link_ids = _related_ids(context, related_scope, {"constraint"})
    for object_ids, link_ids in (
        (evidence_ids, evidence_link_ids),
        (risk_ids, risk_link_ids),
        (constraint_ids, constraint_link_ids),
    ):
        trace.add_objects(object_ids)
        trace.add_links(link_ids)
    trace.merge(criteria_trace)
    return [
        option.get("title") or option["id"],
        ", ".join(proposal_ids),
        criteria_fit,
        ", ".join(evidence_ids),
        ", ".join(risk_ids),
        ", ".join(constraint_ids),
        accepted_status,
        option.get("body"),
    ], trace


def _proposal_ids_for_option(context: DocumentContext, option_id: str) -> tuple[list[str], list[str]]:
    by_id = objects_by_id(context)
    links = [
        link
        for link in links_for(context, relation="recommends", target_object_id=option_id)
        if by_id.get(link.get("source_object_id"), {}).get("type") == "proposal"
    ]
    return (
        sorted(stable_unique(link["source_object_id"] for link in links)),
        sorted(stable_unique(link["id"] for link in links)),
    )


def _decision_ids_for_proposals(context: DocumentContext, proposal_ids: list[str]) -> tuple[list[str], list[str]]:
    by_id = objects_by_id(context)
    proposal_set = set(proposal_ids)
    links = [
        link
        for link in links_for(context, relation="addresses")
        if link.get("source_object_id") in proposal_set
        and by_id.get(link.get("target_object_id"), {}).get("type") == "decision"
    ]
    return (
        sorted(stable_unique(link["target_object_id"] for link in links)),
        sorted(stable_unique(link["id"] for link in links)),
    )


def _criteria_fit(context: DocumentContext, object_ids: list[str]) -> tuple[str, Trace]:
    criterion_ids, criterion_link_ids = _related_ids(context, object_ids, {"criterion"})
    trace = Trace(criterion_ids, criterion_link_ids)
    if not criterion_ids:
        return "", trace
    labels = []
    by_id = objects_by_id(context)
    scope = set(object_ids)
    for criterion_id in criterion_ids:
        matching_links = [
            link
            for link in context.scoped_project_state.get("links", [])
            if criterion_id in {link.get("source_object_id"), link.get("target_object_id")}
            and (link.get("source_object_id") in scope or link.get("target_object_id") in scope)
        ]
        relations = sorted(stable_unique(link["relation"] for link in matching_links))
        trace.add_links([link["id"] for link in matching_links])
        labels.append(f"{object_label(by_id.get(criterion_id)) or criterion_id} ({', '.join(relations)})")
    return "; ".join(labels), trace


def _related_ids(context: DocumentContext, object_ids: list[str], types: set[str]) -> tuple[list[str], list[str]]:
    by_id = objects_by_id(context)
    scope = set(object_ids)
    related: list[str] = []
    link_ids: list[str] = []
    for link in context.scoped_project_state.get("links", []):
        source = link.get("source_object_id")
        target = link.get("target_object_id")
        if source in scope and by_id.get(target, {}).get("type") in types:
            related.append(target)
            link_ids.append(link["id"])
        elif target in scope and by_id.get(source, {}).get("type") in types:
            related.append(source)
            link_ids.append(link["id"])
    return sorted(stable_unique(related)), sorted(stable_unique(link_ids))


def _option_status(
    context: DocumentContext,
    option: dict[str, Any],
    proposal_ids: list[str],
    decision_ids: list[str],
) -> tuple[str, Trace]:
    trace = Trace()
    proposal_set = set(proposal_ids)
    accepted = []
    for link in context.scoped_project_state.get("links", []):
        if link.get("relation") == "accepts" and link.get("target_object_id") in proposal_set:
            accepted.append(link.get("source_object_id"))
            trace.add_object(link.get("source_object_id"), link.get("target_object_id"))
            trace.add_link(link.get("id"))
    if accepted:
        return f"accepted by {', '.join(sorted(stable_unique(accepted)))}", trace
    by_id = objects_by_id(context)
    decision_statuses = [
        by_id[decision_id].get("status")
        for decision_id in decision_ids
        if decision_id in by_id
    ]
    if "deferred" in decision_statuses:
        return "deferred", trace
    if option.get("status") in {"rejected", "invalidated"}:
        return option.get("status"), trace
    return "open", trace
