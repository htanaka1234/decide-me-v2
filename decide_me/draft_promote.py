from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from decide_me.constants import ACCEPTED_VIA_VALUES
from decide_me.draft_sets import DraftSetError, DraftSetHeadMismatchError, draft_set_dir, load_draft_set
from decide_me.events import utc_now
from decide_me.object_views import latest_proposal_for_decision, proposal_view
from decide_me.protocol import (
    current_bundle,
    materialize_decision_with_proposal,
    _require_mutable_session,
    _require_no_other_active_proposal,
)
from decide_me.store import (
    _atomic_write_json,
    _atomic_write_text,
    _write_lock,
    load_runtime,
    read_event_log,
    runtime_paths,
)
from decide_me.taxonomy import stable_unique


PROMOTION_VERSION = 1
RISK_SCAFFOLD_TIERS = {"medium", "high", "critical"}
_BULK_ALLOWED_RISK_TIER = "low"


class DraftPromotionError(DraftSetError):
    pass


class DraftDecisionNotFoundError(DraftPromotionError):
    pass


class DraftDecisionNotPromotableError(DraftPromotionError):
    pass


class DraftDecisionAlreadyPromotedError(DraftPromotionError):
    pass


class DraftPromotionStaleError(DraftSetHeadMismatchError, DraftPromotionError):
    pass


class DraftBulkPromotionError(DraftPromotionError):
    pass


def promote_draft_decision(
    ai_dir: str | Path,
    draft_set_id: str,
    draft_decision_id: str,
    *,
    session_id: str,
    allow_stale: bool = False,
    bulk: bool = False,
    materialize_risk_scaffold: bool = True,
    promotion_mode: str = "single",
    now: str | None = None,
    expected_project_head: str | None = None,
) -> dict[str, Any]:
    draft_set = load_draft_set(ai_dir, draft_set_id)
    draft = _require_draft_decision(draft_set, draft_decision_id)
    _validate_promotion_recipe(draft)
    _require_risk_scaffold_policy(draft, materialize_risk_scaffold=materialize_risk_scaffold)
    if bulk:
        _require_bulk_promotable(draft)
        promotion_mode = "bulk"

    promoted_at = now or utc_now()
    suffix = _stable_suffix(draft_set_id, draft_decision_id)
    decision_id = f"D-draft-{suffix}"
    option_id = f"O-option-draft-{suffix}"
    proposal_id = f"P-draft-{suffix}"
    question_id = f"Q-draft-{suffix}"

    bundle = current_bundle(str(ai_dir))
    session = _require_mutable_session(bundle, session_id)
    current_head = _current_project_head(bundle)
    generated_head = _project_head_at_generation(draft_set)
    staleness_head = expected_project_head or current_head
    stale = generated_head != staleness_head
    existing = _find_promoted_decision(bundle, draft_set_id, draft_decision_id)
    if existing is not None:
        proposal = latest_proposal_for_decision(bundle["project_state"], existing["id"])
        if proposal is None:
            raise DraftPromotionError(
                f"draft decision {draft_decision_id} was promoted to {existing['id']} "
                "but has no canonical proposal"
            )
        return {
            "status": "already_promoted",
            "draft_set_id": draft_set_id,
            "draft_decision_id": draft_decision_id,
            "session_id": session_id,
            "decision_id": existing["id"],
            "proposal_id": proposal["id"],
            "idempotent": True,
            "event_ids": [],
            "decision": existing,
            "proposal": proposal_view(bundle["project_state"], proposal["id"]),
        }
    if stale and not allow_stale:
        raise DraftPromotionStaleError(
            "draft set is stale: "
            f"generated at project_head {generated_head}, current project_head is {staleness_head}"
        )
    _require_no_other_active_proposal(bundle, session, decision_id)
    _require_no_id_collision(bundle, decision_id, "decision")
    _require_no_id_collision(bundle, option_id, "option")
    _require_no_id_collision(bundle, proposal_id, "proposal")
    _require_supporting_objects(bundle, draft, decision_id)

    origin = _draft_origin(
        draft_set_id,
        draft_decision_id,
        generated_head=generated_head,
        current_head=current_head,
        promoted_at=promoted_at,
        promotion_mode=promotion_mode,
        stale_promoted=stale,
        draft=draft,
    )
    materialized = materialize_decision_with_proposal(
        str(ai_dir),
        session_id,
        decision=_canonical_decision_payload(decision_id, draft, origin),
        proposal={
            "id": proposal_id,
            "option_id": option_id,
            "question_id": question_id,
            "question": draft["question"],
            "recommendation": draft["recommendation"],
            "why": draft["rationale"],
            "if_not": _proposal_if_not(draft),
            "metadata": {
                "author": "assistant",
                "source": "draft-promotion",
                "draft_origin": deepcopy(origin),
                "acceptance_mode_allowed": _acceptance_modes(draft),
                "blocked_for_bulk_acceptance": draft["promotion_recipe"]["blocked_for_bulk_acceptance"],
                "option_metadata": {
                    "source": "draft-promotion",
                    "draft_origin": deepcopy(origin),
                },
            },
        },
        supporting_object_ids=_supporting_object_ids(draft),
        risk_scaffold=_risk_scaffold(suffix, draft, origin=origin, decision_id=decision_id)
        if materialize_risk_scaffold and _needs_risk_scaffold(draft)
        else None,
        now=promoted_at,
    )
    sidecar = _record_promotion_sidecar(
        ai_dir,
        draft_set_id,
        draft_decision_id,
        session_id=session_id,
        decision_id=decision_id,
        proposal_id=proposal_id,
        option_id=option_id,
        question_id=question_id,
        promoted_at=promoted_at,
        materialized=materialized,
        draft_set=draft_set,
    )
    result = {
        "status": "promoted",
        "draft_set_id": draft_set_id,
        "draft_decision_id": draft_decision_id,
        "session_id": session_id,
        "decision_id": decision_id,
        "proposal_id": proposal_id,
        "option_id": option_id,
        "question_id": question_id,
        "risk_object_ids": materialized["risk_object_ids"],
        "tx_id": materialized["tx_id"],
        "event_ids": materialized["event_ids"],
        "project_head_before_promotion": materialized["project_head_before_promotion"],
        "project_head_after_promotion": materialized["project_head_after_promotion"],
        "sidecar": sidecar,
        "decision": materialized["decision"],
        "proposal": materialized["proposal"],
    }
    return result


