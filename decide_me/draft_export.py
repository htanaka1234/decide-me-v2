from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from decide_me.constants import DECISION_STACK_LAYER_ORDER
from decide_me.documents.merge import marker_warnings_for_path, merge_managed_content
from decide_me.draft_projection import project_draft_set
from decide_me.draft_sets import draft_set_dir, load_draft_set
from decide_me.events import utc_now
from decide_me.exporters.render import render_table_cell
from decide_me.store import _atomic_write_json, _atomic_write_text, _write_lock, load_runtime, runtime_paths


DRAFT_REVIEW_QUEUE_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "draft-review-queue.schema.json"

PRIORITY_RANK = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
}
LAYER_RANK = {layer: index for index, layer in enumerate(DECISION_STACK_LAYER_ORDER)}
RISK_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}
EVIDENCE_RANK = {
    "challenged": 0,
    "none": 1,
    "partial": 2,
    "sufficient": 3,
}
REVIEW_MODE_RANK = {
    "blocked": 0,
    "individual": 1,
    "bulk": 2,
    "already_promoted": 3,
}
EVIDENCE_STATUS_ALIASES = {
    "challenged": "challenged",
    "none": "none",
    "partial": "partial",
    "sufficient": "sufficient",
    "complete": "sufficient",
    "unknown": "unknown",
}
MISSING_EVIDENCE_STATUSES = {"challenged", "none", "unknown"}
DRAFT_BANNER = (
    "> **DRAFT / NOT ACCEPTED**\n"
    "> This file is a readable draft export. It is not canonical runtime state and does not represent accepted decisions."
)
DRAFT_EXPORT_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "drafts"
DRAFT_EXPORT_SPECS = {
    "preflight": ("preflight.md", "draft-preflight"),
    "draft_decisions": ("draft-decisions.md", "draft-decisions"),
    "review_queue": ("review-queue.md", "draft-review-queue"),
    "assumptions_risks": ("assumptions-risks.md", "draft-assumptions-risks"),
}


class DraftReviewQueueValidationError(ValueError):
    pass


