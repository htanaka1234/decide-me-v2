from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable

from decide_me.events import utc_now

if TYPE_CHECKING:
    from decide_me.domains.apply import InterviewPolicy
    from decide_me.domains.model import EvidenceRequirementSpec, SafetyRuleSpec
    from decide_me.domains.registry import DomainRegistry


SAFETY_GATE_SCHEMA_VERSION = 1
SAFETY_APPROVAL_ARTIFACT_TYPE = "safety_gate_approval"
_RISK_TIER_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_APPROVAL_THRESHOLD_RANK = {
    "none": 0,
    "explicit_acceptance": 1,
    "human_review": 2,
    "external_review": 3,
}
APPROVAL_LEVEL_RANK = {
    "explicit_acceptance": 1,
    "human_review": 2,
    "external_review": 3,
}
_BLOCKING_RISK_TIERS_FOR_INSUFFICIENT_EVIDENCE = {"critical"}
_APPROVAL_RISK_TIERS_FOR_INSUFFICIENT_EVIDENCE = {"medium", "high"}
_REVERSIBILITY_RANK = {
    "unknown": 0,
    "reversible": 1,
    "partially_reversible": 2,
    "irreversible": 3,
}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_DECISION_REVERSIBILITY_MAP = {
    "reversible": "reversible",
    "hard-to-reverse": "partially_reversible",
    "irreversible": "irreversible",
    "unknown": "unknown",
}


def evaluate_safety_gate(
    project_state: dict[str, Any],
    object_id: str,
    *,
    now: str | None = None,
    include_approvals: bool = True,
    domain_registry: DomainRegistry | None = None,
) -> dict[str, Any]:
    as_of, reference = _reference_time(project_state, now)
    objects_by_id = _objects_by_id(project_state)
    target = objects_by_id.get(object_id)
    if target is None:
        raise ValueError(f"unknown object_id: {object_id}")

    links = list(project_state.get("links", []))
    evidence = _evidence_items(target, objects_by_id, links, reference=reference)
    assumptions = _assumption_items(target, objects_by_id, links, reference=reference)
    risks = _risk_items(target, objects_by_id, links)
    domain_requirements, domain_safety_rules = _domain_overlay(
        target,
        evidence,
        risks,
        domain_registry=domain_registry,
    )

    evidence_coverage = _evidence_coverage(evidence)
    risk_tier = _max_ranked((risk["risk_tier"] for risk in risks), _RISK_TIER_RANK, default="none")
    approval_threshold = _max_ranked(
        (risk["approval_threshold"] for risk in risks),
        _APPROVAL_THRESHOLD_RANK,
        default="none",
    )
    approval_threshold = _max_ranked(
        (rule["approval_threshold"] for rule in domain_safety_rules),
        _APPROVAL_THRESHOLD_RANK,
        default=approval_threshold,
    )
    reversibility = _max_reversibility(target, risks)
    verification_gap = _verification_gap(project_state, target)
    blocking_reasons = _blocking_reasons(target, evidence_coverage, risk_tier, verification_gap)
    warning_reasons = _warning_reasons(risk_tier, reversibility, assumptions, evidence, evidence_coverage)
    approval_reasons = _approval_reasons(
        risk_tier,
        reversibility,
        approval_threshold,
        evidence_coverage,
        verification_gap,
        assumptions,
    )
    if any(not item["satisfied"] for item in domain_requirements):
        approval_reasons = _sorted_strings([*approval_reasons, "domain_required_evidence_missing"])
    approval_required = bool(approval_reasons)
    source_link_ids = _source_link_ids(evidence, assumptions, risks)
    digest_inputs = _digest_inputs(
        target,
        risk_tier=risk_tier,
        reversibility=reversibility,
        evidence_coverage=evidence_coverage,
        approval_threshold=approval_threshold,
        blocking_reasons=blocking_reasons,
        warning_reasons=warning_reasons,
        approval_reasons=approval_reasons,
        evidence=evidence,
        assumptions=assumptions,
        risks=risks,
        domain_requirements=domain_requirements,
        domain_safety_rules=domain_safety_rules,
        verification_gap=verification_gap,
        source_link_ids=source_link_ids,
    )
    gate_digest = _gate_digest(digest_inputs)
    approval_artifact_ids = (
        _matching_approval_artifact_ids(project_state, target["id"], gate_digest, approval_threshold, reference)
        if include_approvals
        else []
    )
    approval_satisfied = bool(approval_required and approval_artifact_ids)
    gate_status = "blocked" if blocking_reasons else "passed" if approval_satisfied else "needs_approval" if approval_required else "passed"

    return {
        "object_id": target["id"],
        "object_type": target["type"],
        "title": target.get("title"),
        "status": target.get("status"),
        "as_of": as_of,
        "gate_status": gate_status,
        "risk_tier": risk_tier,
        "reversibility": reversibility,
        "evidence_coverage": evidence_coverage,
        "approval_required": approval_required,
        "approval_satisfied": approval_satisfied,
        "approval_artifact_ids": approval_artifact_ids,
        "approval_threshold": approval_threshold,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "approval_reasons": approval_reasons,
        "gate_digest": gate_digest,
        "digest_inputs": digest_inputs,
        "evidence": evidence,
        "assumptions": assumptions,
        "risks": risks,
        "domain_requirements": domain_requirements,
        "domain_safety_rules": domain_safety_rules,
        "source_link_ids": source_link_ids,
    }


