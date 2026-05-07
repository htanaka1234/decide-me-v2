from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from decide_me.constants import (
    APPROVAL_LEVEL_VALUES,
    APPROVAL_THRESHOLD_VALUES,
    DECISION_STACK_LAYERS,
    DOMAIN_VALUES,
    EVIDENCE_FRESHNESS_VALUES,
    EVIDENCE_SOURCES,
    METADATA_CONFIDENCE_VALUES,
    REVISIT_TRIGGER_TYPE_VALUES,
    RISK_LIKELIHOOD_VALUES,
    RISK_REVERSIBILITY_VALUES,
    RISK_SEVERITY_VALUES,
    RISK_TIER_VALUES,
    VERIFICATION_METHOD_VALUES,
    VERIFICATION_RESULT_VALUES,
)


DOMAIN_PACK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DOMAIN_PACK_DIGEST_PATTERN = re.compile(r"^DP-[0-9a-f]{12}$")
SHA256_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
PACK_METADATA_KEYS = ("domain_pack_id", "domain_pack_version", "domain_pack_digest")
OPEN_DECISION_STATUSES = {"unresolved", "proposed", "blocked"}
ALL_DECISION_STATUSES = OPEN_DECISION_STATUSES | {
    "accepted",
    "deferred",
    "resolved-by-evidence",
    "invalidated",
}
PRIORITIES = {"P0", "P1", "P2"}
FRONTIERS = {"now", "later", "discovered-later", "deferred"}
KINDS = {"choice", "constraint", "risk", "dependency"}
RESOLVABLE_BY = {"human", "codebase", "docs", "tests", "external"}
REVERSIBILITY = {"reversible", "hard-to-reverse", "irreversible", "unknown"}
_APPROVAL_LEVEL_RANK = {"explicit_acceptance": 1, "human_review": 2, "external_review": 3}
_APPROVAL_THRESHOLD_RANK = {"none": 0, **_APPROVAL_LEVEL_RANK}


@dataclass(frozen=True)
class ValidationError:
    message: str

    def __str__(self) -> str:
        return self.message


class MetadataValidationError(ValueError):
    """Raised when object metadata fails object type-specific validation."""


def validate_object_metadata(
    object_type: str,
    metadata: dict[str, Any],
    *,
    object_id: str = "?",
    status: str | None = None,
) -> list[ValidationError]:
    validator = _MetadataValidator()
    validator.validate(object_type, metadata, object_id=object_id, status=status)
    return [ValidationError(message) for message in validator.errors]


def assert_valid_object_metadata(
    object_type: str,
    metadata: dict[str, Any],
    *,
    object_id: str = "?",
    status: str | None = None,
    error_cls: type[Exception] = MetadataValidationError,
) -> None:
    errors = validate_object_metadata(object_type, metadata, object_id=object_id, status=status)
    if errors:
        raise error_cls(str(errors[0]))


