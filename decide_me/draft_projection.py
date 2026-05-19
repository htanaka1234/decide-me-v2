from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from decide_me.constants import DECISION_STACK_LAYER_ORDER
from decide_me.draft_sets import draft_set_dir, load_draft_set
from decide_me.events import utc_now
from decide_me.store import _atomic_write_json, _write_lock, load_runtime, runtime_paths


DRAFT_PROJECTION_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "draft-projection.schema.json"
OPEN_DECISION_STATUSES = {"unresolved", "proposed", "blocked"}
ACCEPTED_DECISION_STATUSES = {"accepted", "resolved-by-evidence"}
EVIDENCE_STATUS_ALIASES = {
    "challenged": "challenged",
    "none": "none",
    "partial": "partial",
    "sufficient": "sufficient",
    "complete": "sufficient",
    "unknown": "unknown",
}
INSUFFICIENT_EVIDENCE_STATUSES = {"none", "challenged", "unknown"}
DRAFT_COLLECTIONS = {
    "draft_decisions": "draft_decision",
    "draft_assumptions": "draft_assumption",
    "draft_risks": "draft_risk",
    "draft_actions": "draft_action",
    "draft_verifications": "draft_verification",
}
SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}
PRIORITY_RANK = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
}
AXIS_TYPE_RANK = {
    "decision_stack_layer": 0,
    "evidence_coverage": 1,
    "human_review_safety": 2,
    "promotion_safety": 3,
}
DRAFT_ID_PREFIXES = ("DD-", "DA-", "DR-", "DV-", "DACTION-")


class DraftProjectionError(Exception):
    pass


class DraftProjectionValidationError(DraftProjectionError):
    pass


