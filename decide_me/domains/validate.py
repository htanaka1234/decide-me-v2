from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

from decide_me.constants import (
    APPROVAL_THRESHOLD_VALUES,
    DECISION_STACK_LAYERS,
    DOMAIN_VALUES,
    EVIDENCE_FRESHNESS_VALUES,
    EVIDENCE_SOURCES,
    METADATA_CONFIDENCE_VALUES,
    RISK_TIER_VALUES,
)
from decide_me.documents.model import DOCUMENT_TYPES


DOMAIN_PACK_SCHEMA_VERSION = 1
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SECTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
DECISION_KIND_VALUES = {"choice", "constraint", "risk", "dependency"}
PRIORITY_VALUES = {"P0", "P1", "P2"}
DECISION_REVERSIBILITY_VALUES = {
    "reversible",
    "hard-to-reverse",
    "irreversible",
    "unknown",
}

TOP_LEVEL_KEYS = {
    "schema_version",
    "pack_id",
    "version",
    "label",
    "description",
    "aliases",
    "default_core_domain",
    "decision_types",
    "criteria",
    "evidence_requirements",
    "risk_types",
    "safety_rules",
    "documents",
    "interview",
}
DECISION_TYPE_KEYS = {
    "id",
    "label",
    "object_type",
    "layer",
    "kind",
    "default_priority",
    "default_reversibility",
    "criteria",
    "required_evidence",
}
CRITERION_KEYS = {"id", "label", "description"}
EVIDENCE_REQUIREMENT_KEYS = {
    "id",
    "label",
    "evidence_source",
    "domain_evidence_type",
    "min_confidence",
    "freshness_required",
}
RISK_TYPE_KEYS = {
    "id",
    "label",
    "default_risk_tier",
    "default_approval_threshold",
}
SAFETY_RULE_KEYS = {"id", "applies_when", "approval_threshold", "reason"}
SAFETY_RULE_CONDITION_KEYS = {"risk_types"}
DOCUMENT_KEYS = {"document_type", "default", "profile_id", "required_sections"}
INTERVIEW_KEYS = {"domain_hints", "question_templates"}


class DomainPackValidationError(ValueError):
    """Raised when a DomainPack payload violates the contract."""


def validate_domain_pack_payload(raw: dict[str, Any]) -> None:
    payload = _require_dict(raw, "domain_pack")
    _require_keys(payload, TOP_LEVEL_KEYS, "domain_pack")
    _reject_unknown_keys(payload, TOP_LEVEL_KEYS, "domain_pack")
    if type(payload.get("schema_version")) is not int:
        raise DomainPackValidationError("domain_pack.schema_version must be an integer")
    if payload["schema_version"] != DOMAIN_PACK_SCHEMA_VERSION:
        raise DomainPackValidationError(
            f"domain_pack.schema_version must be {DOMAIN_PACK_SCHEMA_VERSION}"
        )
    _require_identifier(payload.get("pack_id"), "domain_pack.pack_id")
    for key in ("version", "label", "description"):
        _require_non_empty_string(payload.get(key), f"domain_pack.{key}")
    _require_string_list(payload.get("aliases"), "domain_pack.aliases")
    _require_enum(
        payload.get("default_core_domain"),
        DOMAIN_VALUES,
        "domain_pack.default_core_domain",
    )

    decision_types = _validate_spec_list(
        payload.get("decision_types"),
        "domain_pack.decision_types",
        _validate_decision_type,
    )
    criteria = _validate_spec_list(
        payload.get("criteria"),
        "domain_pack.criteria",
        _validate_criterion,
    )
    evidence_requirements = _validate_spec_list(
        payload.get("evidence_requirements"),
        "domain_pack.evidence_requirements",
        _validate_evidence_requirement,
    )
    risk_types = _validate_spec_list(
        payload.get("risk_types"),
        "domain_pack.risk_types",
        _validate_risk_type,
    )
    safety_rules = _validate_spec_list(
        payload.get("safety_rules"),
        "domain_pack.safety_rules",
        _validate_safety_rule,
    )
    documents = _validate_spec_list(
        payload.get("documents"),
        "domain_pack.documents",
        _validate_document,
    )
    _validate_interview(payload.get("interview"), "domain_pack.interview")

    decision_type_ids = _unique_ids(decision_types, "domain_pack.decision_types")
    criterion_ids = _unique_ids(criteria, "domain_pack.criteria")
    evidence_requirement_ids = _unique_ids(
        evidence_requirements,
        "domain_pack.evidence_requirements",
    )
    risk_type_ids = _unique_ids(risk_types, "domain_pack.risk_types")
    _unique_ids(safety_rules, "domain_pack.safety_rules")
    _validate_document_uniqueness(documents)
    _validate_references(
        decision_types,
        criterion_ids=criterion_ids,
        evidence_requirement_ids=evidence_requirement_ids,
    )
    _validate_safety_rule_references(safety_rules, risk_type_ids)
    _validate_question_templates(payload["interview"]["question_templates"], decision_type_ids)


