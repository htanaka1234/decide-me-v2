# Safety Gates

Phase 7 adds safety gate evaluation on top of typed metadata contracts and register projections.
Safety gate commands remain diagnostic JSON views and are not persisted in `project-state.json`.
Approval state is represented separately as normal `artifact` objects and `addresses` links.

## Commands

Inspect one object:

```bash
python3 scripts/decide_me.py show-safety-gate \
  --ai-dir .ai/decide-me \
  --object-id DEC-001
```

Inspect all default gate targets:

```bash
python3 scripts/decide_me.py show-safety-gates --ai-dir .ai/decide-me
```

`show-safety-gates` evaluates live `decision` and `action` objects. Use `show-safety-gate` for
any other object type that needs an explicit diagnostic check.

Both commands accept `--now`. When omitted, they use `project_state.state.updated_at` so a fixed
projection produces stable diagnostics.

## Evaluation Inputs

Safety gates read only `project_state.objects` and `project_state.links`.

Evidence:

- Incoming live evidence linked with `supports` or `verifies` is supporting evidence.
- Incoming live evidence linked with `challenges` is challenge evidence.
- Evidence is sufficient when at least one supporting item has `confidence` of `medium` or `high`
  and `freshness` of `current`, and no challenge evidence is present.

Assumptions:

- Incoming live assumptions linked with `constrains` or `invalidates` are related assumptions.
- Outgoing `requires` or `derived_from` links from the target to a live assumption are also related.
- Low-confidence assumptions produce a warning, not a blocking result.

Risks:

- Incoming live risks linked with `challenges`, `constrains`, or `invalidates` are related risks.
- Outgoing `blocked_by`, `addresses`, or `mitigates` links from the target to a live risk are
  related risks.
- A live risk is also related when `risk.metadata.mitigation_object_ids` contains the target id.
- The effective `risk_tier`, `approval_threshold`, and `reversibility` are the highest ranked
  values across related risks.
- Decision and action `metadata.reversibility` also contributes to effective reversibility. For
  actions, `irreversible` requires approval before the action can be implementation-ready.

Safety gates compare `valid_until`, `expires_at`, and action verification coverage at the selected
`as_of` time. Due revisit checks remain in `show-revisit-due`.

## Output

Single-object evaluation returns a safety gate result:

- `object_id`, `object_type`, `title`, `status`
- `as_of`
- `gate_status`: `passed`, `needs_approval`, or `blocked`
- `risk_tier`: `none`, `low`, `medium`, `high`, or `critical`
- `reversibility`: `unknown`, `reversible`, `partially_reversible`, or `irreversible`
- `evidence_coverage`: `sufficient`, `insufficient`, or `challenged`
- `approval_required`, `approval_satisfied`, `approval_artifact_ids`, and `approval_threshold`
- `risk_policy`: the effective domain-neutral or pack-overridden policy for the current risk tier
- `gate_digest` and `digest_inputs`
- `blocking_reasons`, `warning_reasons`, and `approval_reasons`
- `evidence`, `assumptions`, `risks`, and `source_link_ids`

Multi-object evaluation returns a report with `schema_version`, `project_head`, `generated_at`,
summary counts, and `results`. `generated_at` is copied from `project_state.state.updated_at` so
the diagnostic remains reproducible for a fixed projection.

Both output shapes are validated by `schemas/safety-gates.schema.json`.

## Status Rules

Blocking reasons:

- `target_invalidated`
- `critical_risk_tier`
- `insufficient_evidence`
- `challenged_evidence`
- `completed_action_verification_gap`

Approval reasons:

- `high_risk_tier`
- `irreversible_change`
- `insufficient_evidence_requires_approval`
- `action_verification_gap`
- `expired_assumption_review_required`
- `external_review_required`
- `human_review_required`
- `explicit_acceptance_required`

Warning reasons:

- `medium_risk_tier`
- `partially_reversible_change`
- `low_confidence_assumption`
- `expired_assumption`
- `stale_supporting_evidence`
- `insufficient_evidence`

`gate_status` is `blocked` when any blocking reason exists. Otherwise it is `passed` when no
approval is required, or when a current approval artifact matches the gate digest. Otherwise it is
`needs_approval`.

Insufficient evidence is tier-sensitive: `none` and `low` risk produce warnings, `medium` and
`high` risk require approval when approval reasons are present, and `critical` risk is blocked.
Challenge evidence is always blocked.

## Risk Policy

The domain-neutral default policy is:

- `low`: approval is optional.
- `medium`: explicit approval is required when the gate has approval reasons.
- `high`: explicit approval with rationale is required.
- `critical`: automatic adoption is blocked; explicit approval alone is insufficient.

`risk_policy` is part of `gate_digest`, so approval artifacts are tied to the policy in effect at
the time they were recorded. `risk_policy.automatic_adoption` is the effective gate state, not a
separate bypass path: blocking reasons make it `blocked`, approval reasons make it
`requires_approval`, and otherwise it is `allowed`. For `critical` risk, `risk_policy.reason` is
`critical_risk_requires_external_review`, `risk_policy.automatic_adoption` is `blocked`, and the
required actions are to record a safety approval, add external review evidence, split or defer the
decision, and reject or rework it when appropriate. A domain pack may override policy text and
required actions with an optional `risk_policy` section, but it cannot allow critical automatic
adoption or bypass ordinary blocking reasons such as challenged evidence or an invalidated target.
