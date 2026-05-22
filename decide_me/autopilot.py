from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.draft_export import export_draft_set
from decide_me.draft_projection import build_draft_projection, project_draft_set
from decide_me.draft_sets import DRAFT_SET_SCHEMA_VERSION, create_draft_set, default_exploration_contract
from decide_me.domains import DomainPackLoadError, DomainRegistry, load_domain_registry
from decide_me.domains.registry import GENERIC_PACK_ID
from decide_me.events import utc_now
from decide_me.store import load_runtime, runtime_paths


STOP_REASON_STATUS = {
    "converged": "converged",
    "budget_exhausted": "budget_exhausted",
    "risk_gate_triggered": "blocked",
    "evidence_gap_blocked": "blocked",
    "conflict_blocked": "blocked",
    "user_review_required": "blocked",
}
AUTO_REMEDIABLE_GAP_TYPES = {
    "verification_without_observable_command",
    "missing_purpose_layer",
    "missing_constraint_layer",
    "missing_verification_layer",
    "missing_review_plan",
    "missing_required_layer",
    "no_draft_decisions",
    "unsupported_recommendation",
}
VALID_RISK_THRESHOLDS = {"low", "medium", "high", "critical"}
HARD_STOP_RISK_GAP_TYPES = {"unsafe_bulk_review", "bulk_promotion_blocked"}
HARD_STOP_REVIEW_GAP_TYPES = {"stale_draft_set"}
HARD_STOP_SAFETY_AXIS_TYPES = {"human_review_safety", "promotion_safety"}
LAYER_COVERAGE_SPECS = {
    "purpose": {
        "id": "DD-GAP-PURPOSE",
        "layer": "purpose",
        "priority": "P1",
        "question": "What purpose and success criteria should this draft set optimize for?",
        "recommendation": "Review and record the goal, success criteria, and explicit non-goals before promotion.",
        "rationale": "A purpose layer keeps later draft decisions tied to an inspectable outcome.",
        "alternative": "Skip purpose review",
        "reason_not_recommended": "Reviewers may promote decisions without a shared definition of success.",
    },
    "principle": {
        "id": "DD-GAP-PRINCIPLE",
        "layer": "principle",
        "priority": "P1",
        "question": "Which decision principles should guide this draft set?",
        "recommendation": "Record the principles that constrain future tradeoffs before promotion.",
        "rationale": "A principle layer keeps later choices consistent when reviewers compare alternatives.",
        "alternative": "Let each draft decision define principles independently",
        "reason_not_recommended": "Reviewers would not have a stable policy for resolving tradeoffs.",
    },
    "constraint": {
        "id": "DD-GAP-CONSTRAINT",
        "layer": "constraint",
        "priority": "P1",
        "question": "Which source-of-truth and safety constraints must this draft set preserve?",
        "recommendation": "Keep drafting in sidecar artifacts and reserve canonical events for explicit promotion.",
        "rationale": "The draft flow must not make recommendations look like accepted runtime state.",
        "alternative": "Let drafting write canonical decisions directly",
        "reason_not_recommended": "That would bypass review and blur the source-of-truth boundary.",
    },
    "strategy": {
        "id": "DD-GAP-STRATEGY",
        "layer": "strategy",
        "priority": "P1",
        "question": "What exploration strategy should this draft set follow?",
        "recommendation": "Prefer explicit coverage of required layers before expanding lower-priority draft details.",
        "rationale": "A strategy layer prevents deterministic drafting from converging on a narrow or accidental slice.",
        "alternative": "Expand whichever draft detail appears first",
        "reason_not_recommended": "Important required coverage gaps could remain hidden until promotion review.",
    },
    "design": {
        "id": "DD-GAP-DESIGN",
        "layer": "design",
        "priority": "P1",
        "question": "What design shape should reviewers evaluate before promotion?",
        "recommendation": "Describe the intended runtime and artifact boundaries before creating canonical proposals.",
        "rationale": "A design layer makes implementation implications inspectable without mutating canonical state.",
        "alternative": "Let implementation details emerge only during promotion",
        "reason_not_recommended": "Promotion reviewers would need to infer design intent from incomplete draft text.",
    },
    "execution": {
        "id": "DD-GAP-EXECUTION",
        "layer": "execution",
        "priority": "P1",
        "question": "What execution steps should follow from this draft set?",
        "recommendation": "Record the minimal follow-through actions needed after human review accepts the direction.",
        "rationale": "An execution layer turns review output into concrete next steps without treating them as already done.",
        "alternative": "Promote decisions without execution implications",
        "reason_not_recommended": "Accepted decisions could lack an actionable path to implementation.",
    },
    "verification": {
        "id": "DD-GAP-VERIFICATION",
        "layer": "verification",
        "priority": "P1",
        "question": "What verification criteria should reviewers apply before promotion?",
        "recommendation": "Require each P0/P1 draft decision to show either evidence coverage or explicit missing evidence.",
        "rationale": "Reviewers need to separate validated decisions from unresolved assumptions.",
        "alternative": "Promote without verification criteria",
        "reason_not_recommended": "Promotion could carry unexamined assumptions into canonical proposal review.",
    },
    "review": {
        "id": "DD-GAP-REVIEW",
        "layer": "review",
        "priority": "P1",
        "question": "How should this draft set be reviewed before any promotion?",
        "recommendation": "Review P0/P1 and medium-or-higher risk items individually; bulk review only low-risk eligible items.",
        "rationale": "Human review boundaries keep deterministic drafting from becoming automatic adoption.",
        "alternative": "Use one bulk review for every draft item",
        "reason_not_recommended": "High-impact or underspecified items need individual review.",
    },
}
LAYER_GAP_TYPES = {
    "missing_purpose_layer": "purpose",
    "missing_constraint_layer": "constraint",
    "missing_verification_layer": "verification",
    "missing_review_plan": "review",
}


