from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from decide_me.domains.infer import infer_decision_type
from decide_me.domains.loader import domain_pack_digest
from decide_me.domains.model import DecisionTypeSpec, DomainPack
from decide_me.domains.registry import DomainRegistry, GENERIC_PACK_ID


PACK_METADATA_KEYS = ("domain_pack_id", "domain_pack_version", "domain_pack_digest")


@dataclass(frozen=True)
class InterviewPolicy:
    pack: DomainPack
    digest: str

    @property
    def pack_id(self) -> str:
        return self.pack.pack_id

    @property
    def is_generic(self) -> bool:
        return self.pack.pack_id == GENERIC_PACK_ID

    @property
    def initial_decision_type(self) -> DecisionTypeSpec | None:
        if self.is_generic or not self.pack.decision_types:
            return None
        return self.pack.decision_types[0]

    def decision_type(self, type_id: str | None) -> DecisionTypeSpec | None:
        if not type_id:
            return None
        for spec in self.pack.decision_types:
            if spec.id == type_id:
                return spec
        return None

    def question_template(self, type_id: str | None) -> str | None:
        if not type_id:
            return None
        templates = dict(self.pack.interview.question_templates)
        return templates.get(type_id)

    def criteria_labels(self, spec: DecisionTypeSpec) -> tuple[str, ...]:
        criteria_by_id = {item.id: item.label for item in self.pack.criteria}
        return tuple(criteria_by_id.get(criteria_id, criteria_id) for criteria_id in spec.criteria)

    def evidence_labels(self, spec: DecisionTypeSpec) -> tuple[str, ...]:
        evidence_by_id = {item.id: item.label for item in self.pack.evidence_requirements}
        return tuple(evidence_by_id.get(evidence_id, evidence_id) for evidence_id in spec.required_evidence)


def build_interview_policy(
    registry: DomainRegistry,
    *,
    domain_pack_id: str | None,
) -> InterviewPolicy:
    pack_id = GENERIC_PACK_ID if domain_pack_id is None else domain_pack_id
    pack = registry.get(pack_id)
    return InterviewPolicy(pack=pack, digest=domain_pack_digest(pack))


def build_interview_policy_from_metadata(
    registry: DomainRegistry,
    metadata: dict[str, Any],
    *,
    label: str,
) -> InterviewPolicy:
    present = [key for key in PACK_METADATA_KEYS if key in metadata]
    if present and len(present) != len(PACK_METADATA_KEYS):
        missing = sorted(set(PACK_METADATA_KEYS) - set(present))
        raise ValueError(f"{label} has incomplete domain pack metadata; missing: {', '.join(missing)}")
    pack_id = metadata.get("domain_pack_id")
    try:
        policy = build_interview_policy(registry, domain_pack_id=pack_id)
    except KeyError as exc:
        raise ValueError(f"{label}.domain_pack_id is not defined: {exc}") from exc
    if pack_id is None:
        return policy

    _validate_policy_metadata(policy, metadata, label=label)
    return policy


def _validate_policy_metadata(
    policy: InterviewPolicy,
    metadata: dict[str, Any],
    *,
    label: str,
) -> None:
    version = metadata.get("domain_pack_version")
    digest = metadata.get("domain_pack_digest")
    if version != policy.pack.version:
        raise ValueError(
            f"{label}.domain_pack_version mismatch for domain pack {policy.pack_id}; "
            f"expected {policy.pack.version}, got {version}"
        )
    if digest != policy.digest:
        raise ValueError(
            f"{label}.domain_pack_digest mismatch for domain pack {policy.pack_id}; "
            f"expected {policy.digest}, got {digest}"
        )


def apply_decision_pack_metadata(
    policy: InterviewPolicy,
    decision: dict[str, Any],
    *,
    decision_type_id: str | None = None,
    infer_text: str | None = None,
) -> dict[str, Any]:
    if policy.is_generic:
        return deepcopy(decision)

    updated = deepcopy(decision)
    selected_type_id = (
        decision_type_id
        or updated.get("domain_decision_type")
        or infer_decision_type(policy.pack, infer_text or _decision_text(updated))
    )
    spec = policy.decision_type(selected_type_id)
    if selected_type_id and spec is None:
        raise ValueError(f"unknown decision type for domain pack {policy.pack_id}: {selected_type_id}")

    updated.setdefault("domain", policy.pack.default_core_domain)
    updated["domain_pack_id"] = policy.pack.pack_id
    updated["domain_pack_version"] = policy.pack.version
    updated["domain_pack_digest"] = policy.digest
    if spec is not None:
        updated["domain_decision_type"] = spec.id
        updated["domain_criteria"] = list(spec.criteria)
        updated.setdefault("kind", spec.kind)
        updated.setdefault("priority", spec.default_priority)
        updated.setdefault("reversibility", spec.default_reversibility)
    return updated


def build_initial_decision_payload(policy: InterviewPolicy, *, context: str | None) -> dict[str, Any] | None:
    spec = policy.initial_decision_type
    if spec is None:
        return None
    payload = {
        "title": spec.label,
        "kind": spec.kind,
        "domain": policy.pack.default_core_domain,
        "priority": spec.default_priority,
        "frontier": "now",
        "reversibility": spec.default_reversibility,
        "question": policy.question_template(spec.id) or f"What should we decide about {spec.label}?",
        "context": context or policy.pack.description,
        "notes": [f"Seeded from domain pack {policy.pack_id}:{spec.id}."],
    }
    return apply_decision_pack_metadata(policy, payload, decision_type_id=spec.id)


def _decision_text(decision: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            decision.get("title"),
            decision.get("question"),
            decision.get("context"),
            decision.get("body"),
        )
        if value
    )
