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
DRAFT_ID_PREFIXES = ("DD-", "DA-", "DR-", "DV-", "DACTION-")
AUTHORITATIVE_DRAFT_SET_STOP_REASONS = {
    "converged",
    "budget_exhausted",
    "risk_gate_triggered",
    "evidence_gap_blocked",
    "conflict_blocked",
    "user_review_required",
}


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
) -> dict[str, Any]:
    """Pure projection function for diagnostics and autopilot iteration."""
    project_state_copy = deepcopy(project_state)
    draft_set_copy = deepcopy(draft_set)
    project_head_at_generation = _project_head_at_generation(draft_set_copy)
    index = _build_index(project_state_copy, draft_set_copy)
    gap_diagnostics = detect_gap_diagnostics(
        project_state=project_state_copy,
        draft_set=draft_set_copy,
        index=index,
    )
    convergence = _projection_convergence(
        gap_diagnostics,
        draft_set=draft_set_copy,
        max_iterations=max_iterations,
    )
    projection = {
        "schema_version": 1,
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
        "gap_diagnostics": gap_diagnostics,
        "convergence": convergence,
    }
    validate_draft_projection(projection)
    return projection


def detect_gap_diagnostics(
    *,
    project_state: dict[str, Any],
    draft_set: dict[str, Any],
    index: dict[str, Any],
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
            gaps.append(
                _gap(
                    "missing_recommendation",
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
        if evidence_status in INSUFFICIENT_EVIDENCE_STATUSES:
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
        if (
            priority in {"P0", "P1"}
            and evidence_status == "partial"
            and _items(evidence, "missing")
            and not _has_evidence_collection_action(draft_set, draft_id)
        ):
            gaps.append(
                _gap(
                    "p0_p1_partial_evidence",
                    severity="medium",
                    scope="draft_decision",
                    target_id=draft_id,
                    target_kind="draft_decision",
                    blocks_convergence=False,
                    reason=f"{priority} draft decision {draft_id} has partial evidence with missing items.",
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
                    "action_without_verification",
                    severity="medium",
                    scope="draft_action",
                    target_id=action_id,
                    target_kind="draft_action",
                    blocks_convergence=False,
                    reason=f"Draft action {action_id} has no corresponding verification.",
                    suggested_resolution="Add a draft verification that targets this action.",
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
                    "verification_without_target",
                    severity="medium",
                    scope="draft_verification",
                    target_id=verification_id,
                    target_kind="draft_verification",
                    blocks_convergence=True,
                    reason=f"Draft verification {verification_id} has no target.",
                    suggested_resolution="Add target_ids that point to the action or decision being verified.",
                )
            )

    gaps.extend(_reference_gaps(draft_set, index=index))
    gaps.extend(_promotion_gaps(draft_set, index=index))
    gaps.extend(_coverage_gaps(draft_set))
    return _sort_and_number_gaps(gaps)


def validate_draft_projection(projection: dict[str, Any]) -> None:
    if not isinstance(projection, dict):
        raise DraftProjectionValidationError("draft projection validation failed: payload must be an object")
    errors = sorted(_schema_validator().iter_errors(projection), key=lambda error: list(error.path))
    if errors:
        raise DraftProjectionValidationError(
            f"draft projection validation failed: {_format_validation_error(errors[0])}"
        )


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
                    "accepted_conflict",
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


def _coverage_gaps(draft_set: dict[str, Any]) -> list[dict[str, Any]]:
    layers = {
        str(draft.get("layer"))
        for draft in _items(draft_set, "draft_decisions")
        if isinstance(draft, dict) and draft.get("layer")
    }
    gaps: list[dict[str, Any]] = []
    coverage_specs = {
        "purpose": (
            "missing_purpose_layer",
            "Draft set has no purpose-layer decision.",
            "Add a reviewable decision that states purpose and success criteria.",
        ),
        "constraint": (
            "missing_constraint_layer",
            "Draft set has no constraint-layer decision.",
            "Add a reviewable decision for source-of-truth or operating constraints.",
        ),
        "verification": (
            "missing_verification_layer",
            "Draft set has no verification-layer decision.",
            "Add a reviewable decision for validation and completion checks.",
        ),
        "review": (
            "missing_review_plan",
            "Draft set has no review-layer decision.",
            "Add a review plan decision for human approval and promotion boundaries.",
        ),
    }
    for layer in DECISION_STACK_LAYER_ORDER:
        if layer not in coverage_specs or layer in layers:
            continue
        gap_type, reason, resolution = coverage_specs[layer]
        gaps.append(
            _gap(
                gap_type,
                severity="medium",
                scope="draft_set",
                target_id=_draft_set_id(draft_set),
                target_kind="draft_set",
                blocks_convergence=False,
                blocks_bulk_promotion=False,
                reason=reason,
                suggested_resolution=resolution,
            )
        )
    return gaps


def _projection_convergence(
    gaps: list[dict[str, Any]],
    *,
    draft_set: dict[str, Any],
    max_iterations: int | None,
) -> dict[str, Any]:
    blocking = [gap for gap in gaps if gap["blocks_convergence"]]
    draft_convergence = _dict_field(draft_set, "convergence")
    draft_stop_reason = draft_convergence.get("stop_reason")
    if isinstance(draft_stop_reason, str) and draft_stop_reason in AUTHORITATIVE_DRAFT_SET_STOP_REASONS:
        stop_reason = draft_stop_reason
    else:
        stop_reason = _classify_projection_stop_reason(gaps)
    status = _projection_status(stop_reason)
    iterations = int(draft_convergence.get("iterations") or 0)
    iteration_budget = int(max_iterations) if max_iterations is not None else iterations
    return {
        "status": status,
        "stop_reason": stop_reason,
        "new_gap_count": len(gaps),
        "blocking_gap_count": len(blocking),
        "iterations": iterations,
        "max_iterations": iteration_budget,
        "explanation": _projection_explanation(stop_reason, len(gaps), len(blocking)),
    }


def _classify_projection_stop_reason(gaps: list[dict[str, Any]]) -> str:
    gap_types = {gap["type"] for gap in gaps}
    if "accepted_conflict" in gap_types:
        return "conflict_blocked"
    if "unsafe_bulk_review" in gap_types or "bulk_promotion_blocked" in gap_types:
        return "risk_gate_triggered"
    if any(gap["type"] == "insufficient_evidence" and gap["blocks_convergence"] for gap in gaps):
        return "evidence_gap_blocked"
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
        return "No gap diagnostics were detected for this draft projection."
    return f"Detected {gap_count} draft gap(s), including {blocking_gap_count} blocking gap(s)."


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