def build_safety_gate_report(
    project_state: dict[str, Any],
    object_ids: Iterable[str] | None = None,
    *,
    now: str | None = None,
    domain_registry: DomainRegistry | None = None,
) -> dict[str, Any]:
    ids = list(object_ids) if object_ids is not None else _default_gate_object_ids(project_state)
    results = [
        evaluate_safety_gate(project_state, object_id, now=now, domain_registry=domain_registry)
        for object_id in ids
    ]
    state = project_state.get("state", {})
    return {
        "schema_version": SAFETY_GATE_SCHEMA_VERSION,
        "project_head": state.get("project_head"),
        "generated_at": state.get("updated_at"),
        "summary": {
            "evaluated_count": len(results),
            "by_gate_status": _count_by(results, "gate_status"),
            "approval_required_count": sum(1 for result in results if result["approval_required"]),
            "blocking_count": sum(1 for result in results if result["blocking_reasons"]),
        },
        "results": results,
    }


def _evidence_items(
    target: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
    *,
    reference: datetime,
) -> list[dict[str, Any]]:
    items = []
    for link in links:
        if link.get("target_object_id") != target["id"] or link.get("relation") not in {"supports", "verifies", "challenges"}:
            continue
        obj = objects_by_id.get(link.get("source_object_id"))
        if not obj or obj.get("type") != "evidence" or not _is_live(obj):
            continue
        metadata = obj.get("metadata", {})
        items.append(
            {
                "object_id": obj["id"],
                "status": obj.get("status"),
                "relation": link["relation"],
                "link_id": link["id"],
                "source": metadata.get("source"),
                "source_ref": metadata.get("source_ref"),
                "summary": metadata.get("summary"),
                "confidence": metadata.get("confidence"),
                "freshness": metadata.get("freshness"),
                "observed_at": metadata.get("observed_at"),
                "valid_until": metadata.get("valid_until"),
                "is_stale": _is_stale_evidence_metadata(metadata, reference),
                "domain_evidence_type": metadata.get("domain_evidence_type"),
                "evidence_requirement_id": metadata.get("evidence_requirement_id"),
            }
        )
    return sorted(items, key=lambda item: (item["object_id"], item["relation"], item["link_id"]))