class AutopilotDraftError(ValueError):
    pass


def run_autopilot_draft(
    ai_dir: str | Path,
    *,
    goal: str | None = None,
    goal_file: str | None = None,
    seed_draft_json: str | None = None,
    draft_set_id: str | None = None,
    max_iterations: int = 3,
    max_draft_decisions: int = 30,
    risk_threshold: str = "medium",
    now: str | None = None,
    export: bool = True,
    force_export: bool = False,
) -> dict[str, Any]:
    """Create a deterministic draft set, iterate diagnostics, and persist sidecar artifacts."""
    _validate_options(
        goal=goal,
        goal_file=goal_file,
        max_iterations=max_iterations,
        max_draft_decisions=max_draft_decisions,
        risk_threshold=risk_threshold,
    )
    timestamp = now or utc_now()
    paths = runtime_paths(ai_dir)
    bundle = load_runtime(paths)
    project_state = bundle["project_state"]
    current_project_head = _current_project_head(project_state)
    goal_text = _read_goal_text(goal=goal, goal_file=goal_file)
    draft_payload = _initial_draft_payload(
        seed_draft_json=seed_draft_json,
        goal_text=goal_text,
        now=timestamp,
        current_project_head=current_project_head,
        ai_dir=paths.ai_dir,
    )
    final_draft_set, iteration_projection = iterate_draft_set(
        project_state=project_state,
        draft_set=draft_payload,
        current_project_head=current_project_head,
        max_iterations=max_iterations,
        max_draft_decisions=max_draft_decisions,
        risk_threshold=risk_threshold,
        now=timestamp,
        ai_dir=paths.ai_dir,
    )
    if final_draft_set.get("id") == "DS-19700101-000":
        final_draft_set.pop("id", None)
    created = create_draft_set(
        paths.ai_dir,
        final_draft_set,
        draft_set_id=draft_set_id,
        generated_by="autopilot",
        now=timestamp,
    )
    persisted_id = created["draft_set_id"]
    projection = build_draft_projection(
        paths.ai_dir,
        draft_set_id=persisted_id,
        now=timestamp,
        persist=True,
        max_iterations=max_iterations,
        convergence_override=iteration_projection["convergence"],
    )
    exports: dict[str, str] = {}
    if export:
        export_result = export_draft_set(
            paths.ai_dir,
            persisted_id,
            format="markdown",
            now=timestamp,
            force=force_export,
        )
        exports = dict(export_result["paths"])
    convergence = projection["convergence"]
    return {
        "status": "ok",
        "draft_set_id": persisted_id,
        "draft_set_path": created["path"],
        "projection_path": str(paths.ai_dir / "draft-sets" / persisted_id / "draft-projection.json"),
        "exports": exports,
        "convergence": {
            "status": convergence["status"],
            "stop_reason": convergence["stop_reason"],
            "iterations": convergence["iterations"],
            "gap_count": convergence["new_gap_count"],
            "blocking_gap_count": convergence["blocking_gap_count"],
        },
        "coverage_summary": projection["coverage_summary"],
        "canonical_events_created": False,
    }


