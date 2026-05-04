from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from decide_me.domains.validate import validate_domain_pack_payload


DOMAIN_PACK_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DecisionTypeSpec:
    id: str
    label: str
    object_type: str
    layer: str
    kind: str
    default_priority: str
    default_reversibility: str
    criteria: tuple[str, ...]
    required_evidence: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DecisionTypeSpec:
        return cls(
            id=raw["id"],
            label=raw["label"],
            object_type=raw["object_type"],
            layer=raw["layer"],
            kind=raw["kind"],
            default_priority=raw["default_priority"],
            default_reversibility=raw["default_reversibility"],
            criteria=_tuple(raw["criteria"]),
            required_evidence=_tuple(raw["required_evidence"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "object_type": self.object_type,
            "layer": self.layer,
            "kind": self.kind,
            "default_priority": self.default_priority,
            "default_reversibility": self.default_reversibility,
            "criteria": list(self.criteria),
            "required_evidence": list(self.required_evidence),
        }


@dataclass(frozen=True)
class CriteriaSpec:
    id: str
    label: str
    description: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CriteriaSpec:
        return cls(id=raw["id"], label=raw["label"], description=raw["description"])

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "description": self.description}


@dataclass(frozen=True)
class EvidenceRequirementSpec:
    id: str
    label: str
    evidence_source: str
    domain_evidence_type: str
    min_confidence: str
    freshness_required: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvidenceRequirementSpec:
        return cls(
            id=raw["id"],
            label=raw["label"],
            evidence_source=raw["evidence_source"],
            domain_evidence_type=raw["domain_evidence_type"],
            min_confidence=raw["min_confidence"],
            freshness_required=raw["freshness_required"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "evidence_source": self.evidence_source,
            "domain_evidence_type": self.domain_evidence_type,
            "min_confidence": self.min_confidence,
            "freshness_required": self.freshness_required,
        }


@dataclass(frozen=True)
class RiskTypeSpec:
    id: str
    label: str
    default_risk_tier: str
    default_approval_threshold: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RiskTypeSpec:
        return cls(
            id=raw["id"],
            label=raw["label"],
            default_risk_tier=raw["default_risk_tier"],
            default_approval_threshold=raw["default_approval_threshold"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "default_risk_tier": self.default_risk_tier,
            "default_approval_threshold": self.default_approval_threshold,
        }


@dataclass(frozen=True)
class SafetyRuleCondition:
    risk_types: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SafetyRuleCondition:
        return cls(risk_types=_tuple(raw["risk_types"]))

    def to_dict(self) -> dict[str, Any]:
        return {"risk_types": list(self.risk_types)}


@dataclass(frozen=True)
class SafetyRuleSpec:
    id: str
    applies_when: SafetyRuleCondition
    approval_threshold: str
    reason: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SafetyRuleSpec:
        return cls(
            id=raw["id"],
            applies_when=SafetyRuleCondition.from_dict(raw["applies_when"]),
            approval_threshold=raw["approval_threshold"],
            reason=raw["reason"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "applies_when": self.applies_when.to_dict(),
            "approval_threshold": self.approval_threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiskPolicySpec:
    risk_tier: str
    approval: str
    automatic_adoption: str
    required_actions: tuple[str, ...]

    @classmethod
    def from_dict(cls, risk_tier: str, raw: dict[str, Any]) -> RiskPolicySpec:
        return cls(
            risk_tier=risk_tier,
            approval=raw["approval"],
            automatic_adoption=raw["automatic_adoption"],
            required_actions=_tuple(raw["required_actions"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval": self.approval,
            "automatic_adoption": self.automatic_adoption,
            "required_actions": list(self.required_actions),
        }


@dataclass(frozen=True)
class DocumentSpec:
    document_type: str
    default: bool
    profile_id: str
    required_sections: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DocumentSpec:
        return cls(
            document_type=raw["document_type"],
            default=raw["default"],
            profile_id=raw["profile_id"],
            required_sections=_tuple(raw["required_sections"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "default": self.default,
            "profile_id": self.profile_id,
            "required_sections": list(self.required_sections),
        }


@dataclass(frozen=True)
class InterviewSpec:
    domain_hints: tuple[str, ...]
    question_templates: tuple[tuple[str, str], ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> InterviewSpec:
        return cls(
            domain_hints=_tuple(raw["domain_hints"]),
            question_templates=tuple(sorted(raw["question_templates"].items())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_hints": list(self.domain_hints),
            "question_templates": {key: value for key, value in self.question_templates},
        }


@dataclass(frozen=True)
class DomainPack:
    schema_version: int
    pack_id: str
    version: str
    label: str
    description: str
    aliases: tuple[str, ...]
    default_core_domain: str
    decision_types: tuple[DecisionTypeSpec, ...]
    criteria: tuple[CriteriaSpec, ...]
    evidence_requirements: tuple[EvidenceRequirementSpec, ...]
    risk_types: tuple[RiskTypeSpec, ...]
    action_types: tuple[str, ...]
    safety_rules: tuple[SafetyRuleSpec, ...]
    risk_policy: tuple[RiskPolicySpec, ...]
    documents: tuple[DocumentSpec, ...]
    interview: InterviewSpec

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "aliases": list(self.aliases),
            "default_core_domain": self.default_core_domain,
            "decision_types": [item.to_dict() for item in self.decision_types],
            "criteria": [item.to_dict() for item in self.criteria],
            "evidence_requirements": [item.to_dict() for item in self.evidence_requirements],
            "risk_types": [item.to_dict() for item in self.risk_types],
            "action_types": list(self.action_types),
            "safety_rules": [item.to_dict() for item in self.safety_rules],
            "documents": [item.to_dict() for item in self.documents],
            "interview": self.interview.to_dict(),
        }
        if self.risk_policy:
            payload["risk_policy"] = {item.risk_tier: item.to_dict() for item in self.risk_policy}
        return payload


def domain_pack_from_dict(raw: dict[str, Any]) -> DomainPack:
    validate_domain_pack_payload(raw)
    return DomainPack(
        schema_version=raw["schema_version"],
        pack_id=raw["pack_id"],
        version=raw["version"],
        label=raw["label"],
        description=raw["description"],
        aliases=_tuple(raw["aliases"]),
        default_core_domain=raw["default_core_domain"],
        decision_types=tuple(DecisionTypeSpec.from_dict(item) for item in raw["decision_types"]),
        criteria=tuple(CriteriaSpec.from_dict(item) for item in raw["criteria"]),
        evidence_requirements=tuple(
            EvidenceRequirementSpec.from_dict(item) for item in raw["evidence_requirements"]
        ),
        risk_types=tuple(RiskTypeSpec.from_dict(item) for item in raw["risk_types"]),
        action_types=_tuple(raw["action_types"]),
        safety_rules=tuple(SafetyRuleSpec.from_dict(item) for item in raw["safety_rules"]),
        risk_policy=tuple(
            RiskPolicySpec.from_dict(risk_tier, item)
            for risk_tier, item in sorted(raw.get("risk_policy", {}).items())
        ),
        documents=tuple(DocumentSpec.from_dict(item) for item in raw["documents"]),
        interview=InterviewSpec.from_dict(raw["interview"]),
    )


def _tuple(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(values)