def promote_draft_set(
    ai_dir: str | Path,
    draft_set_id: str,
    *,
    session_id: str | None = None,
    session_map: dict[str, str] | None = None,
    only_bulk_promotable: bool,
    allow_stale: bool = False,
) -> dict[str, Any]:
    if not only_bulk_promotable:
        raise DraftBulkPromotionError("promote-draft-set requires --only-bulk-promotable")
    if allow_stale:
        raise DraftBulkPromotionError("bulk promotion does not support allow_stale")
    draft_set = load_draft_set(ai_dir, draft_set_id)
    bundle = current_bundle(str(ai_dir))
    generated_head = _project_head_at_generation(draft_set)
    current_head = _current_project_head(bundle)
    if generated_head != current_head:
        raise DraftPromotionStaleError(
            "bulk promotion rejects stale draft sets: "
            f"generated at project_head {generated_head}, current project_head is {current_head}"
        )
    _reject_explicit_forbidden_bulk_requests(draft_set)
    requested_ids = stable_unique(draft_set.get("promotion", {}).get("bulk_promotable_ids", []))
    drafts = {
        draft.get("id"): draft
        for draft in draft_set.get("draft_decisions", [])
        if isinstance(draft, dict) and draft.get("id")
    }
    candidates = [draft_id for draft_id in requested_ids if _is_bulk_promotable(drafts.get(draft_id, {}))]
    if not session_id and not session_map and candidates:
        raise DraftBulkPromotionError("promote-draft-set requires --session-id or --session-map-json")
    if session_id and session_map:
        raise DraftBulkPromotionError("promote-draft-set accepts either --session-id or --session-map-json, not both")
    if session_id and len(candidates) > 1:
        raise DraftBulkPromotionError(
            "bulk promotion would create multiple active proposals in one session; "
            "use --session-map-json to assign separate sessions"
        )
    target_sessions = _bulk_target_sessions(candidates, session_id=session_id, session_map=session_map)
    _preflight_bulk_promotions(
        bundle,
        draft_set,
        candidates,
        target_sessions=target_sessions,
        draft_set_id=draft_set_id,
    )
    promoted = []
    for draft_id in candidates:
        promoted.append(
            promote_draft_decision(
                ai_dir,
                draft_set_id,
                draft_id,
                session_id=target_sessions[draft_id],
                bulk=True,
                promotion_mode="bulk",
                expected_project_head=current_head,
            )
        )
    return {
        "status": "ok",
        "draft_set_id": draft_set_id,
        "promoted_count": len(promoted),
        "promoted": promoted,
        "skipped": _bulk_skips(draft_set),
    }