def iterate_draft_set(
    *,
    project_state: dict[str, Any],
    draft_set: dict[str, Any],
    current_project_head: str | None,
    max_iterations: int,
    max_draft_decisions: int,
    risk_threshold: str,
    now: str,
    ai_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return final draft-set payload and final projection without writing files."""
    _validate_iteration_limits(max_iterations=max_iterations, max_draft_decisions=max_draft_decisions)
    if risk_threshold not in VALID_RISK_THRESHOLDS:
        raise AutopilotDraftError("risk_threshold must be one of: low, medium, high, critical")

    current = _normalize_working_draft_set(
        draft_set,
        now=now,
        current_project_head=current_project_head,
        max_draft_decisions=max_draft_decisions,
        max_iterations=max_iterations,
        ai_dir=ai_dir,
    )
    trace: list[dict[str, Any]] = []
    stop_reason = "budget_exhausted"

    for iteration in range(1, max_iterations + 1):
        projection = project_draft_set(
            project_state=project_state,
            draft_set=current,
            current_project_head=current_project_head,
            generated_at=now,
        )
        gaps = projection["gap_diagnostics"]
        convergence = projection["convergence"]
        stop_reason = _classify_stop_reason(
            gaps,
            projection.get("coverage_matrix", []),
            current,
            max_draft_decisions=max_draft_decisions,
            risk_threshold=risk_threshold,
        )
        trace.append(
            {
                "iteration": iteration,
                "gap_count": convergence["new_gap_count"],
                "blocking_gap_count": convergence["blocking_gap_count"],
                "stop_reason": stop_reason,
            }
        )
        if stop_reason != "continue":
            break
        if iteration >= max_iterations or len(_items(current, "draft_decisions")) >= max_draft_decisions:
            stop_reason = "budget_exhausted"
            trace[-1]["stop_reason"] = stop_reason
            break
        additions = synthesize_gap_resolutions(
            draft_set=current,
            projection=projection,
            max_new_decisions=max_draft_decisions - len(_items(current, "draft_decisions")),
        )
        if not _has_effective_additions(current, additions):
            stop_reason = "user_review_required"
            trace[-1]["stop_reason"] = stop_reason
            break
        _apply_additions(current, additions)
    else:
        stop_reason = "budget_exhausted"

    if stop_reason == "continue":
        stop_reason = "budget_exhausted"
    final_projection = project_draft_set(
        project_state=project_state,
        draft_set=current,
        current_project_head=current_project_head,
        generated_at=now,
    )
    final_projection["convergence"]["status"] = STOP_REASON_STATUS[stop_reason]
    final_projection["convergence"]["stop_reason"] = stop_reason
    final_projection["convergence"]["iterations"] = len(trace)
    final_projection["convergence"]["max_iterations"] = max_iterations
    final_projection["convergence"]["explanation"] = _final_projection_explanation(stop_reason, final_projection)
    final_projection["convergence"]["trace"] = trace
    return current, final_projection


def synthesize_gap_resolutions(
    *,
    draft_set: dict[str, Any],
    projection: dict[str, Any],
    max_new_decisions: int,
) -> dict[str, list[dict[str, Any]]]:
    """Create deterministic supplemental draft decisions/actions/verifications for auto-remediable gaps."""
    additions: dict[str, list[dict[str, Any]]] = {
        "draft_decisions": [],
        "draft_actions": [],
        "draft_verifications": [],
    }
    existing_ids = _draft_object_ids(draft_set)
    existing_coverage_target_ids = _draft_coverage_target_ids(draft_set)
    coverage_matrix = [row for row in projection.get("coverage_matrix", []) if isinstance(row, dict)]
    for frontier in projection.get("frontier_queue", []):
        if len(additions["draft_decisions"]) >= max_new_decisions:
            break
        row = _coverage_row_from_frontier(frontier, projection)
        if row is None:
            continue
        if _is_domain_auto_remediable_coverage_row(row):
            axis_id = str(row.get("axis_id") or "")
            if axis_id in existing_coverage_target_ids:
                continue
            decision = _domain_coverage_decision(row, existing_ids=existing_ids)
        else:
            layer = _layer_from_coverage_row(row)
            spec = LAYER_COVERAGE_SPECS.get(layer)
            if spec is None:
                continue
            decision = _coverage_decision(spec)
        if decision["id"] not in existing_ids:
            additions["draft_decisions"].append(decision)
            existing_ids.add(decision["id"])
            existing_coverage_target_ids.update(_string_items(decision.get("coverage_target_ids")))

    for row in projection.get("coverage_matrix", []):
        if len(additions["draft_decisions"]) >= max_new_decisions:
            break
        if not _is_auto_remediable_coverage_row(row):
            continue
        spec = LAYER_COVERAGE_SPECS.get(str(row.get("value")))
        if spec is None:
            continue
        decision = _coverage_decision(spec)
        if decision["id"] not in existing_ids:
            additions["draft_decisions"].append(decision)
            existing_ids.add(decision["id"])

    for gap in projection.get("gap_diagnostics", []):
        gap_type = gap.get("type")
        if gap_type in LAYER_GAP_TYPES and len(additions["draft_decisions"]) < max_new_decisions:
            decision = _coverage_decision(LAYER_COVERAGE_SPECS[LAYER_GAP_TYPES[str(gap_type)]])
            if decision["id"] not in existing_ids:
                additions["draft_decisions"].append(decision)
                existing_ids.add(decision["id"])
        elif gap_type == "missing_required_layer" and len(additions["draft_decisions"]) < max_new_decisions:
            row = _auto_expandable_coverage_row_from_gap(gap, coverage_matrix)
            if row is not None:
                if _is_domain_auto_remediable_coverage_row(row):
                    axis_id = str(row.get("axis_id") or "")
                    if axis_id in existing_coverage_target_ids:
                        continue
                    decision = _domain_coverage_decision(row, existing_ids=existing_ids)
                else:
                    layer = _layer_from_coverage_row(row)
                    decision = _coverage_decision(LAYER_COVERAGE_SPECS[layer])
                if decision["id"] not in existing_ids:
                    additions["draft_decisions"].append(decision)
                    existing_ids.add(decision["id"])
                    existing_coverage_target_ids.update(_string_items(decision.get("coverage_target_ids")))
        elif gap_type == "no_draft_decisions":
            for spec in LAYER_COVERAGE_SPECS.values():
                if len(additions["draft_decisions"]) >= max_new_decisions:
                    break
                decision = _coverage_decision(spec)
                if decision["id"] not in existing_ids:
                    additions["draft_decisions"].append(decision)
                    existing_ids.add(decision["id"])
        elif gap_type == "verification_without_observable_command":
            action_id = gap.get("target_id")
            if isinstance(action_id, str) and action_id:
                verification = _verification_for_action(action_id)
                if verification["id"] not in existing_ids:
                    additions["draft_verifications"].append(verification)
                    existing_ids.add(verification["id"])
        elif gap_type == "unsupported_recommendation":
            draft_id = gap.get("target_id")
            if isinstance(draft_id, str) and draft_id:
                action = _evidence_action_for_decision(draft_id)
                if action["id"] not in existing_ids:
                    additions["draft_actions"].append(action)
                    existing_ids.add(action["id"])
    return additions


def _initial_draft_payload(
    *,
    seed_draft_json: str | None,
    goal_text: str | None,
    now: str,
    current_project_head: str | None,
    ai_dir: str | Path | None,
) -> dict[str, Any]:
    registry = _load_domain_registry(ai_dir)
    if seed_draft_json:
        payload = _read_seed_json(seed_draft_json)
        if not isinstance(payload, dict):
            raise AutopilotDraftError("seed-draft-json must contain an object")
        payload = deepcopy(payload)
        if "goal" not in payload or not isinstance(payload.get("goal"), dict):
            payload["goal"] = _goal_from_text(goal_text or "Review draft decision set", now=now)
        _default_seed_domain_pack(payload, registry=registry, goal_text=goal_text)
        return payload
    if goal_text is None or not goal_text.strip():
        raise AutopilotDraftError("autopilot-draft requires --seed-draft-json, --goal, or --goal-file")
    domain_pack_id = registry.infer_from_context(goal_text)
    return _goal_only_skeleton(
        goal_text,
        now=now,
        current_project_head=current_project_head,
        domain_pack_id=domain_pack_id,
    )


def _load_domain_registry(ai_dir: str | Path | None) -> DomainRegistry:
    try:
        return load_domain_registry(ai_dir)
    except DomainPackLoadError as exc:
        raise AutopilotDraftError(f"cannot load domain packs: {exc}") from exc


def _default_seed_domain_pack(
    payload: dict[str, Any],
    *,
    registry: DomainRegistry,
    goal_text: str | None,
) -> None:
    source_context = payload.get("source_context")
    if source_context is not None and not isinstance(source_context, dict):
        return
    if source_context is None:
        source_context = {}
        payload["source_context"] = source_context

    if "domain_pack_id" in source_context:
        existing_pack_id = source_context["domain_pack_id"]
        if not isinstance(existing_pack_id, str) or not existing_pack_id.strip():
            raise AutopilotDraftError("source_context.domain_pack_id must be a non-empty string")
        pack_id = existing_pack_id.strip()
        try:
            registry.get(pack_id)
        except KeyError as exc:
            raise AutopilotDraftError(f"unknown domain pack: {pack_id}") from exc
        source_context["domain_pack_id"] = pack_id
        return

    source_context["domain_pack_id"] = registry.infer_from_context(
        _domain_pack_inference_text(payload, goal_text=goal_text)
    )


def _domain_pack_inference_text(payload: dict[str, Any], *, goal_text: str | None) -> str:
    parts: list[str] = []
    if goal_text:
        parts.append(goal_text)
    goal = payload.get("goal")
    if isinstance(goal, dict):
        for key in ("title", "desired_outcome"):
            value = goal.get(key)
            if isinstance(value, str):
                parts.append(value)
        constraints = goal.get("constraints")
        if isinstance(constraints, list):
            parts.extend(item for item in constraints if isinstance(item, str))
    return " ".join(parts)


def _goal_only_skeleton(
    goal_text: str,
    *,
    now: str,
    current_project_head: str | None,
    domain_pack_id: str = GENERIC_PACK_ID,
) -> dict[str, Any]:
    goal = _goal_from_text(goal_text, now=now)
    decisions = [
        _skeleton_decision(
            "DD-GOAL-PURPOSE",
            layer="purpose",
            priority="P0",
            question="How should the goal and success criteria be defined before promotion review?",
            recommendation="Review the goal statement, desired outcome, and non-goals before promoting any draft decision.",
            rationale="Goal-only autopilot cannot infer accepted scope; it can only produce a conservative review scaffold.",
        ),
        _skeleton_decision(
            "DD-GOAL-CONSTRAINT",
            layer="constraint",
            priority="P0",
            question="How should canonical runtime state be protected during drafting?",
            recommendation="Keep all autopilot output in draft-set sidecars until a user explicitly promotes a decision.",
            rationale="This preserves the event log as the source of truth and prevents draft text from becoming accepted state.",
        ),
        _skeleton_decision(
            "DD-GOAL-EVIDENCE",
            layer="verification",
            priority="P1",
            question="How should missing evidence be handled before promotion?",
            recommendation="Treat missing evidence as review input and add evidence collection actions instead of upgrading coverage.",
            rationale="The deterministic runtime must not claim evidence that was not inspected.",
        ),
        _skeleton_decision(
            "DD-GOAL-REVIEW",
            layer="review",
            priority="P1",
            question="What approval boundary should govern this draft set?",
            recommendation="Review P0/P1 items individually and allow bulk materialization only for low-risk eligible drafts.",
            rationale="Promotion creates canonical proposals, so review boundaries must remain explicit.",
        ),
    ]
    return {
        "schema_version": DRAFT_SET_SCHEMA_VERSION,
        "id": "DS-19700101-000",
        "status": "generated",
        "mode": "autopilot-draft",
        "created_at": now,
        "generated_by": "autopilot",
        "goal": goal,
        "source_context": {
            "project_head_at_generation": current_project_head or "unknown",
            "project_state_ref": "project-state.json",
            "included_session_ids": [],
            "included_object_ids": [],
            "domain_pack_id": domain_pack_id,
        },
        "draft_decisions": decisions,
        "draft_assumptions": [],
        "draft_risks": [],
        "draft_actions": [],
        "draft_verifications": [],
        "conflicts": [],
        "promotion": {
            "promoted_decision_ids": [],
            "bulk_promotable_ids": [],
            "individual_review_required_ids": [],
        },
    }


def _normalize_working_draft_set(
    draft_set: dict[str, Any],
    *,
    now: str,
    current_project_head: str | None,
    max_draft_decisions: int,
    max_iterations: int,
    ai_dir: str | Path | None = None,
) -> dict[str, Any]:
    current = deepcopy(draft_set)
    current.setdefault("schema_version", DRAFT_SET_SCHEMA_VERSION)
    current.setdefault("id", "DS-19700101-000")
    current.setdefault("status", "generated")
    current.setdefault("mode", "autopilot-draft")
    current.setdefault("created_at", now)
    current.setdefault("generated_by", "autopilot")
    current.setdefault("goal", _goal_from_text("Review draft decision set", now=now))
    source_context = current.setdefault("source_context", {})
    if isinstance(source_context, dict):
        source_context.setdefault("project_head_at_generation", current_project_head or "unknown")
        source_context.setdefault("project_state_ref", "project-state.json")
        source_context.setdefault("included_session_ids", [])
        source_context.setdefault("included_object_ids", [])
        source_context.setdefault("domain_pack_id", GENERIC_PACK_ID)
    if "exploration_contract" not in current:
        current["exploration_contract"] = default_exploration_contract(
            current,
            max_draft_decisions=max_draft_decisions,
            max_iterations=max_iterations,
            ai_dir=ai_dir,
        )
    else:
        exploration_contract = current.get("exploration_contract")
        if isinstance(exploration_contract, dict) and isinstance(exploration_contract.get("budgets"), dict):
            exploration_contract["budgets"]["max_draft_decisions"] = max_draft_decisions
            exploration_contract["budgets"]["max_iterations"] = max_iterations
    for field in (
        "draft_decisions",
        "draft_assumptions",
        "draft_risks",
        "draft_actions",
        "draft_verifications",
        "conflicts",
    ):
        current.setdefault(field, [])
    current.setdefault(
        "promotion",
        {
            "promoted_decision_ids": [],
            "bulk_promotable_ids": [],
            "individual_review_required_ids": [],
        },
    )
    return current


def _classify_stop_reason(
    gaps: list[dict[str, Any]],
    coverage_matrix: list[dict[str, Any]],
    draft_set: dict[str, Any],
    *,
    max_draft_decisions: int,
    risk_threshold: str,
) -> str:
    blocking_gap_types = {
        str(gap.get("type"))
        for gap in gaps
        if gap.get("blocks_convergence") is True
    }
    if "accepted_decision_conflict_possible" in blocking_gap_types:
        return "conflict_blocked"
    if any(
        gap.get("type") in HARD_STOP_RISK_GAP_TYPES
        and gap.get("target_kind") == "draft_decision"
        and gap.get("blocks_convergence") is True
        for gap in gaps
    ):
        return "risk_gate_triggered"
    auto_coverage = [row for row in coverage_matrix if _is_auto_expandable_coverage_row(row)]
    auto_remediable = [gap for gap in gaps if _is_auto_remediable_gap(gap, coverage_matrix)]
    if len(_items(draft_set, "draft_decisions")) >= max_draft_decisions and (
        auto_remediable or auto_coverage
    ):
        return "budget_exhausted"
    non_auto_blocking = [
        gap
        for gap in gaps
        if gap.get("blocks_convergence") is True
        and gap.get("target_kind") != "coverage_gap"
        and not _is_auto_remediable_gap(gap, coverage_matrix)
    ]
    non_auto_coverage_blocking = [
        row
        for row in coverage_matrix
        if row.get("blocks_convergence") is True and not _is_auto_expandable_coverage_row(row)
    ]
    non_auto_structural_coverage_blocking = [
        row
        for row in non_auto_coverage_blocking
        if row.get("axis_type") == "decision_stack_layer"
    ]
    hard_stop_safety_coverage = _has_blocking_safety_coverage(coverage_matrix)
    if (
        (auto_remediable or auto_coverage)
        and not non_auto_blocking
        and not non_auto_structural_coverage_blocking
        and not hard_stop_safety_coverage
        and not (blocking_gap_types & HARD_STOP_REVIEW_GAP_TYPES)
    ):
        return "continue"
    if any(
        gap.get("type") in {"insufficient_evidence", "challenged_evidence"}
        and gap.get("blocks_convergence") is True
        for gap in gaps
    ):
        return "evidence_gap_blocked"
    if blocking_gap_types & HARD_STOP_RISK_GAP_TYPES:
        return "risk_gate_triggered"
    if blocking_gap_types & HARD_STOP_REVIEW_GAP_TYPES:
        return "user_review_required"
    if non_auto_blocking or non_auto_coverage_blocking:
        return "user_review_required"
    unresolved = [gap for gap in gaps if _severity_at_or_above(str(gap.get("severity")), risk_threshold)]
    if unresolved:
        return "user_review_required"
    return "converged"


def _is_auto_remediable_coverage_row(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and row.get("source") != "domain_pack"
        and row.get("match_policy") == "layer_complete"
        and row.get("blocks_convergence") is True
        and row.get("axis_type") == "decision_stack_layer"
        and row.get("status") in {"missing", "partial"}
        and str(row.get("value") or "") in LAYER_COVERAGE_SPECS
    )


def _is_domain_auto_remediable_coverage_row(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and row.get("source") == "domain_pack"
        and row.get("match_policy") == "explicit_target_or_domain_axis"
        and row.get("blocks_convergence") is True
        and row.get("axis_type") == "decision_stack_layer"
        and row.get("status") in {"missing", "partial"}
        and row.get("required") is True
        and row.get("priority") in {"P0", "P1"}
        and isinstance(row.get("axis_id"), str)
        and bool(str(row.get("axis_id") or "").strip())
        and str(row.get("value") or "") in LAYER_COVERAGE_SPECS
    )


def _is_auto_expandable_coverage_row(row: Any) -> bool:
    return _is_auto_remediable_coverage_row(row) or _is_domain_auto_remediable_coverage_row(row)


def _has_blocking_safety_coverage(coverage_matrix: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(row, dict)
        and row.get("blocks_convergence") is True
        and row.get("axis_type") in HARD_STOP_SAFETY_AXIS_TYPES
        for row in coverage_matrix
    )


def _is_auto_remediable_gap(gap: dict[str, Any], coverage_matrix: list[dict[str, Any]]) -> bool:
    gap_type = gap.get("type")
    if gap_type == "missing_required_layer":
        return bool(_auto_expandable_coverage_row_from_gap(gap, coverage_matrix))
    return gap_type in AUTO_REMEDIABLE_GAP_TYPES


def _auto_expandable_coverage_row_from_gap(
    gap: dict[str, Any],
    coverage_matrix: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if gap.get("target_kind") != "coverage_gap":
        return None
    target_id = str(gap.get("target_id") or "")
    rows_by_axis_id = {
        str(row.get("axis_id")): row
        for row in coverage_matrix
        if isinstance(row, dict) and isinstance(row.get("axis_id"), str)
    }
    row = rows_by_axis_id.get(target_id)
    if row is not None and _is_auto_expandable_coverage_row(row):
        return row
    return None


def _coverage_row_from_frontier(frontier: Any, projection: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(frontier, dict):
        return None
    source_gap_id = frontier.get("source_gap_id")
    if not isinstance(source_gap_id, str):
        return None
    gaps_by_id = {
        str(gap.get("id")): gap
        for gap in projection.get("gap_diagnostics", [])
        if isinstance(gap, dict) and isinstance(gap.get("id"), str)
    }
    gap = gaps_by_id.get(source_gap_id)
    if gap is None or gap.get("target_kind") != "coverage_gap":
        return None
    target_id = gap.get("target_id")
    rows_by_axis_id = {
        str(row.get("axis_id")): row
        for row in projection.get("coverage_matrix", [])
        if isinstance(row, dict) and isinstance(row.get("axis_id"), str)
    }
    row = rows_by_axis_id.get(str(target_id or ""))
    if row is not None and _is_auto_expandable_coverage_row(row):
        return row
    return None


def _layer_from_coverage_row(row: dict[str, Any]) -> str:
    layer = str(row.get("value") or "")
    return layer if layer in LAYER_COVERAGE_SPECS else ""


def _final_projection_explanation(stop_reason: str, projection: dict[str, Any]) -> str:
    gap_count = projection["convergence"]["new_gap_count"]
    blocking_gap_count = projection["convergence"]["blocking_gap_count"]
    if stop_reason == "converged":
        return "Autopilot converged under the configured deterministic diagnostics."
    return f"Autopilot stopped with {gap_count} gap(s), including {blocking_gap_count} blocking gap(s)."


def _apply_additions(draft_set: dict[str, Any], additions: dict[str, list[dict[str, Any]]]) -> None:
    for field, items in additions.items():
        existing_ids = _draft_object_ids(draft_set)
        target = draft_set.setdefault(field, [])
        if not isinstance(target, list):
            draft_set[field] = []
            target = draft_set[field]
        for item in items:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id not in existing_ids:
                target.append(item)
                existing_ids.add(item_id)


def _has_effective_additions(draft_set: dict[str, Any], additions: dict[str, list[dict[str, Any]]]) -> bool:
    existing_ids = _draft_object_ids(draft_set)
    for items in additions.values():
        for item in items:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id not in existing_ids:
                return True
    return False


def _coverage_decision(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "id": spec["id"],
        "status": "recommended",
        "layer": spec["layer"],
        "priority": spec["priority"],
        "frontier": "now",
        "kind": "choice",
        "question": spec["question"],
        "recommendation": spec["recommendation"],
        "rationale": spec["rationale"],
        "alternatives": [
            {
                "option": spec["alternative"],
                "reason_not_recommended": spec["reason_not_recommended"],
            }
        ],
        "risk_tier": "medium",
        "reversibility": "reversible",
        "evidence_coverage": {
            "status": "partial",
            "supporting_object_ids": [],
            "source_unit_ids": [],
            "missing": ["human review of deterministic supplemental draft"],
        },
        "human_review": {
            "required": True,
            "mode": "individual",
            "bulk_promotable": False,
            "reason": "Supplemental gap-resolution draft decisions require human review.",
        },
        "promotion_recipe": {
            "canonical_object_type": "decision",
            "canonical_initial_status": "unresolved",
            "proposal_required": True,
            "acceptance_mode_allowed": ["explicit"],
            "blocked_for_bulk_acceptance": True,
        },
    }


def _domain_coverage_decision(row: dict[str, Any], *, existing_ids: set[str] | None = None) -> dict[str, Any]:
    axis_id = str(row.get("axis_id") or "")
    layer = str(row.get("value") or "")
    pack_id = str(row.get("domain_pack_id") or "domain")
    axis = str(row.get("domain_axis_id") or "axis")
    label = str(row.get("label") or axis.replace("_", " ")).strip() or axis
    draft_id = _domain_coverage_decision_id(
        pack_id=pack_id,
        axis=axis,
        layer=layer,
        axis_id=axis_id,
        existing_ids=existing_ids or set(),
    )
    label_text = label[:1].lower() + label[1:] if label else axis
    decision = _coverage_decision(
        {
            "id": draft_id,
            "layer": layer,
            "priority": str(row.get("priority") or "P1"),
            "question": (
                f"What {layer} decision should address the {pack_id} "
                f"{label_text} coverage target before promotion?"
            ),
            "recommendation": _domain_coverage_recommendation(layer, label_text),
            "rationale": (
                f"Domain Pack axis {axis} requires explicit coverage; generic "
                f"{layer}-layer draft decisions do not satisfy {axis_id}."
            ),
            "alternative": f"Treat generic {layer} coverage as sufficient",
            "reason_not_recommended": (
                f"{axis_id} requires coverage_target_ids binding to prevent false "
                "domain-axis coverage."
            ),
        }
    )
    decision["coverage_target_ids"] = [axis_id]
    decision["evidence_coverage"]["missing"] = [
        f"human review of domain-specific evidence for {axis_id}"
    ]
    decision["human_review"]["reason"] = (
        "Domain-specific supplemental draft decisions require individual review."
    )
    return decision


def _domain_coverage_decision_id(
    *,
    pack_id: str,
    axis: str,
    layer: str,
    axis_id: str,
    existing_ids: set[str],
) -> str:
    base_id = f"DD-GAP-{_safe_id_suffix(f'{pack_id}-{axis}-{layer}')}"
    if base_id not in existing_ids:
        return base_id
    digest = hashlib.sha256(axis_id.encode("utf-8")).hexdigest()[:8].upper()
    candidate = f"{base_id}-{digest}"
    counter = 2
    while candidate in existing_ids:
        candidate = f"{base_id}-{digest}-{counter}"
        counter += 1
    return candidate


def _domain_coverage_recommendation(layer: str, label_text: str) -> str:
    recommendations = {
        "purpose": f"Define the intended outcome and success signal for {label_text} before promotion.",
        "principle": f"Set the guiding principle and tradeoff rule for {label_text} before promotion.",
        "constraint": f"State the constraints, prohibitions, and non-goals for {label_text} before promotion.",
        "strategy": (
            "Choose the strategy, prioritization rule, and sequencing approach for "
            f"{label_text} before promotion."
        ),
        "design": f"Define the design boundary and review criteria for {label_text} before promotion.",
        "execution": (
            "Specify the minimum execution path and rollback consideration for "
            f"{label_text} before promotion."
        ),
        "verification": f"Require an observable verification step for {label_text} assumptions before promotion.",
        "review": f"Define the approval criteria and individual review conditions for {label_text} before promotion.",
    }
    return recommendations.get(
        layer,
        f"Clarify the {layer}-layer policy, acceptance criteria, and review trigger for {label_text} before promotion.",
    )


def _skeleton_decision(
    draft_id: str,
    *,
    layer: str,
    priority: str,
    question: str,
    recommendation: str,
    rationale: str,
) -> dict[str, Any]:
    decision = _coverage_decision(
        {
            "id": draft_id,
            "layer": layer,
            "priority": priority,
            "question": question,
            "recommendation": recommendation,
            "rationale": rationale,
            "alternative": "Skip this review decision",
            "reason_not_recommended": "Goal-only drafting needs explicit human review before promotion.",
        }
    )
    decision["evidence_coverage"]["missing"] = ["goal-specific human review"]
    return decision


def _verification_for_action(action_id: str) -> dict[str, Any]:
    suffix = _safe_id_suffix(action_id)
    return {
        "id": f"DV-GAP-{suffix}",
        "statement": f"Verify completion criteria for action {action_id}.",
        "target_ids": [action_id],
        "method": "human_review",
        "evidence_coverage": {
            "status": "none",
            "missing": ["verification evidence"],
        },
    }


def _evidence_action_for_decision(draft_id: str) -> dict[str, Any]:
    suffix = _safe_id_suffix(draft_id)
    return {
        "id": f"DACTION-GAP-{suffix}",
        "statement": f"Collect or review missing evidence for draft decision {draft_id}.",
        "purpose": "evidence_collection",
        "target_ids": [draft_id],
        "linked_decision_ids": [draft_id],
        "evidence_coverage": {
            "status": "none",
            "missing": ["evidence collection result"],
        },
    }


def _goal_from_text(goal_text: str, *, now: str) -> dict[str, Any]:
    title = " ".join(goal_text.strip().split()) or "Review draft decision set"
    date_part = _yyyymmdd(now)
    return {
        "id": f"G-{date_part}-001",
        "title": title,
        "desired_outcome": f"Create a reviewable draft decision set for: {title}",
        "constraints": [
            "Do not mutate canonical runtime during drafting",
            "Do not create accepted decisions",
            "Keep deterministic autopilot output reviewable",
        ],
    }


def _read_goal_text(*, goal: str | None, goal_file: str | None) -> str | None:
    if goal is not None and goal_file is not None:
        raise AutopilotDraftError("--goal and --goal-file cannot be used together")
    if goal_file is not None:
        return Path(goal_file).read_text(encoding="utf-8")
    return goal


def _read_seed_json(path: str) -> dict[str, Any]:
    try:
        if path == "-":
            raise AutopilotDraftError("seed-draft-json '-' is not supported by run_autopilot_draft")
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AutopilotDraftError(f"seed-draft-json contains malformed JSON: {exc.msg}") from exc


def _validate_options(
    *,
    goal: str | None,
    goal_file: str | None,
    max_iterations: int,
    max_draft_decisions: int,
    risk_threshold: str,
) -> None:
    if goal is not None and goal_file is not None:
        raise AutopilotDraftError("--goal and --goal-file cannot be used together")
    _validate_iteration_limits(max_iterations=max_iterations, max_draft_decisions=max_draft_decisions)
    if risk_threshold not in VALID_RISK_THRESHOLDS:
        raise AutopilotDraftError("--risk-threshold must be one of: low, medium, high, critical")


def _validate_iteration_limits(*, max_iterations: int, max_draft_decisions: int) -> None:
    if max_iterations < 1 or max_iterations > 10:
        raise AutopilotDraftError("--max-iterations must be between 1 and 10")
    if max_draft_decisions < 1 or max_draft_decisions > 100:
        raise AutopilotDraftError("--max-draft-decisions must be between 1 and 100")


def _current_project_head(project_state: dict[str, Any]) -> str | None:
    value = project_state.get("state", {}).get("project_head")
    return value if isinstance(value, str) and value else None


def _draft_object_ids(draft_set: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field in (
        "draft_decisions",
        "draft_assumptions",
        "draft_risks",
        "draft_actions",
        "draft_verifications",
    ):
        for item in _items(draft_set, field):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.add(item["id"])
    return ids


def _draft_coverage_target_ids(draft_set: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for draft in _items(draft_set, "draft_decisions"):
        if isinstance(draft, dict):
            ids.update(_string_items(draft.get("coverage_target_ids")))
    return ids


def _string_items(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _items(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    return item if isinstance(item, list) else []


def _severity_at_or_above(severity: str, threshold: str) -> bool:
    rank = {"low": 3, "medium": 2, "high": 1, "critical": 0}
    return rank.get(severity, 99) <= rank[threshold]


def _safe_id_suffix(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return sanitized or "ITEM"


def _yyyymmdd(value: str) -> str:
    return value[:10].replace("-", "") if len(value) >= 10 else "19700101"
