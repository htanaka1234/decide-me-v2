from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_TIMESTAMP = "2026-04-23T12:00:00Z"


def evidence_metadata(
    *,
    source: str = "docs",
    source_ref: str = "docs/auth.md",
    summary: str = "Documentation supports the decision.",
    confidence: str = "high",
    freshness: str = "current",
    observed_at: str | None = DEFAULT_TIMESTAMP,
    valid_until: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_ref": source_ref,
        "summary": summary,
        "confidence": confidence,
        "freshness": freshness,
        "observed_at": observed_at,
        "valid_until": valid_until,
    }


def assumption_metadata(
    *,
    statement: str = "The dependency remains available.",
    confidence: str = "medium",
    validation: str | None = None,
    invalidates_if_false: list[str] | None = None,
    expires_at: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    return {
        "statement": statement,
        "confidence": confidence,
        "validation": validation,
        "invalidates_if_false": deepcopy([] if invalidates_if_false is None else invalidates_if_false),
        "expires_at": expires_at,
        "owner": owner,
    }


def risk_metadata(
    *,
    statement: str = "The implementation may miss the release window.",
    severity: str = "medium",
    likelihood: str = "medium",
    risk_tier: str = "medium",
    reversibility: str = "partially_reversible",
    mitigation_object_ids: list[str] | None = None,
    approval_threshold: str = "explicit_acceptance",
) -> dict[str, Any]:
    return {
        "statement": statement,
        "severity": severity,
        "likelihood": likelihood,
        "risk_tier": risk_tier,
        "reversibility": reversibility,
        "mitigation_object_ids": deepcopy([] if mitigation_object_ids is None else mitigation_object_ids),
        "approval_threshold": approval_threshold,
    }


def action_metadata(
    *,
    action_type: str = "execution",
    implementation_ready: bool = True,
    required_inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    verification_refs: list[str] | None = None,
    source_decision_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "implementation_ready": implementation_ready,
        "required_inputs": deepcopy(["requirements brief"] if required_inputs is None else required_inputs),
        "outputs": deepcopy(["implementation patch"] if outputs is None else outputs),
        "verification_refs": deepcopy(["VER-001"] if verification_refs is None else verification_refs),
        "source_decision_refs": deepcopy(["D-001"] if source_decision_refs is None else source_decision_refs),
    }


def verification_metadata(
    *,
    method: str = "test",
    expected_result: str = "The expected behavior is verified.",
    verified_at: str | None = None,
    result: str = "pending",
) -> dict[str, Any]:
    return {
        "method": method,
        "expected_result": expected_result,
        "verified_at": verified_at,
        "result": result,
    }


def revisit_trigger_metadata(
    *,
    trigger_type: str = "time",
    condition: str = "Revisit when the milestone changes.",
    due_at: str | None = None,
    target_object_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "trigger_type": trigger_type,
        "condition": condition,
        "due_at": due_at,
        "target_object_ids": deepcopy(["D-001"] if target_object_ids is None else target_object_ids),
    }


def metadata_for_object_type(object_type: str) -> dict[str, Any]:
    if object_type == "evidence":
        return evidence_metadata()
    if object_type == "assumption":
        return assumption_metadata()
    if object_type == "risk":
        return risk_metadata()
    if object_type == "action":
        return action_metadata()
    if object_type == "verification":
        return verification_metadata()
    if object_type == "revisit_trigger":
        return revisit_trigger_metadata()
    return {}