def review_draft_set(
    ai_dir: str | Path,
    draft_set_id: str,
    *,
    now: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Build and optionally persist review-queue.json."""
    paths = runtime_paths(ai_dir)
    generated_at = now or utc_now()
    with _write_lock(paths.lock_path):
        draft_set = load_draft_set(paths.ai_dir, draft_set_id)
        current_project_head = _current_project_head(paths.ai_dir)
        review_queue = build_review_queue(
            draft_set,
            current_project_head=current_project_head,
            generated_at=generated_at,
        )
        validate_review_queue(review_queue)
        if persist:
            _atomic_write_json(draft_set_dir(paths.ai_dir, draft_set_id) / "review-queue.json", review_queue)
    return review_queue


def export_draft_set(
    ai_dir: str | Path,
    draft_set_id: str,
    *,
    format: str = "markdown",
    now: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Write readable export files and review-queue.json."""
    if format != "markdown":
        raise ValueError("draft set export format must be markdown")

    paths = runtime_paths(ai_dir)
    generated_at = now or utc_now()
    with _write_lock(paths.lock_path):
        draft_set = load_draft_set(paths.ai_dir, draft_set_id)
        bundle = load_runtime(paths)
        project_state = bundle["project_state"]
        current_project_head = _project_head_from_state(project_state)
        review_queue = build_review_queue(
            draft_set,
            current_project_head=current_project_head,
            generated_at=generated_at,
        )
        draft_dir = draft_set_dir(paths.ai_dir, draft_set_id)
        draft_projection = project_draft_set(
            project_state=project_state,
            draft_set=draft_set,
            current_project_head=current_project_head,
            generated_at=generated_at,
        )
        exports_dir = draft_dir / "exports"
        output_paths = _draft_export_paths(exports_dir)
        _extend_warnings(
            review_queue,
            _marker_warnings(output_paths, project_head=current_project_head),
        )
        validate_review_queue(review_queue)

        rendered = render_draft_exports(
            draft_set,
            review_queue,
            current_project_head=current_project_head,
            generated_at=generated_at,
            draft_projection=draft_projection,
        )
        prepared = _prepare_markdown_writes(
            output_paths,
            rendered,
            project_head=current_project_head,
            force=force,
        )

        review_queue_path = draft_dir / "review-queue.json"
        _atomic_write_json(review_queue_path, review_queue)
        for output_path, body in prepared.items():
            _atomic_write_text(output_path, body)

    return {
        "status": "ok",
        "draft_set_id": draft_set_id,
        "format": format,
        "review_queue_path": str(review_queue_path),
        "paths": {
            key: str(output_paths[key])
            for key in ("preflight", "draft_decisions", "review_queue", "assumptions_risks")
        },
        "warnings": list(review_queue["warnings"]),
    }


def build_review_queue(
    draft_set: dict[str, Any],
    *,
    current_project_head: str | None,
    generated_at: str,
) -> dict[str, Any]:
    """Pure deterministic review queue builder."""
    project_head_at_generation = _project_head_at_generation(draft_set)
    stale = (
        project_head_at_generation is not None
        and current_project_head is not None
        and project_head_at_generation != current_project_head
    )
    warnings: list[str] = []
    if stale:
        warnings.append(
            "stale project_head: "
            f"generated at {project_head_at_generation}, current is {current_project_head}."
        )

    promotion = _dict_field(draft_set, "promotion")
    promoted_ids = set(_string_list(promotion.get("promoted_decision_ids")))
    bulk_requested_ids = set(_string_list(promotion.get("bulk_promotable_ids")))
    individual_requested_ids = set(_string_list(promotion.get("individual_review_required_ids")))
    conflicts = _list_field(draft_set, "conflicts")

    ranked_items: list[tuple[tuple[int, int, int, int, int, str], dict[str, Any]]] = []
    draft_decisions = _list_field(draft_set, "draft_decisions")
    for draft in draft_decisions:
        if not isinstance(draft, dict):
            continue
        item = _review_item(
            draft,
            conflicts=conflicts,
            promoted_ids=promoted_ids,
            bulk_requested_ids=bulk_requested_ids,
            individual_requested_ids=individual_requested_ids,
        )
        ranked_items.append((_review_sort_key(item, draft), item))

    ranked_items.sort(key=lambda pair: pair[0])
    review_order = [item for _sort_key, item in ranked_items]
    for rank, item in enumerate(review_order, start=1):
        item["rank"] = rank

    bulk_promotable = [item["draft_decision_id"] for item in review_order if item["review_mode"] == "bulk"]
    individual_review_required = [
        item["draft_decision_id"] for item in review_order if item["review_mode"] == "individual"
    ]
    blocked = [item["draft_decision_id"] for item in review_order if item["review_mode"] == "blocked"]
    must_not_bulk_promote = [item["draft_decision_id"] for item in review_order if item["review_mode"] in {"blocked", "individual"}]

    review_queue = {
        "schema_version": 1,
        "draft_set_id": str(draft_set.get("id") or ""),
        "status": "warning" if warnings else "ok",
        "generated_at": generated_at,
        "project_head_at_generation": project_head_at_generation,
        "current_project_head": current_project_head,
        "stale": stale,
        "summary": {
            "draft_decision_count": len(draft_decisions),
            "blocked_count": len(blocked),
            "individual_review_required_count": len(individual_review_required),
            "bulk_promotable_count": len(bulk_promotable),
            "high_risk_count": sum(
                1
                for draft in draft_decisions
                if isinstance(draft, dict) and str(draft.get("risk_tier") or "").lower() in {"high", "critical"}
            ),
            "missing_evidence_count": sum(
                1 for draft in draft_decisions if isinstance(draft, dict) and _has_missing_evidence(draft)
            ),
        },
        "review_order": review_order,
        "bulk_promotable": bulk_promotable,
        "individual_review_required": individual_review_required,
        "blocked": blocked,
        "must_not_bulk_promote": must_not_bulk_promote,
        "warnings": warnings,
    }
    return review_queue


def render_draft_exports(
    draft_set: dict[str, Any],
    review_queue: dict[str, Any],
    *,
    current_project_head: str | None,
    generated_at: str,
    draft_projection: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return markdown bodies keyed by filename."""
    return {
        "preflight.md": _apply_template(
            "preflight.md",
            _render_preflight(
                draft_set,
                review_queue,
                current_project_head=current_project_head,
                generated_at=generated_at,
                draft_projection=draft_projection,
            ),
        ),
        "draft-decisions.md": _apply_template("draft-decisions.md", _render_draft_decisions(draft_set, review_queue)),
        "review-queue.md": _apply_template("review-queue.md", _render_review_queue(review_queue)),
        "assumptions-risks.md": _apply_template("assumptions-risks.md", _render_assumptions_risks(draft_set)),
    }


def validate_review_queue(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise DraftReviewQueueValidationError("draft review queue validation failed: payload must be an object")
    _validate_date_time_field(payload, "generated_at")
    errors = sorted(_schema_validator().iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise DraftReviewQueueValidationError(
            f"draft review queue validation failed: {_format_validation_error(errors[0])}"
        )


def _review_item(
    draft: dict[str, Any],
    *,
    conflicts: list[Any],
    promoted_ids: set[str],
    bulk_requested_ids: set[str],
    individual_requested_ids: set[str],
) -> dict[str, Any]:
    draft_id = str(draft.get("id") or "")
    priority = _nullable_string(draft.get("priority"))
    layer = _nullable_string(draft.get("layer"))
    risk_tier = _nullable_string(draft.get("risk_tier"))
    reasons: list[str] = []
    if priority in {"P0", "P1"}:
        reasons.append(f"{priority} decision")

    if draft_id in promoted_ids:
        reasons.append("promotion.promoted_decision_ids includes draft decision; PR-2 treats this as informational only")

    blocking_reasons = _blocking_reasons(draft)
    if blocking_reasons:
        review_mode = "blocked"
        reasons.extend(blocking_reasons)
    else:
        human_review = _dict_field(draft, "human_review")
        evidence_status = _normalized_evidence_status(_dict_field(draft, "evidence_coverage").get("status"))
        risk = str(draft.get("risk_tier") or "").lower()
        if _has_conflict(conflicts, draft_id):
            review_mode = "individual"
            reasons.append("draft decision has conflicts")
        elif risk in {"high", "critical"}:
            review_mode = "individual"
            reasons.append(f"risk_tier is {risk}")
        elif draft_id in individual_requested_ids:
            review_mode = "individual"
            reasons.append("promotion.individual_review_required_ids includes draft decision")
        elif human_review.get("required") is True:
            review_mode = "individual"
            reasons.append("human_review.required is true")
        elif human_review.get("mode") == "individual":
            review_mode = "individual"
            reasons.append("human_review.mode is individual")
        elif evidence_status in {"none", "challenged"}:
            review_mode = "individual"
            reasons.append(f"evidence_coverage.status is {evidence_status}")
        elif _is_low_risk_bulk_candidate(draft, conflicts=conflicts):
            review_mode = "bulk"
            reasons.append("low-risk draft is marked bulk_promotable")
            if draft_id in bulk_requested_ids:
                reasons.append("promotion.bulk_promotable_ids includes draft decision")
        else:
            review_mode = "individual"
            reasons.append("requires individual review by default")

    return {
        "draft_decision_id": draft_id,
        "priority": priority,
        "layer": layer,
        "risk_tier": risk_tier,
        "review_mode": review_mode,
        "promotion_readiness": _promotion_readiness(review_mode),
        "rank": 1,
        "reasons": _unique(reasons),
        "required_action": _required_action(review_mode),
    }


def _blocking_reasons(draft: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if draft.get("status") == "accepted":
        reasons.append("status accepted is not allowed for draft decisions")
    if not _non_empty_string(draft.get("question")):
        reasons.append("missing question")
    if not _non_empty_string(draft.get("recommendation")):
        reasons.append("missing recommendation")
    if not _list_field(draft, "alternatives"):
        reasons.append("missing alternatives")
    if str(draft.get("risk_tier") or "").lower() not in RISK_RANK:
        reasons.append("risk_tier is missing or invalid")

    human_review = draft.get("human_review")
    if not isinstance(human_review, dict):
        reasons.append("human_review is missing")

    promotion_recipe = draft.get("promotion_recipe")
    if not isinstance(promotion_recipe, dict):
        reasons.append("promotion_recipe is missing")
    elif promotion_recipe.get("canonical_object_type") != "decision":
        reasons.append("promotion_recipe.canonical_object_type must be decision")

    evidence_coverage = draft.get("evidence_coverage")
    if not isinstance(evidence_coverage, dict) or not _non_empty_string(evidence_coverage.get("status")):
        reasons.append("evidence_coverage.status is missing")
    elif _normalized_evidence_status(evidence_coverage.get("status")) is None:
        reasons.append("evidence_coverage.status is invalid")
    return reasons


def _is_low_risk_bulk_candidate(draft: dict[str, Any], *, conflicts: list[Any]) -> bool:
    draft_id = str(draft.get("id") or "")
    human_review = _dict_field(draft, "human_review")
    promotion_recipe = _dict_field(draft, "promotion_recipe")
    evidence_status = _normalized_evidence_status(_dict_field(draft, "evidence_coverage").get("status"))
    return (
        str(draft.get("risk_tier") or "").lower() == "low"
        and human_review.get("bulk_promotable") is True
        and _non_empty_string(draft.get("recommendation"))
        and bool(_list_field(draft, "alternatives"))
        and evidence_status in {"partial", "sufficient"}
        and not _has_conflict(conflicts, draft_id)
        and promotion_recipe.get("blocked_for_bulk_acceptance") is not True
    )


def _review_sort_key(item: dict[str, Any], draft: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    evidence_status = _normalized_evidence_status(_dict_field(draft, "evidence_coverage").get("status"))
    return (
        REVIEW_MODE_RANK.get(str(item.get("review_mode")), len(REVIEW_MODE_RANK)),
        PRIORITY_RANK.get(str(item.get("priority")), len(PRIORITY_RANK)),
        LAYER_RANK.get(str(item.get("layer")), len(LAYER_RANK)),
        RISK_RANK.get(str(item.get("risk_tier")), len(RISK_RANK)),
        EVIDENCE_RANK.get(str(evidence_status), len(EVIDENCE_RANK)),
        str(item.get("draft_decision_id") or ""),
    )


def _promotion_readiness(review_mode: str) -> str:
    return {
        "blocked": "blocked",
        "individual": "review_required",
        "bulk": "bulk_materialize_candidate",
        "already_promoted": "already_promoted",
    }[review_mode]


def _required_action(review_mode: str) -> str:
    return {
        "blocked": "Resolve blocking draft fields before promotion.",
        "individual": "Review individually before promotion.",
        "bulk": "Eligible for low-risk bulk materialization review; not accepted by this export.",
        "already_promoted": "No review required; already promoted.",
    }[review_mode]


def _render_preflight(
    draft_set: dict[str, Any],
    review_queue: dict[str, Any],
    *,
    current_project_head: str | None,
    generated_at: str,
    draft_projection: dict[str, Any] | None,
) -> str:
    goal = _dict_field(draft_set, "goal")
    source_context = _dict_field(draft_set, "source_context")
    convergence = _dict_field(draft_projection, "convergence") if isinstance(draft_projection, dict) else {}
    summary = _dict_field(review_queue, "summary")
    lines = [
        DRAFT_BANNER,
        "",
        "## Goal",
        f"- Goal ID: {_text(goal.get('id'))}",
        f"- Title: {_text(goal.get('title'))}",
        f"- Desired outcome: {_text(goal.get('desired_outcome'))}",
        f"- Constraints: {_inline_list(goal.get('constraints'))}",
        "",
        "## Source Context",
        f"- Draft set: {_text(draft_set.get('id'))}",
        f"- Generated at: {_text(generated_at)}",
        f"- Project head at generation: {_text(_project_head_at_generation(draft_set))}",
        f"- Current project head: {_text(current_project_head)}",
        f"- Stale: {'yes' if review_queue.get('stale') else 'no'}",
        f"- Project state ref: {_text(source_context.get('project_state_ref'))}",
        f"- Domain pack: {_text(source_context.get('domain_pack_id'))}",
        "",
        "## Convergence",
        f"- Status: {_text(convergence.get('status'))}",
        f"- Iterations: {_text(convergence.get('iterations'))}",
        f"- Stop reason: {_text(convergence.get('stop_reason'))}",
        f"- Explanation: {_text(convergence.get('explanation'))}",
        "",
        "## Summary",
        _table(
            ["Metric", "Value"],
            [
                ["Draft decisions", summary.get("draft_decision_count")],
                ["Blocked", summary.get("blocked_count")],
                ["Individual review required", summary.get("individual_review_required_count")],
                ["Bulk materialize candidates", summary.get("bulk_promotable_count")],
                ["High/Critical risk", summary.get("high_risk_count")],
                ["Missing or challenged evidence", summary.get("missing_evidence_count")],
            ],
        ),
        "",
        "## Coverage Summary",
        _render_coverage_summary(draft_projection),
        "",
        "## Coverage Matrix",
        _render_coverage_matrix(draft_projection),
        "",
        "## Gap Diagnostics",
        _render_gap_diagnostics(draft_projection),
        "",
        "## Human Approval Plan",
        "- Review blocked items first.",
        "- Review P0/P1 individual items next.",
        "- Only low-risk bulk candidates may be materialized in bulk.",
        "- No item is accepted by this export.",
        "",
        "## Top Review Items",
        _table(
            ["Rank", "Draft Decision", "Priority", "Layer", "Risk", "Mode", "Required Action"],
            [
                [
                    item.get("rank"),
                    item.get("draft_decision_id"),
                    item.get("priority"),
                    item.get("layer"),
                    item.get("risk_tier"),
                    item.get("review_mode"),
                    item.get("required_action"),
                ]
                for item in _list_field(review_queue, "review_order")
                if item.get("review_mode") != "already_promoted"
            ],
        ),
        "",
        "## Warnings",
        _bullet_list(review_queue.get("warnings")),
    ]
    return "\n".join(lines)


def _render_coverage_summary(draft_projection: dict[str, Any] | None) -> str:
    if not isinstance(draft_projection, dict):
        return "- coverage diagnostics unavailable"
    coverage_summary = _dict_field(draft_projection, "coverage_summary")
    return _table(
        ["Metric", "Value"],
        [
            ["Required targets", coverage_summary.get("required_target_count")],
            ["Covered", coverage_summary.get("covered_count")],
            ["Partial", coverage_summary.get("partial_count")],
            ["Missing", coverage_summary.get("missing_count")],
            ["Blocking coverage gaps", coverage_summary.get("blocking_gap_count")],
        ],
    )


def _render_coverage_matrix(draft_projection: dict[str, Any] | None) -> str:
    if not isinstance(draft_projection, dict):
        return "- coverage diagnostics unavailable"
    return _table(
        [
            "Axis",
            "Type",
            "Target",
            "Observed",
            "Priority",
            "Required",
            "Status",
            "Blocks",
            "Covered By",
            "Remaining Gaps",
        ],
        [
            [
                row.get("axis_id"),
                row.get("axis_type"),
                row.get("value"),
                row.get("observed_value"),
                row.get("priority"),
                row.get("required"),
                row.get("status"),
                row.get("blocks_convergence"),
                row.get("covered_by"),
                row.get("remaining_gaps"),
            ]
            for row in _list_field(draft_projection, "coverage_matrix")
        ],
    )


def _render_gap_diagnostics(draft_projection: dict[str, Any] | None) -> str:
    if not isinstance(draft_projection, dict):
        return "- draft-projection.json not generated"
    convergence = _dict_field(draft_projection, "convergence")
    lines = [
        _table(
            ["Metric", "Value"],
            [
                ["Status", convergence.get("status")],
                ["Stop reason", convergence.get("stop_reason")],
                ["Gap count", convergence.get("new_gap_count")],
                ["Blocking gaps", convergence.get("blocking_gap_count")],
            ],
        ),
        "",
        _table(
            ["ID", "Type", "Severity", "Target", "Blocks", "Reason"],
            [
                [
                    gap.get("id"),
                    gap.get("type"),
                    gap.get("severity"),
                    gap.get("target_id"),
                    gap.get("blocks_convergence"),
                    gap.get("reason"),
                ]
                for gap in _list_field(draft_projection, "gap_diagnostics")
            ],
        ),
    ]
    return "\n".join(lines)


def _render_draft_decisions(draft_set: dict[str, Any], review_queue: dict[str, Any]) -> str:
    draft_by_id = {
        str(draft.get("id")): draft
        for draft in _list_field(draft_set, "draft_decisions")
        if isinstance(draft, dict) and draft.get("id") is not None
    }
    lines = [DRAFT_BANNER, "", "## Decisions by Review Order"]
    for item in _list_field(review_queue, "review_order"):
        draft = draft_by_id.get(str(item.get("draft_decision_id")))
        if draft is None:
            continue
        evidence = _dict_field(draft, "evidence_coverage")
        human_review = _dict_field(draft, "human_review")
        lines.extend(
            [
                "",
                f"### {draft.get('id')}: {_text(draft.get('question'))}",
                "",
                _table(
                    ["Field", "Value"],
                    [
                        ["Status", draft.get("status")],
                        ["Priority", draft.get("priority")],
                        ["Layer", draft.get("layer")],
                        ["Risk tier", draft.get("risk_tier")],
                        ["Reversibility", draft.get("reversibility")],
                        ["Review mode", item.get("review_mode")],
                    ],
                ),
                "",
                "#### Recommendation",
                "",
                _text(draft.get("recommendation")),
                "",
                "#### Rationale",
                "",
                _text(draft.get("rationale")),
                "",
                "#### Alternatives / Rejected Options",
                "",
                _table(
                    ["Option", "Reason not recommended"],
                    [
                        [
                            _alternative_value(alternative, "option"),
                            _alternative_value(alternative, "reason_not_recommended"),
                        ]
                        for alternative in _list_field(draft, "alternatives")
                    ],
                ),
                "",
                "#### Evidence Coverage",
                "",
                _table(
                    ["Field", "Value"],
                    [
                        ["Status", evidence.get("status")],
                        ["Supporting object IDs", evidence.get("supporting_object_ids")],
                        ["Source unit IDs", evidence.get("source_unit_ids")],
                        ["Missing", evidence.get("missing")],
                    ],
                ),
                "",
                "#### Human Review",
                "",
                _table(
                    ["Field", "Value"],
                    [
                        ["Required", human_review.get("required")],
                        ["Mode", human_review.get("mode")],
                        ["Bulk promotable", human_review.get("bulk_promotable")],
                        ["Reason", human_review.get("reason")],
                    ],
                ),
            ]
        )
    return "\n".join(lines)


def _render_review_queue(review_queue: dict[str, Any]) -> str:
    items = _list_field(review_queue, "review_order")
    by_id = {str(item.get("draft_decision_id")): item for item in items if isinstance(item, dict)}
    lines = [
        DRAFT_BANNER,
        "",
        "## Review Order",
        _table(
            ["Rank", "ID", "Priority", "Layer", "Risk", "Mode", "Readiness", "Reasons", "Required Action"],
            [
                [
                    item.get("rank"),
                    item.get("draft_decision_id"),
                    item.get("priority"),
                    item.get("layer"),
                    item.get("risk_tier"),
                    item.get("review_mode"),
                    item.get("promotion_readiness"),
                    item.get("reasons"),
                    item.get("required_action"),
                ]
                for item in items
            ],
        ),
        "",
        "## Blocked Items",
        _table(
            ["ID", "Reasons", "Required Action"],
            [
                [
                    draft_id,
                    by_id.get(str(draft_id), {}).get("reasons"),
                    by_id.get(str(draft_id), {}).get("required_action"),
                ]
                for draft_id in _list_field(review_queue, "blocked")
            ],
        ),
        "",
        "## Individual Review Required",
        _table(
            ["ID", "Priority", "Risk", "Reasons"],
            [
                [
                    draft_id,
                    by_id.get(str(draft_id), {}).get("priority"),
                    by_id.get(str(draft_id), {}).get("risk_tier"),
                    by_id.get(str(draft_id), {}).get("reasons"),
                ]
                for draft_id in _list_field(review_queue, "individual_review_required")
            ],
        ),
        "",
        "## Bulk Materialize Candidates",
        _table(
            ["ID", "Priority", "Risk", "Reason"],
            [
                [
                    draft_id,
                    by_id.get(str(draft_id), {}).get("priority"),
                    by_id.get(str(draft_id), {}).get("risk_tier"),
                    by_id.get(str(draft_id), {}).get("reasons"),
                ]
                for draft_id in _list_field(review_queue, "bulk_promotable")
            ],
        ),
        "",
        "## Must Not Bulk Promote",
        _table(
            ["ID", "Reasons"],
            [
                [draft_id, by_id.get(str(draft_id), {}).get("reasons")]
                for draft_id in _list_field(review_queue, "must_not_bulk_promote")
            ],
        ),
    ]
    return "\n".join(lines)


def _render_assumptions_risks(draft_set: dict[str, Any]) -> str:
    lines = [
        DRAFT_BANNER,
        "",
        "## Draft Assumptions",
        _table(
            ["ID", "Statement", "Evidence status", "Missing evidence", "Invalidates if false", "Owner"],
            [
                [
                    item.get("id"),
                    _annotation_statement(item),
                    _annotation_evidence_status(item),
                    _annotation_missing_evidence(item),
                    _first_present(item, "invalidates_if_false", "invalidates", "false_would_invalidate"),
                    item.get("owner"),
                ]
                for item in _annotation_items(draft_set, "draft_assumptions")
            ],
        ),
        "",
        "## Draft Risks",
        _table(
            ["ID", "Statement", "Severity", "Likelihood", "Risk tier", "Reversibility", "Approval threshold"],
            [
                [
                    item.get("id"),
                    _annotation_statement(item),
                    item.get("severity"),
                    item.get("likelihood"),
                    item.get("risk_tier"),
                    item.get("reversibility"),
                    item.get("approval_threshold"),
                ]
                for item in _annotation_items(draft_set, "draft_risks")
            ],
        ),
        "",
        "## High / Critical Risks",
        _table(
            ["ID", "Statement", "Required review"],
            _high_critical_risk_rows(draft_set),
        ),
        "",
        "## Draft Actions",
        _table(
            ["ID", "Summary", "Linked decisions", "Verification refs"],
            [
                [
                    item.get("id"),
                    _annotation_statement(item),
                    _first_present(item, "linked_decisions", "linked_decision_ids", "draft_decision_ids", "target_ids"),
                    _first_present(item, "verification_refs", "verification_ids", "verifies"),
                ]
                for item in _annotation_items(draft_set, "draft_actions")
            ],
        ),
        "",
        "## Draft Verifications",
        _table(
            ["ID", "Method", "Result", "Target IDs"],
            [
                [
                    item.get("id"),
                    item.get("method"),
                    item.get("result"),
                    _first_present(item, "target_ids", "linked_decisions", "linked_decision_ids"),
                ]
                for item in _annotation_items(draft_set, "draft_verifications")
            ],
        ),
        "",
        "## AI Inference / Missing Evidence",
        _table(["Source", "Item ID", "Missing"], _missing_evidence_rows(draft_set)),
    ]
    return "\n".join(lines)


def _project_head_at_generation(draft_set: dict[str, Any]) -> str | None:
    source_context = _dict_field(draft_set, "source_context")
    value = source_context.get("project_head_at_generation", source_context.get("project_head"))
    return value if isinstance(value, str) and value else None


def _current_project_head(ai_dir: Path) -> str | None:
    bundle = load_runtime(runtime_paths(ai_dir))
    return _project_head_from_state(bundle.get("project_state", {}))


def _project_head_from_state(project_state: dict[str, Any]) -> str | None:
    value = project_state.get("state", {}).get("project_head")
    return value if isinstance(value, str) and value else None


def _has_conflict(conflicts: list[Any], draft_decision_id: str) -> bool:
    return any(_object_mentions_id(conflict, draft_decision_id) for conflict in conflicts)


def _object_mentions_id(value: Any, object_id: str) -> bool:
    if isinstance(value, str):
        return value == object_id
    if isinstance(value, dict):
        return any(_object_mentions_id(item, object_id) for item in value.values())
    if isinstance(value, list):
        return any(_object_mentions_id(item, object_id) for item in value)
    return False


def _normalized_evidence_status(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return EVIDENCE_STATUS_ALIASES.get(value.lower())


def _has_missing_evidence(draft: dict[str, Any]) -> bool:
    evidence = _dict_field(draft, "evidence_coverage")
    evidence_status = _normalized_evidence_status(evidence.get("status"))
    return evidence_status in MISSING_EVIDENCE_STATUSES or bool(_list_field(evidence, "missing"))


def _draft_export_paths(exports_dir: Path) -> dict[str, Path]:
    return {key: exports_dir / filename for key, (filename, _document_type) in DRAFT_EXPORT_SPECS.items()}


def _marker_warnings(output_paths: dict[str, Path], *, project_head: str | None) -> list[str]:
    warnings: list[str] = []
    for key, output_path in output_paths.items():
        document_type = DRAFT_EXPORT_SPECS[key][1]
        warnings.extend(
            warning
            for warning in marker_warnings_for_path(
                output_path,
                document_type=document_type,
                project_head=project_head,
            )
            if warning not in warnings
        )
    return warnings


def _prepare_markdown_writes(
    output_paths: dict[str, Path],
    rendered: dict[str, str],
    *,
    project_head: str | None,
    force: bool,
) -> dict[Path, str]:
    prepared: dict[Path, str] = {}
    for key, output_path in output_paths.items():
        filename, document_type = DRAFT_EXPORT_SPECS[key]
        existing = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        merged, _warnings = merge_managed_content(
            existing,
            rendered[filename],
            document_type=document_type,
            project_head=project_head,
            force=force,
        )
        prepared[output_path] = merged
    return prepared


def _extend_warnings(review_queue: dict[str, Any], warnings: list[str]) -> None:
    if not warnings:
        return
    existing = _list_field(review_queue, "warnings")
    for warning in warnings:
        if warning not in existing:
            existing.append(warning)
    review_queue["warnings"] = existing
    review_queue["status"] = "warning"


def _apply_template(filename: str, content: str) -> str:
    return _read_template(filename).replace("{{content}}", content.rstrip()).rstrip() + "\n"


@lru_cache(maxsize=None)
def _read_template(filename: str) -> str:
    return (DRAFT_EXPORT_TEMPLATE_DIR / filename).read_text(encoding="utf-8")


def _table(headers: list[Any], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(render_table_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    if not rows:
        rows = [["none recorded", *("" for _header in headers[1:])]]
    for row in rows:
        padded = [*row, *(None for _missing in range(max(0, len(headers) - len(row))))]
        lines.append("| " + " | ".join(render_table_cell(value) for value in padded[: len(headers)]) + " |")
    return "\n".join(lines)


def _bullet_list(value: Any) -> str:
    values = _string_list(value)
    if not values:
        return "- none"
    return "\n".join(f"- {render_table_cell(item)}" for item in values)


def _inline_list(value: Any) -> str:
    values = _string_list(value)
    return ", ".join(values) if values else "none recorded"


def _text(value: Any) -> str:
    if value is None:
        return "none recorded"
    if isinstance(value, str):
        return value.strip() or "none recorded"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _nullable_string(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dict_field(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    return item if isinstance(item, dict) else {}


def _list_field(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    return item if isinstance(item, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item) != ""]


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


def _alternative_value(alternative: Any, key: str) -> Any:
    if isinstance(alternative, dict):
        return alternative.get(key)
    if key == "option":
        return alternative
    return None


def _annotation_items(draft_set: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in _list_field(draft_set, key) if isinstance(item, dict)]


def _annotation_statement(item: dict[str, Any]) -> Any:
    return _first_present(item, "statement", "summary", "title", "description", "note")


def _annotation_evidence_status(item: dict[str, Any]) -> Any:
    if "evidence_status" in item:
        return item.get("evidence_status")
    evidence = item.get("evidence_coverage")
    if isinstance(evidence, dict):
        return evidence.get("status")
    return item.get("status")


def _annotation_missing_evidence(item: dict[str, Any]) -> Any:
    if "missing_evidence" in item:
        return item.get("missing_evidence")
    evidence = item.get("evidence_coverage")
    if isinstance(evidence, dict):
        return evidence.get("missing")
    return item.get("missing")


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item.get(key)
    return None


def _high_critical_risk_rows(draft_set: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for draft in _annotation_items(draft_set, "draft_risks"):
        tier = str(draft.get("risk_tier") or draft.get("severity") or "").lower()
        if tier in {"high", "critical"}:
            rows.append([draft.get("id"), _annotation_statement(draft), "Review individually before promotion."])
    for draft in _annotation_items(draft_set, "draft_decisions"):
        tier = str(draft.get("risk_tier") or "").lower()
        if tier in {"high", "critical"}:
            rows.append([draft.get("id"), draft.get("question"), "High/Critical risk requires individual review."])
    return rows


def _missing_evidence_rows(draft_set: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for draft in _annotation_items(draft_set, "draft_decisions"):
        evidence = _dict_field(draft, "evidence_coverage")
        missing = _list_field(evidence, "missing")
        status = _normalized_evidence_status(evidence.get("status"))
        if missing:
            rows.append(["draft_decision.evidence_coverage", draft.get("id"), missing])
        elif status in MISSING_EVIDENCE_STATUSES:
            rows.append(["draft_decision.evidence_coverage", draft.get("id"), f"Evidence status is {status}."])
    for key in ("draft_assumptions", "draft_risks", "draft_actions", "draft_verifications"):
        for item in _annotation_items(draft_set, key):
            missing = _annotation_missing_evidence(item)
            if missing:
                rows.append([key, item.get("id"), missing])
    return rows


def _schema_validator() -> Draft202012Validator:
    if not hasattr(_schema_validator, "_validator"):
        schema = json.loads(DRAFT_REVIEW_QUEUE_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _schema_validator._validator = Draft202012Validator(schema, format_checker=FormatChecker())  # type: ignore[attr-defined]
    return _schema_validator._validator  # type: ignore[attr-defined]


def _validate_date_time_field(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, str):
        return
    if "T" not in value:
        raise DraftReviewQueueValidationError(f"draft review queue validation failed: {field} must be date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DraftReviewQueueValidationError(
            f"draft review queue validation failed: {field} must be date-time"
        ) from exc
    if parsed.tzinfo is None:
        raise DraftReviewQueueValidationError(f"draft review queue validation failed: {field} must be date-time")


def _format_validation_error(error: ValidationError) -> str:
    path = _format_error_path(list(error.path))
    if error.validator == "enum":
        allowed = ", ".join(str(item) for item in error.validator_value)
        return f"{path} must be one of: {allowed}"
    if error.validator == "required":
        missing = str(error.message).split("'")[1] if "'" in str(error.message) else str(error.message)
        if path == "payload":
            return f"missing required field: {missing}"
        return f"{path} missing required field: {missing}"
    if error.validator == "additionalProperties":
        return f"{path} contains unknown field"
    return f"{path}: {error.message}"


def _format_error_path(path: list[Any]) -> str:
    if not path:
        return "payload"
    rendered = str(path[0])
    for part in path[1:]:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}"
    return rendered