class _MetadataValidator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def validate(
        self,
        object_type: str,
        metadata: dict[str, Any],
        *,
        object_id: str,
        status: str | None,
    ) -> None:
        label = f"{object_type} object {object_id}.metadata"
        if not isinstance(metadata, dict):
            self._error(f"{label} must be an object")
            return
        if "layer" in metadata:
            self._require_enum(metadata["layer"], DECISION_STACK_LAYERS, f"{label}.layer")
        if object_type == "decision":
            self._validate_decision(metadata, label, object_id=object_id, status=status)
        elif object_type == "evidence":
            self._validate_evidence(metadata, label)
        elif object_type == "assumption":
            self._validate_assumption(metadata, label)
        elif object_type == "risk":
            self._validate_risk(metadata, label)
        elif object_type == "verification":
            self._validate_verification(metadata, label)
        elif object_type == "revisit_trigger":
            self._validate_revisit_trigger(metadata, label)
        elif object_type == "artifact":
            self._validate_artifact(metadata, label)
        elif object_type == "action":
            self._validate_action(metadata, label)

    def _validate_decision(
        self,
        metadata: dict[str, Any],
        label: str,
        *,
        object_id: str,
        status: str | None,
    ) -> None:
        if status is not None and status not in ALL_DECISION_STATUSES:
            self._error(f"unsupported decision status: {status}")
        for key, allowed in (
            ("priority", PRIORITIES),
            ("frontier", FRONTIERS),
            ("kind", KINDS),
            ("domain", DOMAIN_VALUES),
            ("resolvable_by", RESOLVABLE_BY),
            ("reversibility", REVERSIBILITY),
        ):
            if key in metadata:
                self._require_enum(metadata[key], allowed, f"{label}.{key}")
        if "agent_relevant" in metadata and metadata["agent_relevant"] is not None:
            if not isinstance(metadata["agent_relevant"], bool):
                self._error(f"{label}.agent_relevant must be a boolean or null")
        if "notes" in metadata:
            self._require_list(metadata["notes"], f"{label}.notes")
        self._validate_object_domain_pack_identity(
            metadata,
            label,
            detail_keys=("domain_decision_type", "domain_criteria"),
            detail_label="domain decision metadata",
        )
        if "domain_decision_type" in metadata:
            self._require_domain_pack_identifier(metadata["domain_decision_type"], f"{label}.domain_decision_type")
        if "domain_criteria" in metadata:
            self._require_string_list(metadata["domain_criteria"], f"{label}.domain_criteria")
        invalidated_by = metadata.get("invalidated_by")
        if status == "invalidated":
            invalidated = self._require_dict(invalidated_by, f"{label}.invalidated_by")
            if isinstance(invalidated, dict):
                self._require_non_empty_string(invalidated.get("decision_id"), f"{label}.invalidated_by.decision_id")
                self._require_timestamp(invalidated.get("invalidated_at"), f"{label}.invalidated_by.invalidated_at")
        elif status is not None and invalidated_by is not None:
            self._error(f"non-invalidated decision object {object_id} must not carry invalidated_by")

    def _validate_evidence(self, metadata: dict[str, Any], label: str) -> None:
        self._require_keys(
            metadata,
            ("source", "source_ref", "summary", "confidence", "freshness", "observed_at", "valid_until"),
            label,
        )
        self._require_enum(metadata.get("source"), EVIDENCE_SOURCES, f"{label}.source")
        self._require_non_empty_string(metadata.get("source_ref"), f"{label}.source_ref")
        self._require_non_empty_string(metadata.get("summary"), f"{label}.summary")
        self._require_enum(metadata.get("confidence"), METADATA_CONFIDENCE_VALUES, f"{label}.confidence")
        self._require_enum(metadata.get("freshness"), EVIDENCE_FRESHNESS_VALUES, f"{label}.freshness")
        self._require_optional_timestamp(metadata.get("observed_at"), f"{label}.observed_at")
        self._require_optional_timestamp(metadata.get("valid_until"), f"{label}.valid_until")
        self._validate_object_domain_pack_identity(
            metadata,
            label,
            detail_keys=("domain_evidence_type", "evidence_requirement_id"),
            detail_label="domain evidence metadata",
        )
        for key in ("domain_evidence_type", "evidence_requirement_id"):
            if key in metadata:
                self._require_domain_pack_identifier(metadata[key], f"{label}.{key}")
        for key in ("source_document_id", "source_unit_id", "citation", "quote", "interpretation_note"):
            if key in metadata:
                self._require_optional_non_empty_string(metadata.get(key), f"{label}.{key}")
        if "source_unit_hash" in metadata:
            self._require_optional_hash(metadata.get("source_unit_hash"), f"{label}.source_unit_hash")
        for key in ("effective_from", "effective_to"):
            if key in metadata:
                self._require_optional_date(metadata.get(key), f"{label}.{key}")

    def _validate_assumption(self, metadata: dict[str, Any], label: str) -> None:
        self._require_keys(
            metadata,
            ("statement", "confidence", "validation", "invalidates_if_false", "expires_at", "owner"),
            label,
        )
        self._require_non_empty_string(metadata.get("statement"), f"{label}.statement")
        self._require_enum(metadata.get("confidence"), METADATA_CONFIDENCE_VALUES, f"{label}.confidence")
        self._require_optional_non_empty_string(metadata.get("validation"), f"{label}.validation")
        self._require_string_list(metadata.get("invalidates_if_false"), f"{label}.invalidates_if_false")
        self._require_optional_timestamp(metadata.get("expires_at"), f"{label}.expires_at")
        self._require_optional_non_empty_string(metadata.get("owner"), f"{label}.owner")

    def _validate_risk(self, metadata: dict[str, Any], label: str) -> None:
        self._require_keys(
            metadata,
            (
                "statement",
                "severity",
                "likelihood",
                "risk_tier",
                "reversibility",
                "mitigation_object_ids",
                "approval_threshold",
            ),
            label,
        )
        self._require_non_empty_string(metadata.get("statement"), f"{label}.statement")
        self._require_enum(metadata.get("severity"), RISK_SEVERITY_VALUES, f"{label}.severity")
        self._require_enum(metadata.get("likelihood"), RISK_LIKELIHOOD_VALUES, f"{label}.likelihood")
        self._require_enum(metadata.get("risk_tier"), RISK_TIER_VALUES, f"{label}.risk_tier")
        self._require_enum(metadata.get("reversibility"), RISK_REVERSIBILITY_VALUES, f"{label}.reversibility")
        self._require_string_list(metadata.get("mitigation_object_ids"), f"{label}.mitigation_object_ids")
        self._require_enum(metadata.get("approval_threshold"), APPROVAL_THRESHOLD_VALUES, f"{label}.approval_threshold")
        self._validate_object_domain_pack_identity(
            metadata,
            label,
            detail_keys=("domain_risk_type",),
            detail_label="domain risk metadata",
        )
        if "domain_risk_type" in metadata:
            self._require_domain_pack_identifier(metadata["domain_risk_type"], f"{label}.domain_risk_type")

    def _validate_verification(self, metadata: dict[str, Any], label: str) -> None:
        self._require_keys(metadata, ("method", "expected_result", "verified_at", "result"), label)
        self._require_enum(metadata.get("method"), VERIFICATION_METHOD_VALUES, f"{label}.method")
        self._require_non_empty_string(metadata.get("expected_result"), f"{label}.expected_result")
        self._require_optional_timestamp(metadata.get("verified_at"), f"{label}.verified_at")
        self._require_enum(metadata.get("result"), VERIFICATION_RESULT_VALUES, f"{label}.result")

    def _validate_revisit_trigger(self, metadata: dict[str, Any], label: str) -> None:
        self._require_keys(metadata, ("trigger_type", "condition", "due_at", "target_object_ids"), label)
        self._require_enum(metadata.get("trigger_type"), REVISIT_TRIGGER_TYPE_VALUES, f"{label}.trigger_type")
        self._require_non_empty_string(metadata.get("condition"), f"{label}.condition")
        self._require_optional_timestamp(metadata.get("due_at"), f"{label}.due_at")
        self._require_string_list(metadata.get("target_object_ids"), f"{label}.target_object_ids")
        if metadata.get("target_object_ids") == []:
            self._error(f"{label}.target_object_ids must not be empty")

    def _validate_artifact(self, metadata: dict[str, Any], label: str) -> None:
        if metadata.get("artifact_type") != "safety_gate_approval":
            return
        self._require_keys(
            metadata,
            (
                "artifact_type",
                "target_object_id",
                "gate_digest",
                "approval_threshold",
                "approval_level",
                "approved_by",
                "approved_at",
                "reason",
                "expires_at",
            ),
            label,
        )
        allowed = {
            "artifact_type",
            "target_object_id",
            "gate_digest",
            "approval_threshold",
            "approval_level",
            "approved_by",
            "approved_at",
            "reason",
            "expires_at",
            "layer",
        }
        unknown = sorted(set(metadata) - allowed)
        if unknown:
            self._error(f"{label} contains unsupported keys: {', '.join(unknown)}")
        self._require_non_empty_string(metadata.get("target_object_id"), f"{label}.target_object_id")
        gate_digest = metadata.get("gate_digest")
        self._require_non_empty_string(gate_digest, f"{label}.gate_digest")
        if gate_digest is not None and not str(gate_digest).startswith("SG-"):
            self._error(f"{label}.gate_digest must start with SG-")
        approval_threshold = metadata.get("approval_threshold")
        approval_level = metadata.get("approval_level")
        self._require_enum(approval_threshold, APPROVAL_THRESHOLD_VALUES, f"{label}.approval_threshold")
        self._require_enum(approval_level, APPROVAL_LEVEL_VALUES, f"{label}.approval_level")
        if approval_level in _APPROVAL_LEVEL_RANK and approval_threshold in _APPROVAL_THRESHOLD_RANK:
            if _APPROVAL_LEVEL_RANK[approval_level] < _APPROVAL_THRESHOLD_RANK[approval_threshold]:
                self._error(f"{label}.approval_level does not satisfy approval_threshold")
        self._require_non_empty_string(metadata.get("approved_by"), f"{label}.approved_by")
        self._require_timestamp(metadata.get("approved_at"), f"{label}.approved_at")
        self._require_non_empty_string(metadata.get("reason"), f"{label}.reason")
        self._require_optional_timestamp(metadata.get("expires_at"), f"{label}.expires_at")

    def _validate_action(self, metadata: dict[str, Any], label: str) -> None:
        for key in ("decision_id", "origin_session_id", "next_step", "responsibility", "kind"):
            if key in metadata:
                self._require_optional_non_empty_string(metadata.get(key), f"{label}.{key}")
        if "action_type" in metadata:
            self._require_domain_pack_identifier(metadata["action_type"], f"{label}.action_type")
        if "implementation_ready" in metadata and not isinstance(metadata["implementation_ready"], bool):
            self._error(f"{label}.implementation_ready must be a boolean")
        if "evidence_backed" in metadata and not isinstance(metadata["evidence_backed"], bool):
            self._error(f"{label}.evidence_backed must be a boolean")
        if "evidence_source" in metadata:
            self._require_optional_non_empty_string(metadata.get("evidence_source"), f"{label}.evidence_source")
        for key in ("required_inputs", "outputs", "verification_refs", "source_decision_refs"):
            if key in metadata:
                self._require_string_list(metadata[key], f"{label}.{key}")
        for key, allowed in (
            ("priority", PRIORITIES),
            ("frontier", FRONTIERS),
            ("resolvable_by", RESOLVABLE_BY),
            ("reversibility", REVERSIBILITY),
        ):
            if key in metadata:
                self._require_enum(metadata[key], allowed, f"{label}.{key}")

    def _validate_object_domain_pack_identity(
        self,
        metadata: dict[str, Any],
        label: str,
        *,
        detail_keys: tuple[str, ...],
        detail_label: str,
    ) -> None:
        present = [key for key in PACK_METADATA_KEYS if key in metadata]
        has_domain_details = any(key in metadata for key in detail_keys)
        if present and len(present) != len(PACK_METADATA_KEYS):
            missing = sorted(set(PACK_METADATA_KEYS) - set(present))
            self._error(f"{label} has incomplete domain pack metadata; missing: {', '.join(missing)}")
        if has_domain_details and not present:
            self._error(f"{label} {detail_label} requires domain pack metadata")
        if "domain_pack_id" in metadata:
            self._require_domain_pack_identifier(metadata["domain_pack_id"], f"{label}.domain_pack_id")
        if "domain_pack_version" in metadata:
            self._require_non_empty_string(metadata["domain_pack_version"], f"{label}.domain_pack_version")
        if "domain_pack_digest" in metadata:
            digest = metadata["domain_pack_digest"]
            self._require_non_empty_string(digest, f"{label}.domain_pack_digest")
            if isinstance(digest, str) and not DOMAIN_PACK_DIGEST_PATTERN.fullmatch(digest):
                self._error(f"{label}.domain_pack_digest must match ^DP-[0-9a-f]{{12}}$")

    def _require_domain_pack_identifier(self, value: Any, label: str) -> None:
        self._require_non_empty_string(value, label)
        if isinstance(value, str) and not DOMAIN_PACK_ID_PATTERN.fullmatch(value):
            self._error(f"{label} must match ^[a-z][a-z0-9_]*$")

    def _require_keys(self, payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
        missing = [key for key in keys if key not in payload]
        if missing:
            self._error(f"{label} is missing required keys: {', '.join(missing)}")

    def _require_timestamp(self, value: Any, label: str) -> None:
        if not isinstance(value, str) or not value.strip():
            self._error(f"{label} must be a non-empty timestamp")
            return
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            self._error(f"{label} must be ISO-8601/RFC3339-like")

    def _require_optional_timestamp(self, value: Any, label: str) -> None:
        if value is None:
            return
        self._require_timestamp(value, label)

    def _require_optional_date(self, value: Any, label: str) -> None:
        if value is None:
            return
        if not isinstance(value, str) or not value.strip():
            self._error(f"{label} must be a non-empty date or null")
            return
        try:
            date.fromisoformat(value)
        except ValueError:
            self._error(f"{label} must be YYYY-MM-DD")

    def _require_optional_hash(self, value: Any, label: str) -> None:
        if value is None:
            return
        self._require_non_empty_string(value, label)
        if isinstance(value, str) and not SHA256_HASH_PATTERN.fullmatch(value):
            self._error(f"{label} must be sha256:<64 lowercase hex chars>")

    def _require_non_empty_string(self, value: Any, label: str) -> None:
        if not isinstance(value, str) or not value.strip():
            self._error(f"{label} must be a non-empty string")

    def _require_optional_non_empty_string(self, value: Any, label: str) -> None:
        if value is None:
            return
        self._require_non_empty_string(value, label)

    def _require_dict(self, value: Any, label: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self._error(f"{label} must be an object")
            return None
        return value

    def _require_list(self, value: Any, label: str) -> list[Any] | None:
        if not isinstance(value, list):
            self._error(f"{label} must be a list")
            return None
        return value

    def _require_string_list(self, value: Any, label: str) -> None:
        items = self._require_list(value, label)
        if items is None:
            return
        seen: set[str] = set()
        for item in items:
            self._require_non_empty_string(item, f"{label}[]")
            if isinstance(item, str):
                if item in seen:
                    self._error(f"{label} contains duplicate values")
                seen.add(item)

    def _require_enum(self, value: Any, allowed: set[str], label: str) -> None:
        if value not in allowed:
            choices = ", ".join(sorted(allowed))
            self._error(f"{label} must be one of: {choices}")

    def _error(self, message: str) -> None:
        self.errors.append(message)
