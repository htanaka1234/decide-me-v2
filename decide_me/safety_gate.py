from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


SAFETY_GATE_SCHEMA_VERSION = 1
_RISK_TIER_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_APPROVAL_THRESHOLD_RANK = {
    "none": 0,
    "explicit_acceptance": 1,
    "human_review": 2,
    "external_review": 3,
}
_REVERSIBILITY_RANK = {
    "unknown": 0,
    "reversible": 1,
    "partially_reversible": 2,
    "irreversible": 3,
}
_DECISION_REVERSIBILITY_MAP = {
    "reversible": "reversible",
    "hard-to-reverse": "partially_reversible",
    "irreversible": "irreversible",
    "unknown": "unknown",
}


def evaluate_safety_gate(project_state: dict[str, Any], object_id: str) -> dict[str, Any]:
    objects_by_id = _objects_by_id(project_state)
    target = objects_by_id.get(object_id)
    if target is None:
        raise ValueError(f"unknown object_id: {object_id}")

    links = list(project_state.get("links", []))
    evidence = _evidence_items(target, objects_by_id, links)
    assumptions = _assumption_items(target, objects_by_id, links)
    risks = _risk_items(target, objects_by_id, links)

    evidence_coverage = _evidence_coverage(evidence)
    risk_tier = _max_ranked((risk["risk_tier"] for risk in risks), _RISK_TIER_RANK, default="none")
    approval_threshold = _max_ranked(
        (risk["approval_threshold"] for risk in risks),
        _APPROVAL_THRESHOLD_RANK,
        default="none",
    )
    reversibility = _max_reversibility(target, risks)
    blocking_reasons = _blocking_reasons(target, evidence_coverage, risk_tier)
    warning_reasons = _warning_reasons(risk_tier, reversibility, assumptions)
    approval_reasons = _approval_reasons(risk_tier, reversibility, approval_threshold)
    approval_required = bool(approval_reasons)
    gate_status = "blocked" if blocking_reasons else "needs_approval" if approval_required else "passed"

    return {
        "object_id": target["id"],
        "object_type": target["type"],
        "title": target.get("title"),
        "status": target.get("status"),
        "gate_status": gate_status,
        "risk_tier": risk_tier,
        "reversibility": reversibility,
        "evidence_coverage": evidence_coverage,
        "approval_required": approval_required,
        "approval_threshold": approval_threshold,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "approval_reasons": approval_reasons,
        "evidence": evidence,
        "assumptions": assumptions,
        "risks": risks,
        "source_link_ids": _source_link_ids(evidence, assumptions, risks),
    }


def build_safety_gate_report(
    project_state: dict[str, Any],
    object_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    ids = list(object_ids) if object_ids is not None else _default_gate_object_ids(project_state)
    results = [evaluate_safety_gate(project_state, object_id) for object_id in ids]
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
            }
        )
    return sorted(items, key=lambda item: (item["object_id"], item["relation"], item["link_id"]))


def _assumption_items(
    target: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
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
    }


def _evidence_coverage(evidence: list[dict[str, Any]]) -> str:
    if any(item["relation"] == "challenges" for item in evidence):
        return "challenged"
    for item in evidence:
        if item["relation"] in {"supports", "verifies"}:
            if item.get("confidence") in {"medium", "high"} and item.get("freshness") == "current":
                return "sufficient"
    return "insufficient"


def _blocking_reasons(target: dict[str, Any], evidence_coverage: str, risk_tier: str) -> list[str]:
    reasons = []
    if target.get("status") == "invalidated":
        reasons.append("target_invalidated")
    if risk_tier == "critical":
        reasons.append("critical_risk_tier")
    if evidence_coverage == "insufficient":
        reasons.append("insufficient_evidence")
    elif evidence_coverage == "challenged":
        reasons.append("challenged_evidence")
    return reasons


def _approval_reasons(risk_tier: str, reversibility: str, approval_threshold: str) -> list[str]:
    reasons = []
    if risk_tier == "high":
        reasons.append("high_risk_tier")
    if reversibility == "irreversible":
        reasons.append("irreversible_change")
    if approval_threshold == "external_review":
        reasons.append("external_review_required")
    elif approval_threshold == "human_review":
        reasons.append("human_review_required")
    elif approval_threshold == "explicit_acceptance":
        reasons.append("explicit_acceptance_required")
    return reasons


def _warning_reasons(risk_tier: str, reversibility: str, assumptions: list[dict[str, Any]]) -> list[str]:
    reasons = []
    if risk_tier == "medium":
        reasons.append("medium_risk_tier")
    if reversibility == "partially_reversible":
        reasons.append("partially_reversible_change")
    if any(item.get("confidence") == "low" for item in assumptions):
        reasons.append("low_confidence_assumption")
    return reasons


def _max_reversibility(target: dict[str, Any], risks: list[dict[str, Any]]) -> str:
    values = [risk.get("reversibility") for risk in risks if risk.get("reversibility")]
    if target.get("type") == "decision":
        decision_value = target.get("metadata", {}).get("reversibility")
        if decision_value:
            values.append(_DECISION_REVERSIBILITY_MAP.get(decision_value, "unknown"))
    return _max_ranked(values, _REVERSIBILITY_RANK, default="unknown")


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