def _validate_decision_type(item: dict[str, Any], label: str) -> None:
    _require_keys(item, DECISION_TYPE_KEYS, label)
    _reject_unknown_keys(item, DECISION_TYPE_KEYS, label)
    _require_identifier(item.get("id"), f"{label}.id")
    _require_non_empty_string(item.get("label"), f"{label}.label")
    if item.get("object_type") != "decision":
        raise DomainPackValidationError(f"{label}.object_type must be decision")
    _require_enum(item.get("layer"), DECISION_STACK_LAYERS, f"{label}.layer")
    _require_enum(item.get("kind"), DECISION_KIND_VALUES, f"{label}.kind")
    _require_enum(item.get("default_priority"), PRIORITY_VALUES, f"{label}.default_priority")
    _require_enum(
        item.get("default_reversibility"),
        DECISION_REVERSIBILITY_VALUES,
        f"{label}.default_reversibility",
    )
    _require_identifier_list(item.get("criteria"), f"{label}.criteria")
    _require_identifier_list(item.get("required_evidence"), f"{label}.required_evidence")


def _validate_criterion(item: dict[str, Any], label: str) -> None:
    _require_keys(item, CRITERION_KEYS, label)
    _reject_unknown_keys(item, CRITERION_KEYS, label)
    _require_identifier(item.get("id"), f"{label}.id")
    _require_non_empty_string(item.get("label"), f"{label}.label")
    _require_non_empty_string(item.get("description"), f"{label}.description")


def _validate_evidence_requirement(item: dict[str, Any], label: str) -> None:
    _require_keys(item, EVIDENCE_REQUIREMENT_KEYS, label)
    _reject_unknown_keys(item, EVIDENCE_REQUIREMENT_KEYS, label)
    _require_identifier(item.get("id"), f"{label}.id")
    _require_non_empty_string(item.get("label"), f"{label}.label")
    _require_enum(item.get("evidence_source"), EVIDENCE_SOURCES, f"{label}.evidence_source")
    _require_identifier(item.get("domain_evidence_type"), f"{label}.domain_evidence_type")
    _require_enum(item.get("min_confidence"), METADATA_CONFIDENCE_VALUES, f"{label}.min_confidence")
    _require_enum(item.get("freshness_required"), EVIDENCE_FRESHNESS_VALUES, f"{label}.freshness_required")


def _validate_risk_type(item: dict[str, Any], label: str) -> None:
    _require_keys(item, RISK_TYPE_KEYS, label)
    _reject_unknown_keys(item, RISK_TYPE_KEYS, label)
    _require_identifier(item.get("id"), f"{label}.id")
    _require_non_empty_string(item.get("label"), f"{label}.label")
    _require_enum(item.get("default_risk_tier"), RISK_TIER_VALUES, f"{label}.default_risk_tier")
    _require_enum(
        item.get("default_approval_threshold"),
        APPROVAL_THRESHOLD_VALUES,
        f"{label}.default_approval_threshold",
    )


def _validate_safety_rule(item: dict[str, Any], label: str) -> None:
    _require_keys(item, SAFETY_RULE_KEYS, label)
    _reject_unknown_keys(item, SAFETY_RULE_KEYS, label)
    _require_identifier(item.get("id"), f"{label}.id")
    condition = _require_dict(item.get("applies_when"), f"{label}.applies_when")
    _require_keys(condition, SAFETY_RULE_CONDITION_KEYS, f"{label}.applies_when")
    _reject_unknown_keys(condition, SAFETY_RULE_CONDITION_KEYS, f"{label}.applies_when")
    _require_identifier_list(condition.get("risk_types"), f"{label}.applies_when.risk_types")
    if not condition["risk_types"]:
        raise DomainPackValidationError(f"{label}.applies_when.risk_types must not be empty")
    _require_enum(item.get("approval_threshold"), APPROVAL_THRESHOLD_VALUES, f"{label}.approval_threshold")
    _require_non_empty_string(item.get("reason"), f"{label}.reason")


def _validate_document(item: dict[str, Any], label: str) -> None:
    _require_keys(item, DOCUMENT_KEYS, label)
    _reject_unknown_keys(item, DOCUMENT_KEYS, label)
    _require_enum(item.get("document_type"), DOCUMENT_TYPES, f"{label}.document_type")
    if not isinstance(item.get("default"), bool):
        raise DomainPackValidationError(f"{label}.default must be a boolean")
    _require_identifier(item.get("profile_id"), f"{label}.profile_id")
    _require_section_id_list(item.get("required_sections"), f"{label}.required_sections")