def _assumption_items(
    target: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
    *,
    reference: datetime,
) -> list[dict[str, Any]]:
    items_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        obj: dict[str, Any] | None = None
        relation = link.get("relation")
        if link.get("target_object_id") == target["id"] and relation in {"constrains", "invalidates"}:
            obj = objects_by_id.get(link.get("source_object_id"))
        elif link.get("source_object_id") == target["id"] and relation in {"requires", "derived_from"}:
            obj = objects_by_id.get(link.get("target_object_id"))
        if not obj or obj.get("type") != "assumption" or not _is_live(obj):
            continue
        metadata = obj.get("metadata", {})
        items_by_key[(obj["id"], relation, link["id"])] = {
            "object_id": obj["id"],
            "status": obj.get("status"),
            "relation": relation,
            "link_id": link["id"],
            "statement": metadata.get("statement"),
            "confidence": metadata.get("confidence"),
            "validation": metadata.get("validation"),
            "invalidates_if_false": _sorted_strings(metadata.get("invalidates_if_false", [])),
            "expires_at": metadata.get("expires_at"),
            "owner": metadata.get("owner"),
            "is_expired": _is_expired_assumption_metadata(metadata, reference),
        }
    return [items_by_key[key] for key in sorted(items_by_key)]


def _risk_items(
    target: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        obj: dict[str, Any] | None = None
        relation = link.get("relation")
        if link.get("target_object_id") == target["id"] and relation in {"challenges", "constrains", "invalidates"}:
            obj = objects_by_id.get(link.get("source_object_id"))
        elif link.get("source_object_id") == target["id"] and relation in {"blocked_by", "addresses", "mitigates"}:
            obj = objects_by_id.get(link.get("target_object_id"))
        if obj and obj.get("type") == "risk" and _is_live(obj):
            items_by_key[(obj["id"], relation, link["id"])] = _risk_item(obj, relation=relation, link_id=link["id"])

    for obj in objects_by_id.values():
        if obj.get("type") != "risk" or not _is_live(obj):
            continue
        metadata = obj.get("metadata", {})
        if target["id"] in set(metadata.get("mitigation_object_ids", [])):
            items_by_key[(obj["id"], "mitigation_metadata", "")] = _risk_item(
                obj,
                relation="mitigation_metadata",
                link_id=None,
            )

    return [items_by_key[key] for key in sorted(items_by_key)]


def _risk_item(obj: dict[str, Any], *, relation: str, link_id: str | None) -> dict[str, Any]:
    metadata = obj.get("metadata", {})
    return {
        "object_id": obj["id"],
        "status": obj.get("status"),
        "relation": relation,
        "link_id": link_id,
        "statement": metadata.get("statement"),
        "severity": metadata.get("severity"),
        "likelihood": metadata.get("likelihood"),
        "risk_tier": metadata.get("risk_tier"),
        "reversibility": metadata.get("reversibility"),
        "mitigation_object_ids": _sorted_strings(metadata.get("mitigation_object_ids", [])),
        "approval_threshold": metadata.get("approval_threshold"),
        "domain_risk_type": metadata.get("domain_risk_type"),
    }


def _domain_overlay(
    target: dict[str, Any],
    evidence: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    *,
    domain_registry: DomainRegistry | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if domain_registry is None:
        return [], []
    from decide_me.domains.apply import build_interview_policy_from_metadata

    policy = build_interview_policy_from_metadata(
        domain_registry,
        target.get("metadata", {}),
        label=f"object {target['id']}.metadata",
    )
    if policy.is_generic:
        return [], []
    return (
        _domain_requirements(policy, target, evidence),
        _domain_safety_rules(policy, risks),
    )


def _domain_requirements(
    policy: InterviewPolicy,
    target: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if target.get("type") != "decision":
        return []
    decision_type_id = target.get("metadata", {}).get("domain_decision_type")
    if not decision_type_id:
        return []
    decision_type = policy.decision_type(decision_type_id)
    if decision_type is None:
        raise ValueError(f"object {target['id']}.metadata.domain_decision_type is not defined: {decision_type_id}")

    requirements_by_id = {item.id: item for item in policy.pack.evidence_requirements}
    items = []
    for requirement_id in decision_type.required_evidence:
        requirement = requirements_by_id[requirement_id]
        matched = _matching_domain_evidence(requirement, evidence)
        items.append(
            {
                "pack_id": policy.pack_id,
                "decision_type": decision_type.id,
                "required_evidence_id": requirement.id,
                "domain_evidence_type": requirement.domain_evidence_type,
                "label": requirement.label,
                "evidence_source": requirement.evidence_source,
                "min_confidence": requirement.min_confidence,
                "freshness_required": requirement.freshness_required,
                "satisfied": bool(matched),
                "satisfied_by_object_ids": sorted(item["object_id"] for item in matched),
                "reason": (
                    f"{decision_type.label} requires {requirement.label}."
                    if not matched
                    else f"{requirement.label} is linked to {decision_type.label}."
                ),
            }
        )
    return items


def _matching_domain_evidence(
    requirement: EvidenceRequirementSpec,
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        item
        for item in evidence
        if item.get("relation") in {"supports", "verifies"}
        and (
            item.get("evidence_requirement_id") == requirement.id
            or item.get("domain_evidence_type") == requirement.domain_evidence_type
        )
        and _evidence_meets_requirement_quality(item, requirement)
    ]


def _evidence_meets_requirement_quality(
    item: dict[str, Any],
    requirement: EvidenceRequirementSpec,
) -> bool:
    confidence = item.get("confidence")
    if _CONFIDENCE_RANK.get(confidence, 0) < _CONFIDENCE_RANK[requirement.min_confidence]:
        return False
    freshness = item.get("freshness")
    if requirement.freshness_required == "unknown":
        return True
    if freshness != requirement.freshness_required:
        return False
    if requirement.freshness_required == "current" and item.get("is_stale"):
        return False
    return True


def _domain_safety_rules(
    policy: InterviewPolicy,
    risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    applied = []
    for rule in policy.pack.safety_rules:
        matched = _risks_matching_rule(rule, risks)
        if not matched:
            continue
        applied.append(
            {
                "pack_id": policy.pack_id,
                "rule_id": rule.id,
                "approval_threshold": rule.approval_threshold,
                "reason": rule.reason,
                "matched_risk_types": _sorted_strings(
                    risk["domain_risk_type"] for risk in matched if risk.get("domain_risk_type")
                ),
                "matched_risk_object_ids": sorted(risk["object_id"] for risk in matched),
            }
        )
    return sorted(applied, key=lambda item: item["rule_id"])


def _risks_matching_rule(rule: SafetyRuleSpec, risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risk_types = set(rule.applies_when.risk_types)
    return [risk for risk in risks if risk.get("domain_risk_type") in risk_types]


def _evidence_coverage(evidence: list[dict[str, Any]]) -> str:
    if any(item["relation"] == "challenges" for item in evidence):
        return "challenged"
    for item in evidence:
        if item["relation"] in {"supports", "verifies"}:
            if (
                item.get("confidence") in {"medium", "high"}
                and item.get("freshness") == "current"
                and not item.get("is_stale")
            ):
                return "sufficient"
    return "insufficient"


def _blocking_reasons(
    target: dict[str, Any],
    evidence_coverage: str,
    risk_tier: str,
    verification_gap: dict[str, Any] | None,
) -> list[str]:
    reasons = []
    if target.get("status") == "invalidated":
        reasons.append("target_invalidated")
    if risk_tier == "critical":
        reasons.append("critical_risk_tier")
    if evidence_coverage == "insufficient" and risk_tier in _BLOCKING_RISK_TIERS_FOR_INSUFFICIENT_EVIDENCE:
        reasons.append("insufficient_evidence")
    elif evidence_coverage == "challenged":
        reasons.append("challenged_evidence")
    if verification_gap and verification_gap["gap_severity"] == "high":
        reasons.append("completed_action_verification_gap")
    return reasons


def _approval_reasons(
    risk_tier: str,
    reversibility: str,
    approval_threshold: str,
    evidence_coverage: str,
    verification_gap: dict[str, Any] | None,
    assumptions: list[dict[str, Any]],
) -> list[str]:
    reasons = []
    if risk_tier == "high":
        reasons.append("high_risk_tier")
    if reversibility == "irreversible":
        reasons.append("irreversible_change")
    if evidence_coverage == "insufficient" and risk_tier in _APPROVAL_RISK_TIERS_FOR_INSUFFICIENT_EVIDENCE:
        reasons.append("insufficient_evidence_requires_approval")
    if verification_gap and verification_gap["gap_severity"] == "medium":
        reasons.append("action_verification_gap")
    if any(item.get("is_expired") for item in assumptions) and risk_tier in {"high", "critical"}:
        reasons.append("expired_assumption_review_required")
    if approval_threshold == "external_review":
        reasons.append("external_review_required")
    elif approval_threshold == "human_review":
        reasons.append("human_review_required")
    elif approval_threshold == "explicit_acceptance":
        reasons.append("explicit_acceptance_required")
    return _sorted_strings(reasons)


def _warning_reasons(
    risk_tier: str,
    reversibility: str,
    assumptions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    evidence_coverage: str,
) -> list[str]:
    reasons = []
    if risk_tier == "medium":
        reasons.append("medium_risk_tier")
    if reversibility == "partially_reversible":
        reasons.append("partially_reversible_change")
    if any(item.get("confidence") == "low" for item in assumptions):
        reasons.append("low_confidence_assumption")
    if any(item.get("is_expired") for item in assumptions):
        reasons.append("expired_assumption")
    if any(item.get("is_stale") and item.get("relation") in {"supports", "verifies"} for item in evidence):
        reasons.append("stale_supporting_evidence")
    if evidence_coverage == "insufficient" and risk_tier in {"none", "low"}:
        reasons.append("insufficient_evidence")
    return _sorted_strings(reasons)


def _max_reversibility(target: dict[str, Any], risks: list[dict[str, Any]]) -> str:
    values = [risk.get("reversibility") for risk in risks if risk.get("reversibility")]
    if target.get("type") in {"action", "decision"}:
        target_value = target.get("metadata", {}).get("reversibility")
        if target_value:
            values.append(_DECISION_REVERSIBILITY_MAP.get(target_value, target_value))
    return _max_ranked(values, _REVERSIBILITY_RANK, default="unknown")


def _digest_inputs(
    target: dict[str, Any],
    *,
    risk_tier: str,
    reversibility: str,
    evidence_coverage: str,
    approval_threshold: str,
    blocking_reasons: list[str],
    warning_reasons: list[str],
    approval_reasons: list[str],
    evidence: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    domain_requirements: list[dict[str, Any]],
    domain_safety_rules: list[dict[str, Any]],
    verification_gap: dict[str, Any] | None,
    source_link_ids: list[str],
) -> dict[str, Any]:
    return {
        "object_id": target["id"],
        "object_type": target["type"],
        "risk_tier": risk_tier,
        "reversibility": reversibility,
        "evidence_coverage": evidence_coverage,
        "approval_threshold": approval_threshold,
        "blocking_reasons": _sorted_strings(blocking_reasons),
        "warning_reasons": _sorted_strings(warning_reasons),
        "approval_reasons": _sorted_strings(approval_reasons),
        "evidence": [_digest_item(item) for item in evidence],
        "assumptions": [_digest_item(item) for item in assumptions],
        "risks": [_digest_item(item) for item in risks],
        "domain_requirements": [_digest_item(item) for item in domain_requirements],
        "domain_safety_rules": [_digest_item(item) for item in domain_safety_rules],
        "verification_gap": verification_gap,
        "source_link_ids": source_link_ids,
    }


def _digest_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in sorted(item)}


def _gate_digest(digest_inputs: dict[str, Any]) -> str:
    material = json.dumps(digest_inputs, sort_keys=True, separators=(",", ":"))
    return f"SG-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"


def _matching_approval_artifact_ids(
    project_state: dict[str, Any],
    object_id: str,
    gate_digest: str,
    approval_threshold: str,
    reference: datetime,
) -> list[str]:
    addressed_by = _approval_address_links(project_state, object_id)
    ids = []
    for obj in project_state.get("objects", []):
        if obj.get("type") != "artifact" or not _is_live(obj):
            continue
        metadata = obj.get("metadata", {})
        if metadata.get("artifact_type") != SAFETY_APPROVAL_ARTIFACT_TYPE:
            continue
        if metadata.get("target_object_id") != object_id or metadata.get("gate_digest") != gate_digest:
            continue
        if not approval_level_satisfies_threshold(metadata.get("approval_level"), approval_threshold):
            continue
        expires_at = metadata.get("expires_at")
        if expires_at and _parse_timestamp(expires_at, f"approval {obj['id']}.metadata.expires_at") < reference:
            continue
        if obj["id"] not in addressed_by:
            continue
        ids.append(obj["id"])
    return sorted(ids)


def approval_level_satisfies_threshold(approval_level: Any, approval_threshold: str) -> bool:
    return APPROVAL_LEVEL_RANK.get(approval_level, -1) >= _APPROVAL_THRESHOLD_RANK.get(approval_threshold, 999)


def _approval_address_links(project_state: dict[str, Any], object_id: str) -> dict[str, list[str]]:
    addressed_by: dict[str, list[str]] = {}
    objects_by_id = _objects_by_id(project_state)
    for link in project_state.get("links", []):
        if link.get("relation") != "addresses" or link.get("target_object_id") != object_id:
            continue
        source_id = link.get("source_object_id")
        source = objects_by_id.get(source_id)
        if not source or source.get("type") != "artifact" or not _is_live(source):
            continue
        addressed_by.setdefault(source_id, []).append(link["id"])
    return addressed_by


def _verification_gap(project_state: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    if target.get("type") != "action":
        return None
    objects_by_id = _objects_by_id(project_state)
    supporting_links = []
    for link in project_state.get("links", []):
        if link.get("target_object_id") != target["id"] or link.get("relation") not in {"supports", "verifies"}:
            continue
        obj = objects_by_id.get(link.get("source_object_id"))
        if obj and _is_live(obj) and obj.get("type") in {"evidence", "verification"}:
            supporting_links.append(link["id"])
    if supporting_links:
        return None
    return {
        "gap_reason": "missing_verification",
        "gap_severity": "high" if target.get("status") == "completed" else "medium",
        "related_link_ids": [],
    }


def _reference_time(project_state: dict[str, Any], now: str | None) -> tuple[str, datetime]:
    value = now or project_state.get("state", {}).get("updated_at") or utc_now()
    return value, _parse_timestamp(value, "safety gate as_of")


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be ISO-8601/RFC3339-like") from exc


def _is_stale_evidence_metadata(metadata: dict[str, Any], reference: datetime) -> bool:
    valid_until = metadata.get("valid_until")
    return bool(
        metadata.get("freshness") == "stale"
        or (valid_until and _parse_timestamp(valid_until, "evidence.metadata.valid_until") < reference)
    )


def _is_expired_assumption_metadata(metadata: dict[str, Any], reference: datetime) -> bool:
    expires_at = metadata.get("expires_at")
    return bool(expires_at and _parse_timestamp(expires_at, "assumption.metadata.expires_at") < reference)


def _source_link_ids(
    evidence: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
) -> list[str]:
    return _sorted_strings(
        item["link_id"]
        for item in [*evidence, *assumptions, *risks]
        if item.get("link_id")
    )


def _default_gate_object_ids(project_state: dict[str, Any]) -> list[str]:
    return sorted(
        obj["id"]
        for obj in project_state.get("objects", [])
        if obj.get("type") in {"decision", "action"} and _is_live(obj)
    )


def _objects_by_id(project_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: deepcopy(obj) for obj in project_state.get("objects", [])}


def _is_live(obj: dict[str, Any]) -> bool:
    return obj.get("status") != "invalidated"


def _max_ranked(values: Iterable[str | None], ranks: dict[str, int], *, default: str) -> str:
    best = default
    best_rank = ranks[default]
    for value in values:
        if value not in ranks:
            continue
        rank = ranks[value]
        if rank > best_rank:
            best = value
            best_rank = rank
    return best


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _sorted_strings(values: Any) -> list[str]:
    return sorted({str(value) for value in values})
