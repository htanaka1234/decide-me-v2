# Safety Gates

Step 3 adds read-only safety gate evaluation on top of typed metadata contracts and register
projections. Safety gates are diagnostic JSON views. They are not persisted in `project-state.json`
and do not write events, create approval objects, apply invalidation candidates, or mark stale
objects.

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

Step 3 intentionally does not compare timestamps. `valid_until`, `expires_at`, verification gaps,
and due revisit checks belong to the Step 4 stale-detection diagnostics exposed through
`show-stale-assumptions`, `show-stale-evidence`, `show-verification-gaps`, and
`show-revisit-due`.

## Output

Single-object evaluation returns a safety gate result:

- `object_id`, `object_type`, `title`, `status`
- `gate_status`: `passed`, `needs_approval`, or `blocked`
- `risk_tier`: `none`, `low`, `medium`, `high`, or `critical`
- `reversibility`: `unknown`, `reversible`, `partially_reversible`, or `irreversible`
- `evidence_coverage`: `sufficient`, `insufficient`, or `challenged`
- `approval_required` and `approval_threshold`
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

Approval reasons:

- `high_risk_tier`
- `irreversible_change`
- `external_review_required`
- `human_review_required`
- `explicit_acceptance_required`

Warning reasons:

- `medium_risk_tier`
- `partially_reversible_change`
- `low_confidence_assumption`

`gate_status` is `blocked` when any blocking reason exists, otherwise `needs_approval` when any
approval reason exists, otherwise `passed`.

Stale diagnostics are separate read-only inputs for later gate phases. They do not change these
status rules in Step 4.