def reconcile_draft_promotions(
    ai_dir: str | Path,
    draft_set_id: str,
    *,
    repair: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    """Compare draft promotion sidecar metadata against canonical draft_origin provenance."""
    paths = runtime_paths(ai_dir)
    with _write_lock(paths.lock_path):
        draft_set = load_draft_set(paths.ai_dir, draft_set_id)
        bundle = load_runtime(paths)
        events_by_id = {event["event_id"]: event for event in read_event_log(paths) if event.get("event_id")}
        canonical_promotions = _canonical_promotions(bundle, draft_set_id, events_by_id=events_by_id)
        canonical_ids = stable_unique(item["draft_decision_id"] for item in canonical_promotions)
        sidecar_ids = _sidecar_promoted_decision_ids(draft_set)
        canonical_id_set = set(canonical_ids)
        sidecar_id_set = set(sidecar_ids)
        missing_in_sidecar = [draft_id for draft_id in canonical_ids if draft_id not in sidecar_id_set]
        stale_in_sidecar = [draft_id for draft_id in sidecar_ids if draft_id not in canonical_id_set]
        log_path = _promotion_log_path(paths.ai_dir, draft_set_id)
        draft_set_path = draft_set_dir(paths.ai_dir, draft_set_id) / "draft-set.json"
        log_ids, log_errors = _promotion_log_promoted_decision_ids(log_path)
        log_id_set = set(log_ids)
        missing_in_promotion_log = [draft_id for draft_id in canonical_ids if draft_id not in log_id_set]
        stale_in_promotion_log = [draft_id for draft_id in log_ids if draft_id not in canonical_id_set]

        if repair:
            updated_draft_set = deepcopy(draft_set)
            promotion = updated_draft_set.setdefault("promotion", {})
            promotion["promoted_decision_ids"] = canonical_ids
            promotion.setdefault("bulk_promotable_ids", [])
            promotion.setdefault("individual_review_required_ids", [])
            _atomic_write_json(draft_set_path, updated_draft_set)
            reconciled_at = now or utc_now()
            _atomic_write_text(
                log_path,
                "".join(
                    json.dumps(
                        _reconciled_promotion_record(item, reconciled_at=reconciled_at),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                    for item in canonical_promotions
                ),
            )

    return {
        "status": "ok",
        "draft_set_id": draft_set_id,
        "canonical_promoted_decision_ids": canonical_ids,
        "sidecar_promoted_decision_ids": sidecar_ids,
        "missing_in_sidecar": missing_in_sidecar,
        "stale_in_sidecar": stale_in_sidecar,
        "promotion_log_promoted_decision_ids": log_ids,
        "missing_in_promotion_log": missing_in_promotion_log,
        "stale_in_promotion_log": stale_in_promotion_log,
        "promotion_log_parse_errors": log_errors,
        "promotion_log_path": str(log_path),
        "draft_set_path": str(draft_set_path),
        "repaired": repair,
    }


def _require_draft_decision(draft_set: dict[str, Any], draft_decision_id: str) -> dict[str, Any]:
    matches = [
        draft
        for draft in draft_set.get("draft_decisions", [])
        if isinstance(draft, dict) and draft.get("id") == draft_decision_id
    ]
    if not matches:
        raise DraftDecisionNotFoundError(
            f"draft decision {draft_decision_id} not found in draft set {draft_set.get('id')}"
        )
    if len(matches) > 1:
        raise DraftDecisionNotPromotableError(f"draft decision id is duplicated: {draft_decision_id}")
    return matches[0]


def _validate_promotion_recipe(draft: dict[str, Any]) -> None:
    if draft.get("status") != "recommended":
        raise DraftDecisionNotPromotableError(
            f"draft decision {draft.get('id')} is not promotable: status must be recommended"
        )
    for key in ("question", "recommendation", "rationale"):
        if not isinstance(draft.get(key), str) or not draft[key].strip():
            raise DraftDecisionNotPromotableError(
                f"draft decision {draft.get('id')} is not promotable: {key} must not be empty"
            )
    recipe = draft.get("promotion_recipe")
    if not isinstance(recipe, dict):
        raise DraftDecisionNotPromotableError("draft decision promotion_recipe is missing")
    if recipe.get("canonical_object_type") != "decision":
        raise DraftDecisionNotPromotableError("promotion_recipe.canonical_object_type must be decision")
    if recipe.get("canonical_initial_status") != "unresolved":
        raise DraftDecisionNotPromotableError("promotion_recipe.canonical_initial_status must be unresolved")
    if recipe.get("proposal_required") is not True:
        raise DraftDecisionNotPromotableError("promotion_recipe.proposal_required must be true")
    modes = _acceptance_modes(draft)
    if not modes:
        raise DraftDecisionNotPromotableError("promotion_recipe.acceptance_mode_allowed must not be empty")
    invalid = sorted(set(modes) - ACCEPTED_VIA_VALUES)
    if invalid:
        raise DraftDecisionNotPromotableError(
            "promotion_recipe.acceptance_mode_allowed contains invalid modes: "
            + ", ".join(invalid)
        )


def _require_risk_scaffold_policy(draft: dict[str, Any], *, materialize_risk_scaffold: bool) -> None:
    if _needs_risk_scaffold(draft) and not materialize_risk_scaffold:
        raise DraftDecisionNotPromotableError(
            f"draft decision {draft.get('id')} with risk_tier={draft.get('risk_tier')} "
            "must materialize a canonical risk scaffold"
        )


def _require_bulk_promotable(draft: dict[str, Any]) -> None:
    if not _is_bulk_promotable(draft):
        raise DraftBulkPromotionError(
            f"draft decision {draft.get('id')} is not eligible for bulk promotion"
        )


def _is_bulk_promotable(draft: dict[str, Any]) -> bool:
    human_review = draft.get("human_review") if isinstance(draft.get("human_review"), dict) else {}
    recipe = draft.get("promotion_recipe") if isinstance(draft.get("promotion_recipe"), dict) else {}
    return (
        draft.get("risk_tier") == _BULK_ALLOWED_RISK_TIER
        and human_review.get("bulk_promotable") is True
        and human_review.get("mode") == "bulk"
        and recipe.get("blocked_for_bulk_acceptance") is not True
        and recipe.get("canonical_object_type") == "decision"
        and recipe.get("proposal_required") is True
    )


def _reject_explicit_forbidden_bulk_requests(draft_set: dict[str, Any]) -> None:
    requested = set(draft_set.get("promotion", {}).get("bulk_promotable_ids", []))
    if not requested:
        return
    drafts = {
        draft.get("id"): draft
        for draft in draft_set.get("draft_decisions", [])
        if isinstance(draft, dict)
    }
    forbidden = [
        draft_id
        for draft_id in sorted(requested)
        if draft_id not in drafts or not _is_bulk_promotable(drafts[draft_id])
    ]
    if forbidden:
        raise DraftBulkPromotionError(
            "promotion.bulk_promotable_ids contains non-bulk-promotable draft decisions: "
            + ", ".join(forbidden)
        )


def _bulk_target_sessions(
    candidates: list[str],
    *,
    session_id: str | None,
    session_map: dict[str, str] | None,
) -> dict[str, str]:
    if not candidates:
        return {}
    targets: dict[str, str] = {}
    if session_id:
        targets[candidates[0]] = session_id
        return targets
    assert session_map is not None
    for draft_id in candidates:
        target_session_id = session_map.get(draft_id)
        if not isinstance(target_session_id, str) or not target_session_id.strip():
            raise DraftBulkPromotionError(f"session_map is missing draft decision {draft_id}")
        targets[draft_id] = target_session_id.strip()
    by_session: dict[str, list[str]] = {}
    for draft_id, target_session_id in targets.items():
        by_session.setdefault(target_session_id, []).append(draft_id)
    duplicated = {
        target_session_id: draft_ids
        for target_session_id, draft_ids in by_session.items()
        if len(draft_ids) > 1
    }
    if duplicated:
        details = "; ".join(
            f"{target_session_id}: {', '.join(draft_ids)}"
            for target_session_id, draft_ids in sorted(duplicated.items())
        )
        raise DraftBulkPromotionError(
            "session_map assigns multiple draft decisions to the same session: " + details
        )
    return targets


def _preflight_bulk_promotions(
    bundle: dict[str, Any],
    draft_set: dict[str, Any],
    candidates: list[str],
    *,
    target_sessions: dict[str, str],
    draft_set_id: str,
) -> None:
    for draft_id in candidates:
        draft = _require_draft_decision(draft_set, draft_id)
        _validate_promotion_recipe(draft)
        _require_bulk_promotable(draft)
        decision_id, option_id, proposal_id, risk_id = _canonical_ids(draft_set_id, draft_id)
        session = _require_bulk_session(bundle, draft_id, target_sessions[draft_id])
        existing = _find_promoted_decision(bundle, draft_set_id, draft_id)
        if existing is not None:
            proposal = latest_proposal_for_decision(bundle["project_state"], existing["id"])
            if proposal is None:
                raise DraftBulkPromotionError(
                    f"draft decision {draft_id} was promoted to {existing['id']} "
                    "but has no canonical proposal"
                )
            continue
        _require_no_other_active_proposal(bundle, session, decision_id)
        _require_no_id_collision(bundle, decision_id, "decision")
        _require_no_id_collision(bundle, option_id, "option")
        _require_no_id_collision(bundle, proposal_id, "proposal")
        if _needs_risk_scaffold(draft):
            _require_no_id_collision(bundle, risk_id, "risk")
        _require_supporting_objects(bundle, draft, decision_id)


def _require_bulk_session(bundle: dict[str, Any], draft_id: str, session_id: str) -> dict[str, Any]:
    try:
        return _require_mutable_session(bundle, session_id)
    except ValueError as exc:
        raise DraftBulkPromotionError(
            f"session_map target for draft decision {draft_id} is invalid: {exc}"
        ) from exc


def _bulk_skips(draft_set: dict[str, Any]) -> list[dict[str, Any]]:
    skipped = []
    for draft in draft_set.get("draft_decisions", []):
        if not isinstance(draft, dict) or _is_bulk_promotable(draft):
            continue
        reason = "risk_tier must be low" if draft.get("risk_tier") != _BULK_ALLOWED_RISK_TIER else "requires individual promotion"
        skipped.append({"draft_decision_id": draft.get("id"), "reason": reason})
    return skipped


def _current_project_head(bundle: dict[str, Any]) -> str:
    project_head = bundle["project_state"]["state"].get("project_head")
    if not isinstance(project_head, str) or not project_head:
        raise DraftPromotionError("current project_head is unavailable")
    return project_head


def _project_head_at_generation(draft_set: dict[str, Any]) -> str:
    value = draft_set.get("source_context", {}).get("project_head_at_generation")
    if not isinstance(value, str) or not value:
        raise DraftPromotionError("draft set project_head_at_generation is unavailable")
    return value


def _canonical_decision_payload(
    decision_id: str,
    draft: dict[str, Any],
    origin: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": decision_id,
        "title": _decision_title(draft),
        "question": draft["question"],
        "context": _decision_context(draft),
        "kind": draft.get("kind", "choice"),
        "priority": draft.get("priority", "P1"),
        "frontier": draft.get("frontier", "later"),
        "resolvable_by": "human",
        "reversibility": _decision_reversibility(draft.get("reversibility")),
        "notes": _decision_notes(draft),
        "bundle_id": origin["draft_set_id"],
        "draft_origin": deepcopy(origin),
        "acceptance_mode_allowed": _acceptance_modes(draft),
        "layer": draft.get("layer"),
        "draft_risk_tier": draft.get("risk_tier"),
        "draft_evidence_coverage": deepcopy(draft.get("evidence_coverage", {})),
        "status": "unresolved",
    }


def _decision_title(draft: dict[str, Any]) -> str:
    title = f"Decide: {draft['question']}"
    return title if len(title) <= 120 else title[:117].rstrip() + "..."


def _decision_context(draft: dict[str, Any]) -> str:
    parts = [
        f"Draft question: {draft['question']}",
        f"Draft recommendation: {draft['recommendation']}",
        f"Draft rationale: {draft['rationale']}",
    ]
    missing = draft.get("evidence_coverage", {}).get("missing", [])
    if missing:
        parts.append("Missing evidence: " + "; ".join(str(item) for item in missing))
    return "\n".join(parts)


def _decision_notes(draft: dict[str, Any]) -> list[str]:
    notes = [
        f"Promoted from draft decision {draft['id']}.",
        f"Draft risk tier: {draft['risk_tier']}.",
    ]
    reason = draft.get("human_review", {}).get("reason")
    if reason:
        notes.append(f"Human review note: {reason}")
    return notes


def _draft_origin(
    draft_set_id: str,
    draft_decision_id: str,
    *,
    generated_head: str,
    current_head: str,
    promoted_at: str,
    promotion_mode: str,
    stale_promoted: bool,
    draft: dict[str, Any],
) -> dict[str, Any]:
    return {
        "draft_set_id": draft_set_id,
        "draft_decision_id": draft_decision_id,
        "project_head_at_generation": generated_head,
        "project_head_before_promotion": current_head,
        "promoted_at": promoted_at,
        "promotion_mode": promotion_mode,
        "promotion_version": PROMOTION_VERSION,
        "stale_at_promotion": stale_promoted,
        "stale_promoted": stale_promoted,
        "acceptance_mode_allowed": _acceptance_modes(draft),
        "blocked_for_bulk_acceptance": draft["promotion_recipe"]["blocked_for_bulk_acceptance"],
    }


def _proposal_if_not(draft: dict[str, Any]) -> str:
    alternatives = draft.get("alternatives", [])
    if alternatives:
        rendered = []
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            option = str(alternative.get("option") or "").strip()
            reason = str(alternative.get("reason_not_recommended") or "").strip()
            if option and reason:
                rendered.append(f"{option}: {reason}")
        if rendered:
            return "Alternative options considered: " + "; ".join(rendered)
    return "No alternative was recorded in the draft set. Return to the review queue before accepting if this is material."


def _acceptance_modes(draft: dict[str, Any]) -> list[str]:
    recipe = draft.get("promotion_recipe", {})
    modes = recipe.get("acceptance_mode_allowed", [])
    if not isinstance(modes, list):
        return []
    return sorted({str(mode) for mode in modes if str(mode)})


def _decision_reversibility(value: Any) -> str:
    return {
        "reversible": "reversible",
        "partially_reversible": "hard-to-reverse",
        "hard-to-reverse": "hard-to-reverse",
        "irreversible": "irreversible",
        "other": "unknown",
    }.get(str(value), "unknown")


def _risk_reversibility(value: Any) -> str:
    return {
        "reversible": "reversible",
        "partially_reversible": "partially_reversible",
        "hard-to-reverse": "partially_reversible",
        "irreversible": "irreversible",
        "other": "partially_reversible",
    }.get(str(value), "partially_reversible")


def _needs_risk_scaffold(draft: dict[str, Any]) -> bool:
    return draft.get("risk_tier") in RISK_SCAFFOLD_TIERS


def _risk_scaffold(
    suffix: str,
    draft: dict[str, Any],
    *,
    origin: dict[str, Any],
    decision_id: str,
) -> dict[str, Any]:
    risk_id = f"R-draft-{suffix}"
    risk_tier = draft["risk_tier"]
    severity = "critical" if risk_tier == "critical" else "high" if risk_tier == "high" else "medium"
    approval_threshold = {
        "medium": "explicit_acceptance",
        "high": "human_review",
        "critical": "external_review",
    }[risk_tier]
    statement = f"Draft decision {draft['id']} was promoted with risk_tier={risk_tier}."
    return {
        "id": risk_id,
        "title": f"Promotion risk: {_decision_title(draft)}",
        "body": "Generated from draft decision risk_tier.",
        "status": "open",
        "metadata": {
            "statement": statement,
            "severity": severity,
            "likelihood": "medium",
            "risk_tier": risk_tier,
            "reversibility": _risk_reversibility(draft.get("reversibility")),
            "mitigation_object_ids": [],
            "approval_threshold": approval_threshold,
            "draft_origin": deepcopy(origin),
            "target_decision_id": decision_id,
        },
        "rationale": f"Promoted draft risk tier is {risk_tier}.",
    }


def _supporting_object_ids(draft: dict[str, Any]) -> list[str]:
    coverage = draft.get("evidence_coverage")
    if not isinstance(coverage, dict):
        return []
    return stable_unique(str(item).strip() for item in coverage.get("supporting_object_ids", []) if str(item).strip())


def _require_supporting_objects(bundle: dict[str, Any], draft: dict[str, Any], decision_id: str) -> None:
    for supporting_id in _supporting_object_ids(draft):
        if _find_object(bundle, supporting_id) is None:
            raise DraftDecisionNotPromotableError(
                f"supporting_object_id {supporting_id} referenced by {draft.get('id')} does not exist"
            )
        link_id = f"L-{supporting_id}-supports-{decision_id}"
        if _find_link(bundle, link_id) is not None:
            raise DraftDecisionNotPromotableError(f"supporting link id collision: {link_id}")


def _find_promoted_decision(
    bundle: dict[str, Any],
    draft_set_id: str,
    draft_decision_id: str,
) -> dict[str, Any] | None:
    matches = []
    for obj in bundle["project_state"].get("objects", []):
        if obj.get("type") != "decision":
            continue
        origin = obj.get("metadata", {}).get("draft_origin")
        if not isinstance(origin, dict):
            continue
        if origin.get("draft_set_id") == draft_set_id and origin.get("draft_decision_id") == draft_decision_id:
            matches.append(obj)
    if len(matches) > 1:
        raise DraftPromotionError(
            f"multiple canonical decisions reference draft decision {draft_decision_id}"
        )
    return matches[0] if matches else None


def _require_no_id_collision(bundle: dict[str, Any], object_id: str, expected_type: str) -> None:
    for obj in bundle["project_state"].get("objects", []):
        if obj.get("id") == object_id:
            raise DraftPromotionError(
                f"canonical {expected_type} id collision while promoting draft: {object_id}"
            )


def _find_object(bundle: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    for obj in bundle["project_state"].get("objects", []):
        if obj.get("id") == object_id:
            return obj
    return None


def _find_link(bundle: dict[str, Any], link_id: str) -> dict[str, Any] | None:
    for link in bundle["project_state"].get("links", []):
        if link.get("id") == link_id:
            return link
    return None


def _canonical_ids(draft_set_id: str, draft_decision_id: str) -> tuple[str, str, str, str]:
    suffix = _stable_suffix(draft_set_id, draft_decision_id)
    return (
        f"D-draft-{suffix}",
        f"O-option-draft-{suffix}",
        f"P-draft-{suffix}",
        f"R-draft-{suffix}",
    )


def _promotion_log_path(ai_dir: str | Path, draft_set_id: str) -> Path:
    return draft_set_dir(ai_dir, draft_set_id) / "promotion-log.jsonl"


def _sidecar_promoted_decision_ids(draft_set: dict[str, Any]) -> list[str]:
    promotion = draft_set.get("promotion")
    if not isinstance(promotion, dict):
        return []
    return stable_unique(
        str(item).strip()
        for item in promotion.get("promoted_decision_ids", [])
        if str(item).strip()
    )


def _promotion_log_promoted_decision_ids(log_path: Path) -> tuple[list[str], list[str]]:
    if not log_path.exists():
        return [], []
    ids: list[str] = []
    errors: list[str] = []
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: {exc.msg}")
            continue
        draft_id = str(record.get("draft_decision_id") or "").strip() if isinstance(record, dict) else ""
        if draft_id:
            ids.append(draft_id)
    return stable_unique(ids), errors


def _canonical_promotions(
    bundle: dict[str, Any],
    draft_set_id: str,
    *,
    events_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    project_state = bundle["project_state"]
    promotions: list[dict[str, Any]] = []
    for obj in project_state.get("objects", []):
        if obj.get("type") != "decision":
            continue
        origin = _dict_field(_dict_field(obj, "metadata"), "draft_origin")
        if origin.get("draft_set_id") != draft_set_id:
            continue
        draft_decision_id = str(origin.get("draft_decision_id") or "").strip()
        if not draft_decision_id:
            continue
        proposal = latest_proposal_for_decision(project_state, obj["id"])
        proposal_metadata = _dict_field(proposal, "metadata") if proposal else {}
        proposal_id = proposal.get("id") if proposal else None
        option_id = _proposal_option_id(project_state, proposal_id)
        event_ids = _promotion_source_event_ids(project_state, obj, proposal, option_id)
        promotions.append(
            {
                "draft_set_id": draft_set_id,
                "draft_decision_id": draft_decision_id,
                "decision_id": obj["id"],
                "proposal_id": proposal_id,
                "option_id": option_id,
                "question_id": proposal_metadata.get("question_id"),
                "session_id": proposal_metadata.get("origin_session_id"),
                "risk_object_ids": _promotion_risk_object_ids(project_state, obj["id"]),
                "tx_id": _first_tx_id(event_ids, events_by_id),
                "project_head_at_generation": origin.get("project_head_at_generation"),
                "project_head_before_promotion": origin.get("project_head_before_promotion"),
                "project_head_after_promotion": origin.get("project_head_after_promotion"),
                "promoted_at": origin.get("promoted_at") or obj.get("created_at"),
                "event_ids": event_ids,
                "promotion_version": origin.get("promotion_version") or PROMOTION_VERSION,
            }
        )
    return sorted(
        promotions,
        key=lambda item: (
            str(item.get("promoted_at") or ""),
            str(item.get("draft_decision_id") or ""),
            str(item.get("decision_id") or ""),
        ),
    )


def _reconciled_promotion_record(promotion: dict[str, Any], *, reconciled_at: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entry_type": "draft_decision_promoted",
        "promotion_version": promotion.get("promotion_version") or PROMOTION_VERSION,
        "draft_set_id": promotion["draft_set_id"],
        "draft_decision_id": promotion["draft_decision_id"],
        "session_id": promotion.get("session_id"),
        "decision_id": promotion["decision_id"],
        "proposal_id": promotion.get("proposal_id"),
        "option_id": promotion.get("option_id"),
        "question_id": promotion.get("question_id"),
        "risk_object_ids": promotion.get("risk_object_ids", []),
        "tx_id": promotion.get("tx_id"),
        "project_head_at_generation": promotion.get("project_head_at_generation"),
        "project_head_before_promotion": promotion.get("project_head_before_promotion"),
        "project_head_after_promotion": promotion.get("project_head_after_promotion"),
        "promoted_at": promotion.get("promoted_at"),
        "event_ids": promotion.get("event_ids", []),
        "reconstructed": True,
        "reconciled_at": reconciled_at,
        "reconciled_by": "reconcile-draft-promotions",
    }


def _proposal_option_id(project_state: dict[str, Any], proposal_id: Any) -> str | None:
    if not proposal_id:
        return None
    for link in project_state.get("links", []):
        if link.get("source_object_id") == proposal_id and link.get("relation") == "recommends":
            option_id = str(link.get("target_object_id") or "").strip()
            return option_id or None
    return None


def _promotion_risk_object_ids(project_state: dict[str, Any], decision_id: str) -> list[str]:
    object_types = {
        obj.get("id"): obj.get("type")
        for obj in project_state.get("objects", [])
        if obj.get("id")
    }
    return stable_unique(
        str(link.get("source_object_id")).strip()
        for link in project_state.get("links", [])
        if link.get("relation") == "challenges"
        and link.get("target_object_id") == decision_id
        and object_types.get(link.get("source_object_id")) == "risk"
        and str(link.get("source_object_id") or "").strip()
    )


def _promotion_source_event_ids(
    project_state: dict[str, Any],
    decision: dict[str, Any],
    proposal: dict[str, Any] | None,
    option_id: str | None,
) -> list[str]:
    object_ids = {decision.get("id")}
    if proposal:
        object_ids.add(proposal.get("id"))
    if option_id:
        object_ids.add(option_id)
    object_ids.update(_promotion_risk_object_ids(project_state, str(decision.get("id"))))
    event_ids: list[str] = []
    for obj in project_state.get("objects", []):
        if obj.get("id") in object_ids:
            event_ids.extend(_string_values(obj.get("source_event_ids", [])))
    for link in project_state.get("links", []):
        if link.get("source_object_id") in object_ids or link.get("target_object_id") in object_ids:
            event_ids.extend(_string_values(link.get("source_event_ids", [])))
    return stable_unique(event_ids)


def _first_tx_id(event_ids: list[str], events_by_id: dict[str, dict[str, Any]]) -> str | None:
    for event_id in event_ids:
        tx_id = events_by_id.get(event_id, {}).get("tx_id")
        if isinstance(tx_id, str) and tx_id:
            return tx_id
    return None


def _string_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _dict_field(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _record_promotion_sidecar(
    ai_dir: str | Path,
    draft_set_id: str,
    draft_decision_id: str,
    *,
    session_id: str,
    decision_id: str,
    proposal_id: str,
    option_id: str,
    question_id: str,
    promoted_at: str,
    materialized: dict[str, Any],
    draft_set: dict[str, Any],
) -> dict[str, Any]:
    log_path = _promotion_log_path(ai_dir, draft_set_id)
    draft_set_path = draft_set_dir(ai_dir, draft_set_id) / "draft-set.json"
    try:
        updated_draft_set = deepcopy(draft_set)
        promotion = updated_draft_set.setdefault("promotion", {})
        promotion["promoted_decision_ids"] = stable_unique(
            [*promotion.get("promoted_decision_ids", []), draft_decision_id]
        )
        promotion.setdefault("bulk_promotable_ids", [])
        promotion.setdefault("individual_review_required_ids", [])
        _atomic_write_json(draft_set_path, updated_draft_set)

        record = _promotion_record(
            draft_set_id,
            draft_decision_id,
            session_id=session_id,
            decision_id=decision_id,
            proposal_id=proposal_id,
            option_id=option_id,
            question_id=question_id,
            promoted_at=promoted_at,
            materialized=materialized,
            draft_set=draft_set,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return {
            "updated": True,
            "promotion_log_path": str(log_path),
            "draft_set_path": str(draft_set_path),
        }
    except Exception as exc:  # pragma: no cover - defensive; canonical promotion remains authoritative.
        return {
            "updated": False,
            "promotion_log_path": str(log_path),
            "draft_set_path": str(draft_set_path),
            "error": str(exc),
        }


def _promotion_record(
    draft_set_id: str,
    draft_decision_id: str,
    *,
    session_id: str,
    decision_id: str,
    proposal_id: str,
    option_id: str,
    question_id: str,
    promoted_at: str,
    materialized: dict[str, Any],
    draft_set: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entry_type": "draft_decision_promoted",
        "promotion_version": PROMOTION_VERSION,
        "draft_set_id": draft_set_id,
        "draft_decision_id": draft_decision_id,
        "session_id": session_id,
        "decision_id": decision_id,
        "proposal_id": proposal_id,
        "option_id": option_id,
        "question_id": question_id,
        "risk_object_ids": materialized["risk_object_ids"],
        "tx_id": materialized["tx_id"],
        "project_head_at_generation": _project_head_at_generation(draft_set),
        "project_head_before_promotion": materialized["project_head_before_promotion"],
        "project_head_after_promotion": materialized["project_head_after_promotion"],
        "promoted_at": promoted_at,
        "event_ids": materialized["event_ids"],
        "event_types": [event["event_type"] for event in materialized["events"]],
    }


def _stable_suffix(*parts: str) -> str:
    material = "|".join(parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
