from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from decide_me.constants import DECISION_STACK_LAYER_ORDER
from decide_me.domains import DomainPack, DomainPackLoadError, load_domain_registry
from decide_me.domains.registry import GENERIC_PACK_ID
from decide_me.events import utc_now
from decide_me.store import _atomic_write_json, _write_lock, load_json, load_runtime, runtime_paths


DRAFT_SET_SCHEMA_VERSION = 3
DRAFT_SET_ID_PATTERN = re.compile(r"^DS-[0-9]{8}-[0-9]{3}$")
DRAFT_SET_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "draft-decision-set.schema.json"
DRAFT_SET_COUNTS = (
    "draft_decisions",
    "draft_assumptions",
    "draft_risks",
    "draft_actions",
    "draft_verifications",
)
OPTIONAL_ARRAY_FIELDS = (
    "draft_assumptions",
    "draft_risks",
    "draft_actions",
    "draft_verifications",
    "conflicts",
)
DEFAULT_PROMOTION = {
    "promoted_decision_ids": [],
    "bulk_promotable_ids": [],
    "individual_review_required_ids": [],
}
DEFAULT_STOP_CONDITIONS = [
    "required_coverage_targets_satisfied",
    "budget_exhausted",
    "blocking_gap_requires_review",
]
DEFAULT_PAUSE_CONDITIONS = [
    "missing_or_challenged_evidence",
    "high_or_critical_risk",
    "stale_or_unclassifiable_diagnostics",
]


class DraftSetError(ValueError):
    pass


class DraftSetValidationError(DraftSetError):
    pass


class DraftSetNotFoundError(DraftSetError):
    pass


class DraftSetHeadMismatchError(DraftSetError):
    pass