def build_draft_projection(
    ai_dir: str | Path,
    *,
    draft_set_id: str,
    now: str | None = None,
    persist: bool = True,
    max_iterations: int | None = None,
    convergence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load runtime + draft-set, build a derived draft projection, and optionally persist it."""
    paths = runtime_paths(ai_dir)
    generated_at = now or utc_now()
    with _write_lock(paths.lock_path):
        bundle = load_runtime(paths)
        draft_set = load_draft_set(paths.ai_dir, draft_set_id)
        current_project_head = _current_project_head(bundle["project_state"])
        projection = project_draft_set(
            project_state=bundle["project_state"],
            draft_set=draft_set,
            current_project_head=current_project_head,
            generated_at=generated_at,
            max_iterations=max_iterations,
            convergence_override=convergence_override,
        )
        validate_draft_projection(projection)
        if persist:
            _atomic_write_json(draft_projection_path(paths.ai_dir, draft_set_id), projection)
    return projection


def draft_projection_path(ai_dir: str | Path, draft_set_id: str) -> Path:
    return draft_set_dir(ai_dir, draft_set_id) / "draft-projection.json"


def project_draft_set(
    *,
    project_state: dict[str, Any],
    draft_set: dict[str, Any],
    current_project_head: str | None,
    generated_at: str,
    max_iterations: int | None = None,
    convergence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure projection function for diagnostics and autopilot iteration."""
    project_state_copy = deepcopy(project_state)
    draft_set_copy = deepcopy(draft_set)
    project_head_at_generation = _project_head_at_generation(draft_set_copy)
    index = _build_index(project_state_copy, draft_set_copy)
    coverage_matrix = build_coverage_matrix(
        draft_set_copy,
        current_project_head=current_project_head,
    )
    gap_diagnostics = detect_gap_diagnostics(
        project_state=project_state_copy,
        draft_set=draft_set_copy,
        index=index,
        coverage_matrix=coverage_matrix,
        current_project_head=current_project_head,
    )
    coverage_summary = _coverage_summary(coverage_matrix)
    frontier_queue = build_frontier_queue(
        coverage_matrix=coverage_matrix,
        gap_diagnostics=gap_diagnostics,
    )
    convergence = _projection_convergence(
        gap_diagnostics,
        coverage_matrix=coverage_matrix,
        max_iterations=max_iterations,
        convergence_override=convergence_override,
    )
    projection = {
        "schema_version": 3,
        "draft_set_id": _draft_set_id(draft_set_copy),
        "generated_at": generated_at,
        "project_head_at_generation": project_head_at_generation,
        "current_project_head": current_project_head,
        "stale": bool(
            project_head_at_generation is not None
            and current_project_head is not None
            and project_head_at_generation != current_project_head
        ),
        "canonical_summary": _canonical_summary(project_state_copy),
        "draft_summary": _draft_summary(draft_set_copy),
        "nodes": _projection_nodes(project_state_copy, draft_set_copy, index=index),
        "links": _projection_links(project_state_copy, draft_set_copy, index=index),
        "coverage_summary": coverage_summary,
        "coverage_matrix": coverage_matrix,
        "gap_diagnostics": gap_diagnostics,
        "frontier_queue": frontier_queue,
        "convergence": convergence,
    }
    validate_draft_projection(projection)
    return projection


def detect_gap_diagnostics(
    *,
    project_state: dict[str, Any],
    draft_set: dict[str, Any],
    index: dict[str, Any],
    coverage_matrix: list[dict[str, Any]] | None = None,
    current_project_head: str | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic sorted gap diagnostics."""
    gaps: list[dict[str, Any]] = []
    draft_decisions = _items(draft_set, "draft_decisions")
    if not draft_decisions:
        gaps.append(
            _gap(
                "no_draft_decisions",
                severity="high",
                scope="draft_set",
                target_id=_draft_set_id(draft_set),
                target_kind="draft_set",
                blocks_convergence=True,
                reason="Draft set has no draft decisions.",
                suggested_resolution="Add at least one reviewable draft decision before promotion review.",
            )
        )

    for draft_id in index["duplicate_draft_ids"]:
        gaps.append(
            _gap(
                "duplicate_draft_id",
                severity="high",
                scope="draft_set",
                target_id=draft_id,
                target_kind="draft_object",
                blocks_convergence=True,
                reason=f"Draft object id is duplicated: {draft_id}.",
                suggested_resolution="Make every draft object id unique within the draft set.",
            )
        )

    for draft in draft_decisions:
        if not isinstance(draft, dict):
            continue
        draft_id = _object_id(draft)
        priority = str(draft.get("priority") or "")
        if not _non_empty_string(draft.get("question")):
            gaps.append(
                _gap(
                    "missing_question",
                    severity="high",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=True,
                    reason=f"Draft decision {draft_id} has no question.",
                    suggested_resolution="Add a concrete decision question before review.",
                )
            )
        if priority in {"P0", "P1"} and not _non_empty_string(draft.get("recommendation")):
            gap_type = "missing_p0_recommendation" if priority == "P0" else "missing_p1_recommendation"
            gaps.append(
                _gap(
                    gap_type,
                    severity="high",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=True,
                    reason=f"{priority} draft decision has no recommendation.",
                    suggested_resolution=(
                        "Add a concrete recommendation or mark the item as a question for human review."
                    ),
                )
            )
        if not _items(draft, "alternatives"):
            p0_p1 = priority in {"P0", "P1"}
            gaps.append(
                _gap(
                    "missing_alternatives",
                    severity="high" if p0_p1 else "medium",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=p0_p1,
                    reason=f"Draft decision {draft_id} has no alternatives.",
                    suggested_resolution="Record at least one rejected option or tradeoff before review.",
                )
            )
        recipe = draft.get("promotion_recipe")
        if not isinstance(recipe, dict) or not recipe:
            gaps.append(
                _gap(
                    "missing_promotion_recipe",
                    severity="high",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=True,
                    reason=f"Draft decision {draft_id} has no promotion recipe.",
                    suggested_resolution="Add a promotion_recipe that starts canonical decisions as unresolved proposals.",
                )
            )
        evidence = _dict_field(draft, "evidence_coverage")
        evidence_status = _normalized_evidence_status(evidence.get("status"))
        if evidence_status == "challenged":
            blocks = priority in {"P0", "P1"}
            gaps.append(
                _gap(
                    "challenged_evidence",
                    severity="high",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=blocks,
                    reason=f"Draft decision {draft_id} evidence_coverage.status is challenged.",
                    suggested_resolution="Resolve challenged evidence or keep the decision in individual human review.",
                )
            )
        elif evidence_status in INSUFFICIENT_EVIDENCE_STATUSES:
            blocks = priority in {"P0", "P1"}
            if blocks or not _has_evidence_collection_action(draft_set, draft_id):
                gaps.append(
                    _gap(
                        "insufficient_evidence",
                        severity="high",
                        scope="draft_decision",
                        target_id=draft_id,
                        target_kind="draft_decision",
                        blocks_convergence=blocks,
                        reason=f"Draft decision {draft_id} evidence_coverage.status is {evidence_status}.",
                        suggested_resolution="Collect evidence or keep the decision in individual human review.",
                    )
                )
        if evidence_status == "partial" and (
            _items(evidence, "missing")
            or (
                not _string_items(evidence.get("supporting_object_ids"))
                and not _string_items(evidence.get("source_unit_ids"))
            )
        ) and not _has_evidence_collection_action(draft_set, draft_id):
            blocks = priority in {"P0", "P1"}
            gaps.append(
                _gap(
                    "unsupported_recommendation",
                    severity="high" if blocks else "medium",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=blocks,
                    reason=f"Draft decision {draft_id} has a recommendation with partial or incomplete supporting evidence.",
                    suggested_resolution="Add an evidence collection action or review the missing evidence explicitly.",
                )
            )
        for supporting_id in _string_items(evidence.get("supporting_object_ids")):
            if supporting_id not in index["canonical_object_ids"]:
                gaps.append(
                    _gap(
                        "dangling_supporting_object",
                        severity="high",
                        scope="draft_decision",
                        target_id=draft_id,
                        target_kind="draft_decision",
                        blocks_convergence=True,
                        reason=f"supporting_object_id {supporting_id} referenced by {draft_id} does not exist.",
                        suggested_resolution="Remove the dangling support reference or create/link the canonical object first.",
                    )
                )
        human_review = draft.get("human_review")
        if not isinstance(human_review, dict):
            gaps.append(
                _gap(
                    "missing_human_review",
                    severity="high",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=True,
                    reason=f"Draft decision {draft_id} has no human_review policy.",
                    suggested_resolution="Add human_review with required, mode, bulk_promotable, and reason fields.",
                )
            )
        else:
            risk_tier = str(draft.get("risk_tier") or "").lower()
            if risk_tier in {"high", "critical"} and human_review.get("mode") == "bulk":
                gaps.append(
                    _gap(
                        "unsafe_bulk_review",
                        severity="critical",
                        scope="draft_decision",
                        target_id=draft_id,
                        target_kind="draft_decision",
                        blocks_convergence=True,
                        reason=f"Draft decision {draft_id} is {risk_tier} risk but requests bulk review.",
                        suggested_resolution="Change high/critical risk items to individual review.",
                    )
                )
            if human_review.get("bulk_promotable") is True and _dict_field(draft, "promotion_recipe").get(
                "blocked_for_bulk_acceptance"
            ) is True:
                gaps.append(
                    _gap(
                        "bulk_promotion_blocked",
                        severity="high",
                        scope="draft_decision",
                        target_id=draft_id,
                        target_kind="draft_decision",
                        blocks_convergence=True,
                        reason=(
                            f"Draft decision {draft_id} is bulk_promotable but its promotion recipe blocks bulk acceptance."
                        ),
                        suggested_resolution="Use individual review or clear the bulk-promotable flag.",
                    )
                )

    for action in _items(draft_set, "draft_actions"):
        if not isinstance(action, dict):
            continue
        action_id = _object_id(action)
        if action_id and not _action_has_verification(action_id, draft_set):
            gaps.append(
                _gap(
                    "verification_without_observable_command",
                    severity="medium",
                    scope="draft_action",
                    target_id=action_id,
                    target_kind="draft_action",
                    blocks_convergence=False,
                    reason=f"Draft action {action_id} has no observable verification command.",
                    suggested_resolution="Add a draft verification that targets this action and records the command or observation.",
                )
            )

    for verification in _items(draft_set, "draft_verifications"):
        if not isinstance(verification, dict):
            continue
        verification_id = _object_id(verification)
        targets = _target_ids(verification)
        if not targets:
            gaps.append(
                _gap(
                    "verification_without_observable_command",
                    severity="medium",
                    scope="draft_verification",
                    target_id=verification_id,
                    target_kind="draft_verification",
                    blocks_convergence=True,
                    reason=f"Draft verification {verification_id} has no observable target or command.",
                    suggested_resolution="Add target_ids and an observable command or method for this verification.",
                )
            )

    gaps.extend(_reference_gaps(draft_set, index=index))
    gaps.extend(_promotion_gaps(draft_set, index=index))
    gaps.extend(_coverage_gap_diagnostics(coverage_matrix or []))
    return _sort_and_number_gaps(gaps)


def validate_draft_projection(projection: dict[str, Any]) -> None:
    if not isinstance(projection, dict):
        raise DraftProjectionValidationError("draft projection validation failed: payload must be an object")
    errors = sorted(_schema_validator().iter_errors(projection), key=lambda error: list(error.path))
    if errors:
        raise DraftProjectionValidationError(
            f"draft projection validation failed: {_format_validation_error(errors[0])}"
        )


def build_frontier_queue(
    *,
    coverage_matrix: list[dict[str, Any]],
    gap_diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive the next review/expansion frontier from blocking coverage diagnostics."""
    coverage_by_axis_id = {
        str(row.get("axis_id")): row
        for row in coverage_matrix
        if isinstance(row, dict) and _non_empty_string(row.get("axis_id"))
    }
    frontier: list[dict[str, Any]] = []
    for gap in gap_diagnostics:
        if not isinstance(gap, dict):
            continue
        if gap.get("target_kind") != "coverage_gap" or gap.get("blocks_convergence") is not True:
            continue
        gap_id = str(gap.get("id") or "")
        if not gap_id.startswith("GAP-"):
            continue
        row = coverage_by_axis_id.get(str(gap.get("target_id") or ""))
        if not _frontier_eligible_coverage_row(row):
            continue
        frontier.append(
            {
                "id": f"F-{gap_id}",
                "source_gap_id": gap_id,
                "topic": _frontier_topic(row),
                "priority": _target_priority(row),
                "status": "open",
                "evidence_needed": _frontier_evidence_needed(row),
                "suggested_expansion": _frontier_suggested_expansion(row, gap),
            }
        )
    return frontier


def _frontier_eligible_coverage_row(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and row.get("required") is True
        and row.get("priority") in {"P0", "P1"}
        and row.get("blocks_convergence") is True
    )


def _frontier_topic(row: dict[str, Any]) -> str:
    axis_type = str(row.get("axis_type") or "")
    value = str(row.get("value") or "")
    status = str(row.get("status") or "")
    if axis_type == "decision_stack_layer":
        return f"{value} layer is {status}"
    if axis_type == "evidence_coverage":
        return f"evidence coverage is {status}"
    if axis_type == "human_review_safety":
        return f"human review safety is {status}"
    if axis_type == "promotion_safety":
        return f"promotion safety target {value} is {status}"
    return f"{row.get('axis_id')} is {status}"


def _frontier_evidence_needed(row: dict[str, Any]) -> list[str]:
    if row.get("axis_type") != "evidence_coverage":
        return []
    return _string_items(row.get("remaining_gaps"))


def _frontier_suggested_expansion(row: dict[str, Any], gap: dict[str, Any]) -> str:
    axis_type = str(row.get("axis_type") or "")
    value = str(row.get("value") or "")
    if axis_type == "decision_stack_layer":
        return f"Add one complete {value}-layer draft decision before review."
    if axis_type == "evidence_coverage":
        return "Collect or review evidence for the coverage target before promotion review."
    if axis_type == "human_review_safety":
        return "Route unsafe or unclear review targets to individual human review."
    if axis_type == "promotion_safety":
        return "Resolve promotion safety before any promotion."
    return str(gap.get("suggested_resolution") or "Review the derived coverage gap before promotion.")


def _build_index(project_state: dict[str, Any], draft_set: dict[str, Any]) -> dict[str, Any]:
    canonical_objects = {
        str(obj.get("id")): obj
        for obj in _items(project_state, "objects")
        if isinstance(obj, dict) and _non_empty_string(obj.get("id"))
    }
    canonical_links = {
        str(link.get("id")): link
        for link in _items(project_state, "links")
        if isinstance(link, dict) and _non_empty_string(link.get("id"))
    }
    accepted_decision_ids = {
        object_id
        for object_id, obj in canonical_objects.items()
        if obj.get("type") == "decision" and obj.get("status") in ACCEPTED_DECISION_STATUSES
    }
    draft_ids_by_kind: dict[str, set[str]] = {kind: set() for kind in DRAFT_COLLECTIONS.values()}
    draft_id_counts: dict[str, int] = {}
    for field, kind in DRAFT_COLLECTIONS.items():
        for item in _items(draft_set, field):
            if not isinstance(item, dict):
                continue
            item_id = _object_id(item)
            if not item_id:
                continue
            draft_ids_by_kind[kind].add(item_id)
            draft_id_counts[item_id] = draft_id_counts.get(item_id, 0) + 1
    return {
        "canonical_objects": canonical_objects,
        "canonical_links": canonical_links,
        "canonical_object_ids": set(canonical_objects),
        "accepted_decision_ids": accepted_decision_ids,
        "draft_ids_by_kind": draft_ids_by_kind,
        "draft_object_ids": set(draft_id_counts),
        "duplicate_draft_ids": sorted(
            [draft_id for draft_id, count in draft_id_counts.items() if count > 1]
        ),
    }


def _canonical_summary(project_state: dict[str, Any]) -> dict[str, int]:
    objects = _items(project_state, "objects")
    links = _items(project_state, "links")
    return {
        "object_count": len(objects),
        "link_count": len(links),
        "accepted_decision_count": sum(
            1
            for obj in objects
            if isinstance(obj, dict) and obj.get("type") == "decision" and obj.get("status") in ACCEPTED_DECISION_STATUSES
        ),
        "open_decision_count": sum(
            1
            for obj in objects
            if isinstance(obj, dict) and obj.get("type") == "decision" and obj.get("status") in OPEN_DECISION_STATUSES
        ),
    }


def _draft_summary(draft_set: dict[str, Any]) -> dict[str, int]:
    promotion = _dict_field(draft_set, "promotion")
    return {
        "draft_decision_count": len(_items(draft_set, "draft_decisions")),
        "draft_assumption_count": len(_items(draft_set, "draft_assumptions")),
        "draft_risk_count": len(_items(draft_set, "draft_risks")),
        "draft_action_count": len(_items(draft_set, "draft_actions")),
        "draft_verification_count": len(_items(draft_set, "draft_verifications")),
        "promoted_decision_count": len(_string_items(promotion.get("promoted_decision_ids"))),
    }


def _projection_nodes(project_state: dict[str, Any], draft_set: dict[str, Any], *, index: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for obj in _items(project_state, "objects"):
        if not isinstance(obj, dict) or not _non_empty_string(obj.get("id")):
            continue
        metadata = _dict_field(obj, "metadata")
        nodes.append(
            {
                "node_id": f"canonical:{obj['id']}",
                "source": "canonical",
                "object_id": obj["id"],
                "object_type": str(obj.get("type") or "object"),
                "status": obj.get("status"),
                "priority": metadata.get("priority"),
                "risk_tier": metadata.get("risk_tier"),
                "layer": metadata.get("layer"),
            }
        )
    promoted_ids = set(_string_items(_dict_field(draft_set, "promotion").get("promoted_decision_ids")))
    for field, object_type in DRAFT_COLLECTIONS.items():
        for item in _items(draft_set, field):
            if not isinstance(item, dict) or not _non_empty_string(item.get("id")):
                continue
            node = {
                "node_id": f"draft:{item['id']}",
                "source": "draft",
                "object_id": item["id"],
                "object_type": object_type,
                "status": item.get("status"),
                "priority": item.get("priority"),
                "risk_tier": item.get("risk_tier"),
                "layer": item.get("layer"),
            }
            if object_type == "draft_decision":
                node["promoted"] = item["id"] in promoted_ids
            nodes.append(node)
    nodes.sort(key=lambda node: (node["source"], node["object_type"], node["object_id"]))
    return nodes


def _projection_links(project_state: dict[str, Any], draft_set: dict[str, Any], *, index: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for link in _items(project_state, "links"):
        if not isinstance(link, dict) or not _non_empty_string(link.get("id")):
            continue
        source_id = link.get("source_object_id")
        target_id = link.get("target_object_id")
        if not _non_empty_string(source_id) or not _non_empty_string(target_id):
            continue
        links.append(
            {
                "link_id": f"canonical:{link['id']}",
                "source": "canonical",
                "relation": str(link.get("relation") or "related"),
                "source_node_id": f"canonical:{source_id}",
                "target_node_id": f"canonical:{target_id}",
            }
        )
    for draft in _items(draft_set, "draft_decisions"):
        if not isinstance(draft, dict):
            continue
        draft_id = _object_id(draft)
        if not draft_id:
            continue
        for support_id in _string_items(_dict_field(draft, "evidence_coverage").get("supporting_object_ids")):
            if support_id in index["canonical_object_ids"]:
                links.append(
                    {
                        "link_id": f"draft:{support_id}-supports-{draft_id}",
                        "source": "draft",
                        "relation": "supports",
                        "source_node_id": f"canonical:{support_id}",
                        "target_node_id": f"draft:{draft_id}",
                    }
                )
    for action in _items(draft_set, "draft_actions"):
        if not isinstance(action, dict):
            continue
        action_id = _object_id(action)
        for target_id in _target_ids(action):
            if target_id in index["draft_object_ids"]:
                links.append(
                    {
                        "link_id": f"draft:{action_id}-addresses-{target_id}",
                        "source": "draft",
                        "relation": "addresses",
                        "source_node_id": f"draft:{action_id}",
                        "target_node_id": f"draft:{target_id}",
                    }
                )
    for verification in _items(draft_set, "draft_verifications"):
        if not isinstance(verification, dict):
            continue
        verification_id = _object_id(verification)
        for target_id in _target_ids(verification):
            if target_id in index["draft_object_ids"]:
                links.append(
                    {
                        "link_id": f"draft:{verification_id}-verifies-{target_id}",
                        "source": "draft",
                        "relation": "verifies",
                        "source_node_id": f"draft:{verification_id}",
                        "target_node_id": f"draft:{target_id}",
                    }
                )
    links.sort(key=lambda link: (link["source"], link["relation"], link["link_id"]))
    return links


def _reference_gaps(draft_set: dict[str, Any], *, index: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    conflicts = _items(draft_set, "conflicts")
    for conflict_index, conflict in enumerate(conflicts, start=1):
        refs = _referenced_strings(conflict)
        accepted = sorted(set(refs) & index["accepted_decision_ids"])
        draft_refs = sorted(ref for ref in refs if _looks_like_draft_id(ref))
        related_draft_ids = [ref for ref in draft_refs if ref in index["draft_object_ids"]]
        target_id = related_draft_ids[0] if related_draft_ids else accepted[0] if accepted else f"conflict[{conflict_index}]"
        for accepted_id in accepted:
            gaps.append(
                _gap(
                    "accepted_decision_conflict_possible",
                    severity="critical",
                    scope="conflict",
                    target_id=target_id,
                    target_kind="draft_conflict",
                    blocks_convergence=True,
                    reason=f"Draft conflict references accepted canonical decision {accepted_id}.",
                    suggested_resolution="Resolve the conflict against the accepted decision before drafting can converge.",
                )
            )
        for ref in draft_refs:
            if ref not in index["draft_object_ids"]:
                gaps.append(
                    _gap(
                        "dangling_draft_reference",
                        severity="high",
                        scope="conflict",
                        target_id=ref,
                        target_kind="draft_reference",
                        blocks_convergence=True,
                        reason=f"Conflict references missing draft object {ref}.",
                        suggested_resolution="Remove the dangling draft reference or add the referenced draft object.",
                    )
                )

    for field in ("draft_actions", "draft_verifications"):
        for item in _items(draft_set, field):
            if not isinstance(item, dict):
                continue
            item_id = _object_id(item)
            for ref in _target_ids(item):
                if _looks_like_draft_id(ref) and ref not in index["draft_object_ids"]:
                    gaps.append(
                        _gap(
                            "dangling_draft_reference",
                            severity="high",
                            scope=field[:-1],
                            target_id=item_id or ref,
                            target_kind=field[:-1],
                            blocks_convergence=True,
                            reason=f"{item_id or field} references missing draft object {ref}.",
                            suggested_resolution="Remove the dangling draft reference or add the referenced draft object.",
                        )
                    )
    return gaps


def _coverage_gap_diagnostics(coverage_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for row in coverage_matrix:
        if row.get("blocks_convergence") is not True:
            continue
        gap_type = _coverage_gap_type(row)
        gaps.append(
            _gap(
                gap_type,
                severity="high" if row.get("priority") in {"P0", "P1"} else "medium",
                scope="coverage",
                target_id=str(row.get("axis_id") or ""),
                target_kind="coverage_gap",
                blocks_convergence=True,
                reason=_coverage_gap_reason(row),
                suggested_resolution=_coverage_gap_resolution(row),
                blocks_bulk_promotion=True,
            )
        )
    return gaps


def _coverage_gap_type(row: dict[str, Any]) -> str:
    axis_type = str(row.get("axis_type") or "")
    value = str(row.get("value") or "")
    observed = str(row.get("observed_value") or "")
    if axis_type == "decision_stack_layer":
        return "missing_required_layer"
    if axis_type == "evidence_coverage":
        return "challenged_evidence" if observed == "challenged" else "insufficient_evidence"
    if axis_type == "human_review_safety":
        return "unsafe_bulk_review"
    if axis_type == "promotion_safety":
        if value == "accepted_forbidden":
            return "accepted_decision_conflict_possible"
        if value == "stale_warning":
            return "stale_draft_set"
    return "unsupported_recommendation"


def _coverage_gap_reason(row: dict[str, Any]) -> str:
    remaining_gaps = _string_items(row.get("remaining_gaps"))
    if remaining_gaps:
        return "; ".join(remaining_gaps)
    return (
        f"Coverage target {row.get('axis_id')} is {row.get('status')} "
        f"(target={row.get('value')}, observed={row.get('observed_value')})."
    )


def _coverage_gap_resolution(row: dict[str, Any]) -> str:
    if row.get("axis_type") == "decision_stack_layer":
        return f"Add one complete {row.get('value')}-layer draft decision before review."
    if row.get("axis_type") == "evidence_coverage":
        return "Collect or review supporting evidence before bulk promotion."
    if row.get("axis_type") == "human_review_safety":
        return "Route unsafe or unclear review targets to individual human review."
    if row.get("axis_type") == "promotion_safety":
        return "Resolve promotion safety before any bulk materialization."
    return "Review the derived coverage gap before promotion."


def _promotion_gaps(draft_set: dict[str, Any], *, index: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    draft_set_id = _draft_set_id(draft_set)
    for draft_id in _string_items(_dict_field(draft_set, "promotion").get("promoted_decision_ids")):
        if not _canonical_draft_origin_exists(index["canonical_objects"].values(), draft_set_id, draft_id):
            gaps.append(
                _gap(
                    "promoted_but_missing_canonical",
                    severity="high",
                    scope="promotion",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=True,
                    reason=f"Draft decision {draft_id} is marked promoted but no canonical decision has matching draft_origin.",
                    suggested_resolution="Inspect promotion-log.jsonl and canonical state before further promotion.",
                )
            )
    return gaps


def build_coverage_matrix(
    draft_set: dict[str, Any],
    *,
    current_project_head: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_axis_ids: set[str] = set()
    targets = _coverage_targets(draft_set)
    _reject_duplicate_coverage_target_axis_ids(targets)
    for target in targets:
        axis_id = str(target.get("axis_id") or "")
        if not axis_id or axis_id in seen_axis_ids:
            continue
        seen_axis_ids.add(axis_id)
        axis_type = str(target.get("axis_type") or "")
        if axis_type == "decision_stack_layer":
            rows.append(_decision_stack_layer_coverage_row(draft_set, target))
        elif axis_type == "evidence_coverage":
            rows.append(_evidence_coverage_row(draft_set, target=target))
        elif axis_type == "human_review_safety":
            rows.append(_human_review_safety_row(draft_set, target=target))
        elif axis_type == "promotion_safety":
            rows.append(
                _promotion_safety_row(
                    draft_set,
                    current_project_head=current_project_head,
                    target=target,
                )
            )

    for row in _derived_safety_rows(draft_set, current_project_head=current_project_head):
        if row["axis_id"] not in seen_axis_ids:
            rows.append(row)
            seen_axis_ids.add(row["axis_id"])

    rows.sort(
        key=lambda row: (
            AXIS_TYPE_RANK.get(str(row.get("axis_type")), 99),
            PRIORITY_RANK.get(str(row.get("priority")), 99),
            str(row.get("axis_id") or ""),
        )
    )
    return rows


def _coverage_targets(draft_set: dict[str, Any]) -> list[dict[str, Any]]:
    contract = _dict_field(draft_set, "exploration_contract")
    return [target for target in _items(contract, "coverage_targets") if isinstance(target, dict)]


def _reject_duplicate_coverage_target_axis_ids(targets: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for target in targets:
        axis_id = str(target.get("axis_id") or "")
        if not axis_id:
            continue
        if axis_id in seen:
            raise DraftProjectionValidationError(f"duplicate coverage target axis_id: {axis_id}")
        seen.add(axis_id)


def _decision_stack_layer_coverage_row(draft_set: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    layer = str(target.get("value") or "")
    matching = [
        draft
        for draft in _items(draft_set, "draft_decisions")
        if isinstance(draft, dict) and str(draft.get("layer") or "") == layer
    ]
    complete = [draft for draft in matching if _draft_decision_covers_layer(draft)]
    matching_ids = _draft_ids(matching)
    complete_ids = _draft_ids(complete)
    if complete_ids:
        return _coverage_row(target, observed_value="complete", status="covered", covered_by=complete_ids)
    if matching_ids:
        return _coverage_row(
            target,
            observed_value="incomplete",
            status="partial",
            covered_by=matching_ids,
            remaining_gaps=[f"No complete {layer}-layer draft decision exists."],
        )
    return _coverage_row(
        target,
        observed_value="missing",
        status="missing",
        remaining_gaps=[f"No {layer}-layer draft decision exists."],
    )


def _draft_decision_covers_layer(draft: dict[str, Any]) -> bool:
    return (
        _non_empty_string(draft.get("question"))
        and _non_empty_string(draft.get("recommendation"))
        and _non_empty_string(draft.get("rationale"))
    )


def _derived_safety_rows(draft_set: dict[str, Any], *, current_project_head: str | None) -> list[dict[str, Any]]:
    return [
        _evidence_coverage_row(
            draft_set,
            target={
                "axis_id": "core.evidence.coverage",
                "axis_type": "evidence_coverage",
                "value": "sufficient",
                "priority": "P2",
                "required": False,
            },
        ),
        _human_review_safety_row(
            draft_set,
            target={
                "axis_id": "core.human_review.safety",
                "axis_type": "human_review_safety",
                "value": "individual_required",
                "priority": "P2",
                "required": False,
            },
        ),
        _promotion_safety_row(
            draft_set,
            current_project_head=current_project_head,
            target={
                "axis_id": "core.promotion.proposal_required",
                "axis_type": "promotion_safety",
                "value": "proposal_required",
                "priority": "P2",
                "required": False,
            },
        ),
        _promotion_safety_row(
            draft_set,
            current_project_head=current_project_head,
            target={
                "axis_id": "core.promotion.accepted_forbidden",
                "axis_type": "promotion_safety",
                "value": "accepted_forbidden",
                "priority": "P2",
                "required": False,
            },
        ),
        _promotion_safety_row(
            draft_set,
            current_project_head=current_project_head,
            target={
                "axis_id": "core.promotion.stale_warning",
                "axis_type": "promotion_safety",
                "value": "stale_warning",
                "priority": "P2",
                "required": False,
            },
        ),
    ]


def _evidence_coverage_row(draft_set: dict[str, Any], *, target: dict[str, Any]) -> dict[str, Any]:
    problem_ids: list[str] = []
    partial_ids: list[str] = []
    covered_ids: list[str] = []
    problem_priorities: list[str] = []
    worst_status = "sufficient"
    for draft in _items(draft_set, "draft_decisions"):
        if not isinstance(draft, dict):
            continue
        draft_id = _object_id(draft)
        priority = _priority(draft)
        evidence = _dict_field(draft, "evidence_coverage")
        evidence_status = _normalized_evidence_status(evidence.get("status")) or "unknown"
        worst_status = _worst_evidence_status(worst_status, evidence_status)
        if evidence_status in INSUFFICIENT_EVIDENCE_STATUSES:
            if draft_id:
                problem_ids.append(draft_id)
            problem_priorities.append(priority)
        elif evidence_status == "partial" and _items(evidence, "missing"):
            if draft_id:
                partial_ids.append(draft_id)
            problem_priorities.append(priority)
        elif draft_id:
            covered_ids.append(draft_id)

    status = _evidence_target_status(str(target.get("value") or ""), worst_status)
    effective_target = target
    if problem_priorities:
        effective_target = _coverage_target_with_safety(
            target,
            priority=_highest_priority(problem_priorities),
            required=_has_p0_p1(problem_priorities),
        )
    if status != "covered":
        if problem_ids:
            remaining_gaps = [f"Missing, challenged, or unknown evidence coverage: {', '.join(problem_ids)}."]
        elif partial_ids:
            remaining_gaps = [f"Partial evidence does not satisfy required evidence target: {', '.join(partial_ids)}."]
        else:
            remaining_gaps = [
                f"Observed evidence coverage is {worst_status}; target is {target.get('value')}.",
            ]
        return _coverage_row(
            effective_target,
            observed_value=worst_status,
            status=status,
            covered_by=covered_ids + partial_ids,
            remaining_gaps=remaining_gaps,
        )
    return _coverage_row(
        target,
        observed_value=worst_status,
        status="covered",
        covered_by=covered_ids + partial_ids,
    )


def _human_review_safety_row(draft_set: dict[str, Any], *, target: dict[str, Any]) -> dict[str, Any]:
    unsafe_ids: list[str] = []
    individual_needed_ids: list[str] = []
    covered_ids: list[str] = []
    priorities: list[str] = []
    for draft in _items(draft_set, "draft_decisions"):
        if not isinstance(draft, dict):
            continue
        draft_id = _object_id(draft)
        priority = _priority(draft)
        risk_tier = str(draft.get("risk_tier") or "").lower()
        human_review = _dict_field(draft, "human_review")
        bulk_requested = human_review.get("mode") == "bulk" or human_review.get("bulk_promotable") is True
        if risk_tier in {"high", "critical"} and bulk_requested:
            if draft_id:
                unsafe_ids.append(draft_id)
            priorities.append("P0")
        elif priority in {"P0", "P1"} and bulk_requested and human_review.get("required") is not True:
            if draft_id:
                individual_needed_ids.append(draft_id)
            priorities.append(priority)
        elif draft_id:
            covered_ids.append(draft_id)

    if unsafe_ids:
        return _coverage_row(
            _coverage_target_with_safety(target, priority="P0", required=True),
            observed_value="blocked",
            status=_human_review_target_status(str(target.get("value") or ""), "blocked"),
            covered_by=covered_ids,
            remaining_gaps=[f"Unsafe bulk review requested for high/critical risk draft decisions: {', '.join(unsafe_ids)}."],
        )
    if individual_needed_ids:
        observed_value = "bulk_allowed"
        return _coverage_row(
            _coverage_target_with_safety(
                target,
                priority=_highest_priority(priorities),
                required=True,
            ),
            observed_value=observed_value,
            status=_human_review_target_status(str(target.get("value") or ""), observed_value),
            covered_by=covered_ids,
            remaining_gaps=[f"P0/P1 draft decisions require individual review: {', '.join(individual_needed_ids)}."],
        )
    observed_value = "individual_required" if any(
        isinstance(draft, dict) and _dict_field(draft, "human_review").get("required") is True
        for draft in _items(draft_set, "draft_decisions")
    ) else "bulk_allowed"
    status = _human_review_target_status(str(target.get("value") or ""), observed_value)
    remaining_gaps = []
    if status != "covered":
        remaining_gaps = [
            f"Observed human review safety is {observed_value}; target is {target.get('value')}.",
        ]
    return _coverage_row(
        target,
        observed_value=observed_value,
        status=status,
        covered_by=covered_ids,
        remaining_gaps=remaining_gaps,
    )


def _promotion_safety_row(
    draft_set: dict[str, Any],
    *,
    current_project_head: str | None,
    target: dict[str, Any],
) -> dict[str, Any]:
    value = str(target.get("value") or "")
    value_key = value.replace(" ", "_").replace("-", "_")
    if value_key == "accepted_forbidden":
        accepted_ids = [
            _object_id(draft) or "unknown"
            for draft in _items(draft_set, "draft_decisions")
            if isinstance(draft, dict)
            and (
                draft.get("status") == "accepted"
                or _dict_field(draft, "promotion_recipe").get("canonical_initial_status") == "accepted"
            )
        ]
        if accepted_ids:
            return _coverage_row(
                _coverage_target_with_safety(target, priority="P0", required=True),
                observed_value="accepted_present",
                status="missing",
                remaining_gaps=[f"Draft decisions must not start or appear accepted: {', '.join(accepted_ids)}."],
            )
        return _coverage_row(
            target,
            observed_value="accepted_forbidden",
            status="covered",
            covered_by=_draft_ids(_items(draft_set, "draft_decisions")),
        )
    if value_key == "stale_warning":
        generated_head = _project_head_at_generation(draft_set)
        stale = generated_head is not None and current_project_head is not None and generated_head != current_project_head
        if stale:
            return _coverage_row(
                _coverage_target_with_safety(target, priority="P1", required=True),
                observed_value="stale",
                status="partial",
                remaining_gaps=[f"Draft set is stale: generated at {generated_head}, current is {current_project_head}."],
            )
        return _coverage_row(target, observed_value="fresh", status="covered")

    bad_ids = [
        _object_id(draft) or "unknown"
        for draft in _items(draft_set, "draft_decisions")
        if isinstance(draft, dict) and _dict_field(draft, "promotion_recipe").get("proposal_required") is not True
    ]
    if bad_ids:
        return _coverage_row(
            _coverage_target_with_safety(target, priority="P0", required=True),
            observed_value="proposal_missing",
            status="missing",
            remaining_gaps=[f"Promotion must require proposal review before acceptance: {', '.join(bad_ids)}."],
        )
    return _coverage_row(
        target,
        observed_value="proposal_required",
        status="covered",
        covered_by=_draft_ids(_items(draft_set, "draft_decisions")),
    )


def _coverage_row(
    target: dict[str, Any],
    *,
    observed_value: str,
    status: str,
    covered_by: list[str] | None = None,
    remaining_gaps: list[str] | None = None,
) -> dict[str, Any]:
    priority = _target_priority(target)
    required = bool(target.get("required"))
    return {
        "axis_id": str(target.get("axis_id") or ""),
        "axis_type": str(target.get("axis_type") or ""),
        "value": str(target.get("value") or ""),
        "observed_value": observed_value,
        "priority": priority,
        "required": required,
        "status": status,
        "covered_by": _unique(covered_by or []),
        "remaining_gaps": _unique(remaining_gaps or []),
        "blocks_convergence": required and priority in {"P0", "P1"} and status != "covered",
    }


def _coverage_target_with_safety(
    target: dict[str, Any],
    *,
    priority: str | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    updated = dict(target)
    if priority is not None:
        updated["priority"] = priority
    if required is not None:
        updated["required"] = required
    return updated


def _evidence_target_status(target_value: str, observed_value: str) -> str:
    if target_value == "sufficient":
        if observed_value == "sufficient":
            return "covered"
        return "partial" if observed_value == "partial" else "missing"
    if target_value == "partial":
        return "covered" if observed_value in {"partial", "sufficient"} else "missing"
    return "covered" if observed_value == target_value else "partial"


def _human_review_target_status(target_value: str, observed_value: str) -> str:
    if target_value == "bulk_allowed":
        return "covered" if observed_value == "bulk_allowed" else "partial"
    return "covered" if observed_value == target_value else "missing"


def _coverage_summary(coverage_matrix: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "required_target_count": sum(1 for row in coverage_matrix if row.get("required") is True),
        "covered_count": sum(1 for row in coverage_matrix if row.get("status") == "covered"),
        "partial_count": sum(1 for row in coverage_matrix if row.get("status") == "partial"),
        "missing_count": sum(1 for row in coverage_matrix if row.get("status") == "missing"),
        "blocking_gap_count": sum(1 for row in coverage_matrix if row.get("blocks_convergence") is True),
    }


def _draft_ids(items: list[Any]) -> list[str]:
    ids = []
    for item in items:
        if isinstance(item, dict):
            item_id = _object_id(item)
            if item_id:
                ids.append(item_id)
    return _unique(ids)


def _priority(draft: dict[str, Any]) -> str:
    value = draft.get("priority")
    return value if isinstance(value, str) and value in PRIORITY_RANK else "P3"


def _target_priority(target: dict[str, Any]) -> str:
    value = target.get("priority")
    return value if isinstance(value, str) and value in PRIORITY_RANK else "P3"


def _highest_priority(priorities: list[str]) -> str:
    valid = [priority for priority in priorities if priority in PRIORITY_RANK]
    if not valid:
        return "P2"
    return min(valid, key=lambda priority: PRIORITY_RANK[priority])


def _has_p0_p1(priorities: list[str]) -> bool:
    return any(priority in {"P0", "P1"} for priority in priorities)


def _worst_evidence_status(left: str, right: str) -> str:
    rank = {"challenged": 0, "none": 1, "unknown": 2, "partial": 3, "sufficient": 4}
    return left if rank.get(left, 99) <= rank.get(right, 99) else right


def _projection_convergence(
    gaps: list[dict[str, Any]],
    *,
    coverage_matrix: list[dict[str, Any]],
    max_iterations: int | None,
    convergence_override: dict[str, Any] | None,
) -> dict[str, Any]:
    blocking_gaps = [gap for gap in gaps if gap["blocks_convergence"]]
    coverage_problem_count = sum(
        1 for row in coverage_matrix if row.get("status") != "covered" and row.get("blocks_convergence") is not True
    )
    coverage_blockers = [row for row in coverage_matrix if row.get("blocks_convergence") is True]
    if blocking_gaps or coverage_blockers or not isinstance(convergence_override, dict):
        stop_reason = _classify_projection_stop_reason(gaps, coverage_blockers=coverage_blockers)
    else:
        override_stop_reason = convergence_override.get("stop_reason")
        stop_reason = (
            override_stop_reason
            if isinstance(override_stop_reason, str)
            else _classify_projection_stop_reason(gaps, coverage_blockers=coverage_blockers)
        )
    status = _projection_status(stop_reason)
    iterations = _non_negative_int(convergence_override.get("iterations") if isinstance(convergence_override, dict) else None)
    iteration_budget = int(max_iterations) if max_iterations is not None else iterations
    convergence = {
        "status": status,
        "stop_reason": stop_reason,
        "new_gap_count": len(gaps) + coverage_problem_count,
        "blocking_gap_count": len(blocking_gaps),
        "iterations": iterations,
        "max_iterations": iteration_budget,
        "explanation": _projection_explanation(
            stop_reason,
            len(gaps) + coverage_problem_count,
            len(blocking_gaps),
        ),
    }
    if isinstance(convergence_override, dict) and not blocking_gaps and not coverage_blockers:
        explanation = convergence_override.get("explanation")
        if isinstance(explanation, str):
            convergence["explanation"] = explanation
        trace = convergence_override.get("trace")
        if isinstance(trace, list):
            convergence["trace"] = trace
    return convergence


def _classify_projection_stop_reason(gaps: list[dict[str, Any]], *, coverage_blockers: list[dict[str, Any]]) -> str:
    gap_types = {gap["type"] for gap in gaps}
    if "accepted_decision_conflict_possible" in gap_types:
        return "conflict_blocked"
    if any(
        gap["type"] in {"unsafe_bulk_review", "bulk_promotion_blocked"}
        and gap.get("target_kind") == "draft_decision"
        and gap.get("blocks_convergence") is True
        for gap in gaps
    ):
        return "risk_gate_triggered"
    if any(gap["type"] in {"insufficient_evidence", "challenged_evidence"} and gap["blocks_convergence"] for gap in gaps):
        return "evidence_gap_blocked"
    if "unsafe_bulk_review" in gap_types or "bulk_promotion_blocked" in gap_types:
        return "risk_gate_triggered"
    if coverage_blockers:
        return "user_review_required"
    if any(gap["blocks_convergence"] for gap in gaps):
        return "user_review_required"
    if gaps:
        return "stopped"
    return "converged"


def _projection_status(stop_reason: str) -> str:
    if stop_reason == "converged":
        return "converged"
    if stop_reason == "budget_exhausted":
        return "budget_exhausted"
    if stop_reason in {"conflict_blocked", "risk_gate_triggered", "evidence_gap_blocked", "user_review_required"}:
        return "blocked"
    return "stopped"


def _projection_explanation(stop_reason: str, gap_count: int, blocking_gap_count: int) -> str:
    if stop_reason == "converged":
        if gap_count:
            return "No blocking gap diagnostics were detected for this draft projection."
        return "No gap diagnostics were detected for this draft projection."
    return f"Detected {gap_count} draft gap(s), including {blocking_gap_count} blocking gap(s)."


def _non_negative_int(value: Any) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _gap(
    gap_type: str,
    *,
    severity: str,
    scope: str,
    target_id: str | None,
    target_kind: str,
    blocks_convergence: bool,
    reason: str,
    suggested_resolution: str,
    blocks_bulk_promotion: bool | None = None,
    suggested_draft_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "GAP-000",
        "type": gap_type,
        "severity": severity,
        "scope": scope,
        "target_id": target_id,
        "target_kind": target_kind,
        "blocks_convergence": blocks_convergence,
        "blocks_bulk_promotion": blocks_bulk_promotion if blocks_bulk_promotion is not None else severity in {"high", "critical"},
        "reason": reason,
        "suggested_resolution": suggested_resolution,
        "suggested_draft_decision": suggested_draft_decision,
    }


def _sort_and_number_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_gaps = sorted(
        gaps,
        key=lambda gap: (
            SEVERITY_RANK.get(str(gap.get("severity")), 99),
            str(gap.get("type") or ""),
            str(gap.get("target_kind") or ""),
            str(gap.get("target_id") or ""),
            str(gap.get("reason") or ""),
        ),
    )
    for index, gap in enumerate(sorted_gaps, start=1):
        gap["id"] = f"GAP-{index:03d}"
    return sorted_gaps


def _has_evidence_collection_action(draft_set: dict[str, Any], draft_id: str | None) -> bool:
    if not draft_id:
        return False
    for action in _items(draft_set, "draft_actions"):
        if not isinstance(action, dict):
            continue
        if draft_id in _target_ids(action) and str(action.get("purpose") or action.get("kind") or "").lower() in {
            "evidence",
            "evidence_collection",
        }:
            return True
        statement = str(action.get("statement") or action.get("summary") or "")
        if draft_id in _target_ids(action) and "evidence" in statement.lower():
            return True
    return False


def _action_has_verification(action_id: str, draft_set: dict[str, Any]) -> bool:
    for verification in _items(draft_set, "draft_verifications"):
        if isinstance(verification, dict) and action_id in _target_ids(verification):
            return True
    return False


def _target_ids(item: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "target_ids",
        "linked_decisions",
        "linked_decision_ids",
        "draft_decision_ids",
        "verification_refs",
        "verification_ids",
        "verifies",
    ):
        value = item.get(key)
        if isinstance(value, list):
            refs.extend(_string_items(value))
        elif isinstance(value, str) and value.strip():
            refs.append(value.strip())
    return _unique(refs)


def _referenced_strings(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            refs.append(stripped)
    elif isinstance(value, dict):
        for item in value.values():
            refs.extend(_referenced_strings(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_referenced_strings(item))
    return _unique(refs)


def _canonical_draft_origin_exists(objects: Any, draft_set_id: str, draft_id: str) -> bool:
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("type") != "decision":
            continue
        origin = _dict_field(_dict_field(obj, "metadata"), "draft_origin")
        if origin.get("draft_set_id") == draft_set_id and origin.get("draft_decision_id") == draft_id:
            return True
    return False


def _current_project_head(project_state: dict[str, Any]) -> str | None:
    value = _dict_field(project_state, "state").get("project_head")
    return value if isinstance(value, str) and value else None


def _project_head_at_generation(draft_set: dict[str, Any]) -> str | None:
    value = _dict_field(draft_set, "source_context").get("project_head_at_generation")
    return value if isinstance(value, str) and value else None


def _draft_set_id(draft_set: dict[str, Any]) -> str:
    value = draft_set.get("id")
    return value if isinstance(value, str) and value else "DS-19700101-000"


def _object_id(item: dict[str, Any]) -> str | None:
    value = item.get("id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _looks_like_draft_id(value: str) -> bool:
    return value.startswith(DRAFT_ID_PREFIXES)


def _normalized_evidence_status(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return EVIDENCE_STATUS_ALIASES.get(value.lower())


def _items(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    return item if isinstance(item, list) else []


def _dict_field(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    return item if isinstance(item, dict) else {}


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema = json.loads(DRAFT_PROJECTION_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


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