def _validate_interview(value: Any, label: str) -> None:
    item = _require_dict(value, label)
    _require_keys(item, INTERVIEW_KEYS, label)
    _reject_unknown_keys(item, INTERVIEW_KEYS, label)
    _require_string_list(item.get("domain_hints"), f"{label}.domain_hints")
    question_templates = _require_dict(item.get("question_templates"), f"{label}.question_templates")
    for key, template in question_templates.items():
        _require_identifier(key, f"{label}.question_templates key")
        _require_non_empty_string(template, f"{label}.question_templates.{key}")


def _validate_spec_list(value: Any, label: str, validator: Any) -> list[dict[str, Any]]:
    items = _require_list(value, label)
    for index, item in enumerate(items):
        spec = _require_dict(item, f"{label}[{index}]")
        validator(spec, f"{label}[{index}]")
    return items


def _unique_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    ids = [item["id"] for item in items]
    duplicates = _duplicates(ids)
    if duplicates:
        raise DomainPackValidationError(f"{label} contains duplicate ids: {', '.join(duplicates)}")
    return set(ids)


def _validate_document_uniqueness(documents: list[dict[str, Any]]) -> None:
    profiles = [(item["document_type"], item["profile_id"]) for item in documents]
    duplicate_profiles = _duplicates(profiles)
    if duplicate_profiles:
        formatted = ", ".join(f"{doc_type}/{profile_id}" for doc_type, profile_id in duplicate_profiles)
        raise DomainPackValidationError(f"domain_pack.documents contains duplicate profiles: {formatted}")
    defaults_by_type: dict[str, int] = defaultdict(int)
    for item in documents:
        if item["default"]:
            defaults_by_type[item["document_type"]] += 1
    duplicate_defaults = sorted(doc_type for doc_type, count in defaults_by_type.items() if count > 1)
    if duplicate_defaults:
        raise DomainPackValidationError(
            "domain_pack.documents contains multiple defaults for document_type: "
            + ", ".join(duplicate_defaults)
        )


def _validate_references(
    decision_types: list[dict[str, Any]],
    *,
    criterion_ids: set[str],
    evidence_requirement_ids: set[str],
) -> None:
    for item in decision_types:
        _require_references(
            item["criteria"],
            criterion_ids,
            f"decision_type {item['id']}.criteria",
        )
        _require_references(
            item["required_evidence"],
            evidence_requirement_ids,
            f"decision_type {item['id']}.required_evidence",
        )


def _validate_safety_rule_references(safety_rules: list[dict[str, Any]], risk_type_ids: set[str]) -> None:
    for item in safety_rules:
        _require_references(
            item["applies_when"]["risk_types"],
            risk_type_ids,
            f"safety_rule {item['id']}.applies_when.risk_types",
        )


def _validate_question_templates(question_templates: dict[str, Any], decision_type_ids: set[str]) -> None:
    _require_references(
        question_templates.keys(),
        decision_type_ids,
        "domain_pack.interview.question_templates",
    )


def _require_references(values: Iterable[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise DomainPackValidationError(f"{label} references unknown ids: {', '.join(missing)}")


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainPackValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DomainPackValidationError(f"{label} must be a list")
    return value


def _require_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise DomainPackValidationError(f"{label} is missing required keys: {', '.join(missing)}")


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DomainPackValidationError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _require_non_empty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise DomainPackValidationError(f"{label} must be a non-empty string")


def _require_identifier(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise DomainPackValidationError(f"{label} must match {IDENTIFIER_PATTERN.pattern}")


def _require_section_id(value: Any, label: str) -> None:
    _require_non_empty_string(value, label)
    if not SECTION_ID_PATTERN.fullmatch(value):
        raise DomainPackValidationError(f"{label} must match {SECTION_ID_PATTERN.pattern}")


def _require_string_list(value: Any, label: str) -> None:
    items = _require_list(value, label)
    for index, item in enumerate(items):
        _require_non_empty_string(item, f"{label}[{index}]")
    _reject_duplicate_scalars(items, label)


def _require_identifier_list(value: Any, label: str) -> None:
    items = _require_list(value, label)
    for index, item in enumerate(items):
        _require_identifier(item, f"{label}[{index}]")
    _reject_duplicate_scalars(items, label)


def _require_section_id_list(value: Any, label: str) -> None:
    items = _require_list(value, label)
    for index, item in enumerate(items):
        _require_section_id(item, f"{label}[{index}]")
    _reject_duplicate_scalars(items, label)


def _require_enum(value: Any, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise DomainPackValidationError(f"{label} must be one of: {', '.join(sorted(allowed))}")


def _reject_duplicate_scalars(items: list[Any], label: str) -> None:
    duplicates = _duplicates(items)
    if duplicates:
        raise DomainPackValidationError(
            f"{label} contains duplicate values: {', '.join(str(item) for item in duplicates)}"
        )


def _duplicates(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    duplicate_seen: set[Any] = set()
    for value in values:
        if value in seen and value not in duplicate_seen:
            duplicates.append(value)
            duplicate_seen.add(value)
        seen.add(value)
    return sorted(duplicates)