def create_draft_set(
    ai_dir: str | Path,
    draft_payload: dict[str, Any],
    *,
    draft_set_id: str | None = None,
    generated_by: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    timestamp = now or utc_now()
    with _write_lock(paths.lock_path):
        bundle = load_runtime(paths)
        current_head = _current_project_head(bundle)
        normalized = _normalize_draft_set(
            draft_payload,
            current_head=current_head,
            draft_set_id=draft_set_id,
            generated_by=generated_by,
            now=timestamp,
            ai_dir=paths.ai_dir,
        )
        validate_draft_set(normalized)

        target_dir = _draft_set_dir(paths.ai_dir, normalized["id"])
        target_path = target_dir / "draft-set.json"
        if target_dir.exists():
            raise DraftSetError(f"draft set already exists: {normalized['id']}")
        _atomic_write_json(target_path, normalized)

    return {
        "status": "created",
        "draft_set_id": normalized["id"],
        "path": str(target_path),
        "project_head_at_generation": normalized["source_context"]["project_head_at_generation"],
        "is_stale": False,
        "counts": _counts(normalized),
    }


def load_draft_set(ai_dir: str | Path, draft_set_id: str) -> dict[str, Any]:
    _validate_draft_set_id(draft_set_id)
    path = _draft_set_dir(Path(ai_dir), draft_set_id) / "draft-set.json"
    if not path.exists():
        raise DraftSetNotFoundError(f"draft set not found: {draft_set_id}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise DraftSetValidationError("draft-set validation failed: draft-set.json must contain an object")
    validate_draft_set(payload)
    if payload["id"] != draft_set_id:
        raise DraftSetValidationError(
            f"draft-set validation failed: draft-set id {payload['id']} does not match path {draft_set_id}"
        )
    return payload


def draft_set_dir(ai_dir: str | Path, draft_set_id: str) -> Path:
    return _draft_set_dir(Path(ai_dir), draft_set_id)


def show_draft_set(ai_dir: str | Path, draft_set_id: str) -> dict[str, Any]:
    draft_set = load_draft_set(ai_dir, draft_set_id)
    return {
        "status": "ok",
        "draft_set": draft_set,
        "runtime_status": draft_set_staleness(ai_dir, draft_set),
    }


def list_draft_sets(ai_dir: str | Path) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    current_head = _current_project_head(load_runtime(paths))
    draft_root = paths.ai_dir / "draft-sets"
    summaries: list[dict[str, Any]] = []
    if draft_root.exists():
        for path in sorted(draft_root.glob("DS-*/draft-set.json")):
            draft_set_id = path.parent.name
            if not DRAFT_SET_ID_PATTERN.fullmatch(draft_set_id):
                continue
            draft_set = load_draft_set(paths.ai_dir, draft_set_id)
            summaries.append(_summary(draft_set, current_head=current_head, path=path))

    summaries.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {
        "status": "ok",
        "count": len(summaries),
        "draft_sets": summaries,
    }


def validate_draft_set(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise DraftSetValidationError("draft-set validation failed: payload must be an object")
    errors = sorted(_schema_validator().iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise DraftSetValidationError(f"draft-set validation failed: {_format_validation_error(errors[0])}")
    targets_by_axis_id = _coverage_targets_by_axis_id(payload)
    _validate_domain_pack_coverage_target_provenance(targets_by_axis_id.values())
    _validate_coverage_target_references(payload, targets_by_axis_id)


def draft_set_staleness(ai_dir: str | Path, draft_set: dict[str, Any]) -> dict[str, Any]:
    paths = runtime_paths(ai_dir)
    current_head = _current_project_head(load_runtime(paths))
    generated_head = draft_set["source_context"]["project_head_at_generation"]
    is_stale = generated_head != current_head
    return {
        "project_head_at_generation": generated_head,
        "current_project_head": current_head,
        "is_stale": is_stale,
        "reason": "project-head-changed" if is_stale else None,
    }


def default_exploration_contract(
    draft_set: dict[str, Any],
    *,
    max_draft_decisions: int = 20,
    max_iterations: int = 0,
    ai_dir: str | Path | None = None,
    domain_pack: DomainPack | None = None,
) -> dict[str, Any]:
    goal = draft_set.get("goal") if isinstance(draft_set.get("goal"), dict) else {}
    source_context = draft_set.get("source_context") if isinstance(draft_set.get("source_context"), dict) else {}
    objective = goal.get("desired_outcome") or goal.get("title") or "Review draft decision set"
    project_state_ref = source_context.get("project_state_ref") or "project-state.json"
    domain_pack_id = _source_context_domain_pack_id(source_context)
    pack = domain_pack or _load_domain_pack(ai_dir, domain_pack_id)
    coverage_targets = _core_layer_coverage_targets() + _domain_pack_coverage_targets(pack)
    return {
        "objective": str(objective),
        "non_goals": [],
        "read_first_sources": [str(project_state_ref)],
        "coverage_targets": coverage_targets,
        "budgets": {
            "max_draft_decisions": max_draft_decisions,
            "max_iterations": max_iterations,
        },
        "stop_conditions": list(DEFAULT_STOP_CONDITIONS),
        "pause_conditions": list(DEFAULT_PAUSE_CONDITIONS),
    }


def _normalize_draft_set(
    draft_payload: dict[str, Any],
    *,
    current_head: str,
    draft_set_id: str | None,
    generated_by: str | None,
    now: str,
    ai_dir: Path,
) -> dict[str, Any]:
    if not isinstance(draft_payload, dict):
        raise DraftSetValidationError("draft-set validation failed: payload must be an object")
    if draft_set_id is not None:
        _validate_draft_set_id(draft_set_id)

    normalized = deepcopy(draft_payload)
    normalized.setdefault("schema_version", DRAFT_SET_SCHEMA_VERSION)
    normalized.setdefault("status", "generated")
    normalized.setdefault("mode", "autopilot-draft")
    normalized["created_at"] = now
    normalized.setdefault("generated_by", "skill" if generated_by is None else generated_by)
    normalized.setdefault("promotion", deepcopy(DEFAULT_PROMOTION))
    for field in OPTIONAL_ARRAY_FIELDS:
        normalized.setdefault(field, [])

    payload_id = normalized.get("id")
    if draft_set_id is not None and payload_id is not None and payload_id != draft_set_id:
        raise DraftSetError(f"draft payload id does not match --draft-set-id: {payload_id} != {draft_set_id}")
    normalized["id"] = draft_set_id or payload_id or _next_draft_set_id(ai_dir, now)
    _validate_draft_set_id(normalized["id"])

    source_context = normalized.setdefault("source_context", {})
    if not isinstance(source_context, dict):
        raise DraftSetValidationError("draft-set validation failed: source_context must be an object")
    legacy_head = source_context.pop("project_head", None)
    generated_head = source_context.get("project_head_at_generation")
    if legacy_head is not None and generated_head is not None and legacy_head != generated_head:
        raise DraftSetHeadMismatchError(
            "draft payload project_head_at_generation does not match source_context.project_head"
        )
    if generated_head is None and legacy_head is not None:
        generated_head = legacy_head
    if generated_head is not None and generated_head != current_head:
        raise DraftSetHeadMismatchError(
            "draft payload project_head_at_generation does not match current project_head"
        )
    source_context["project_head_at_generation"] = generated_head or current_head
    source_context.setdefault("project_state_ref", "project-state.json")
    source_context.setdefault("included_session_ids", [])
    source_context.setdefault("included_object_ids", [])
    domain_pack = _source_context_domain_pack(ai_dir, source_context)
    normalized.setdefault(
        "exploration_contract",
        default_exploration_contract(
            normalized,
            max_draft_decisions=20,
            max_iterations=0,
            ai_dir=ai_dir,
            domain_pack=domain_pack,
        ),
    )
    return normalized


def _next_draft_set_id(ai_dir: Path, now: str) -> str:
    date_part = _yyyymmdd_utc(now)
    draft_root = ai_dir / "draft-sets"
    existing_numbers: list[int] = []
    if draft_root.exists():
        for path in draft_root.glob(f"DS-{date_part}-*"):
            match = DRAFT_SET_ID_PATTERN.fullmatch(path.name)
            if match is not None:
                existing_numbers.append(int(path.name.rsplit("-", 1)[1]))
    next_number = max(existing_numbers, default=0) + 1
    return f"DS-{date_part}-{next_number:03d}"


def _yyyymmdd_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DraftSetValidationError(f"draft-set validation failed: created_at must be a date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d")


def _current_project_head(bundle: dict[str, Any]) -> str:
    project_head = bundle["project_state"]["state"].get("project_head")
    if not isinstance(project_head, str) or not project_head:
        raise DraftSetError("current project_head is unavailable")
    return project_head


def _draft_set_dir(ai_dir: Path, draft_set_id: str) -> Path:
    _validate_draft_set_id(draft_set_id)
    return Path(ai_dir) / "draft-sets" / draft_set_id


def _validate_draft_set_id(draft_set_id: str) -> None:
    if not isinstance(draft_set_id, str) or DRAFT_SET_ID_PATTERN.fullmatch(draft_set_id) is None:
        raise DraftSetError(f"invalid draft set id: {draft_set_id}")


def _coverage_targets_by_axis_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contract = payload.get("exploration_contract")
    if not isinstance(contract, dict):
        return {}
    coverage_targets = contract.get("coverage_targets")
    if not isinstance(coverage_targets, list):
        return {}

    targets_by_axis_id: dict[str, dict[str, Any]] = {}
    for index, target in enumerate(coverage_targets):
        if not isinstance(target, dict):
            continue
        axis_id = target.get("axis_id")
        if not isinstance(axis_id, str) or not axis_id:
            continue
        if axis_id in targets_by_axis_id:
            raise DraftSetValidationError(
                "draft-set validation failed: "
                f"exploration_contract.coverage_targets[{index}].axis_id duplicates {axis_id}"
            )
        targets_by_axis_id[axis_id] = target
    return targets_by_axis_id


def _validate_domain_pack_coverage_target_provenance(coverage_targets: Any) -> None:
    for target in coverage_targets:
        if not isinstance(target, dict) or target.get("source") != "domain_pack":
            continue
        axis_id = str(target.get("axis_id") or "")
        pack_id = str(target.get("domain_pack_id") or "")
        axis = str(target.get("domain_axis_id") or "")
        layer = str(target.get("value") or "")
        expected_axis_id = f"domain_pack.{pack_id}.{axis}.{layer}"
        if axis_id != expected_axis_id:
            raise DraftSetValidationError(
                "draft-set validation failed: "
                f"domain_pack coverage target {axis_id} must match provenance id {expected_axis_id}"
            )


def _validate_coverage_target_references(
    payload: dict[str, Any],
    targets_by_axis_id: dict[str, dict[str, Any]],
) -> None:
    draft_decisions = payload.get("draft_decisions")
    if not isinstance(draft_decisions, list):
        return
    for draft_index, draft in enumerate(draft_decisions):
        if not isinstance(draft, dict):
            continue
        draft_layer = draft.get("layer")
        coverage_target_ids = draft.get("coverage_target_ids")
        if coverage_target_ids is None:
            continue
        if not isinstance(coverage_target_ids, list):
            continue
        for target_index, target_id in enumerate(coverage_target_ids):
            if not isinstance(target_id, str):
                continue
            target = targets_by_axis_id.get(target_id)
            if target is None:
                raise DraftSetValidationError(
                    "draft-set validation failed: "
                    f"draft_decisions[{draft_index}].coverage_target_ids[{target_index}] "
                    f"references unknown coverage target {target_id}"
                )
            if target.get("axis_type") == "decision_stack_layer" and draft_layer != target.get("value"):
                raise DraftSetValidationError(
                    "draft-set validation failed: "
                    f"draft_decisions[{draft_index}].coverage_target_ids[{target_index}] "
                    f"references {target_id} with layer {target.get('value')}, "
                    f"but draft layer is {draft_layer}"
                )


def _source_context_domain_pack(ai_dir: str | Path | None, source_context: dict[str, Any]) -> DomainPack:
    pack_id = _source_context_domain_pack_id(source_context)
    source_context["domain_pack_id"] = pack_id
    return _load_domain_pack(ai_dir, pack_id)


def _source_context_domain_pack_id(source_context: dict[str, Any]) -> str:
    if "domain_pack_id" not in source_context:
        return GENERIC_PACK_ID
    pack_id = source_context["domain_pack_id"]
    if not isinstance(pack_id, str) or not pack_id.strip():
        raise DraftSetValidationError(
            "draft-set validation failed: source_context.domain_pack_id must be a non-empty string"
        )
    return pack_id.strip()


def _load_domain_pack(ai_dir: str | Path | None, pack_id: str) -> DomainPack:
    try:
        return load_domain_registry(ai_dir).get(pack_id)
    except KeyError as exc:
        raise DraftSetValidationError(f"draft-set validation failed: unknown domain pack: {pack_id}") from exc
    except DomainPackLoadError as exc:
        raise DraftSetValidationError(f"draft-set validation failed: cannot load domain packs: {exc}") from exc


def _core_layer_coverage_targets() -> list[dict[str, Any]]:
    return [
        {
            "axis_id": f"core.layer.{layer}",
            "axis_type": "decision_stack_layer",
            "value": layer,
            "priority": "P1",
            "required": True,
            "source": "core",
            "label": layer.replace("_", " ").title(),
            "match_policy": "layer_complete",
        }
        for layer in DECISION_STACK_LAYER_ORDER
    ]


def _domain_pack_coverage_targets(pack: DomainPack) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for axis in pack.exploration_axes:
        for layer in axis.required_layers:
            targets.append(
                {
                    "axis_id": f"domain_pack.{pack.pack_id}.{axis.id}.{layer}",
                    "axis_type": "decision_stack_layer",
                    "value": layer,
                    "priority": axis.default_priority,
                    "required": axis.required,
                    "source": "domain_pack",
                    "domain_pack_id": pack.pack_id,
                    "domain_axis_id": axis.id,
                    "label": axis.label,
                    "match_policy": "explicit_target_or_domain_axis",
                }
            )
    return targets


def _counts(draft_set: dict[str, Any]) -> dict[str, int]:
    return {field: len(draft_set.get(field, [])) for field in DRAFT_SET_COUNTS}


def _summary(draft_set: dict[str, Any], *, current_head: str, path: Path) -> dict[str, Any]:
    generated_head = draft_set["source_context"]["project_head_at_generation"]
    is_stale = generated_head != current_head
    return {
        "id": draft_set["id"],
        "status": draft_set["status"],
        "mode": draft_set["mode"],
        "created_at": draft_set["created_at"],
        "goal_title": draft_set["goal"]["title"],
        "draft_decision_count": len(draft_set.get("draft_decisions", [])),
        "project_head_at_generation": generated_head,
        "current_project_head": current_head,
        "is_stale": is_stale,
        "path": str(path),
    }


def _schema_validator() -> Draft202012Validator:
    if not hasattr(_schema_validator, "_validator"):
        schema = json.loads(DRAFT_SET_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _schema_validator._validator = Draft202012Validator(schema, format_checker=FormatChecker())  # type: ignore[attr-defined]
    return _schema_validator._validator  # type: ignore[attr-defined]


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
