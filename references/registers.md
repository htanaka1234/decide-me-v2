# Register Projections

Step 2 adds read-only register projections for Phase 7 preparation. Registers are derived JSON
views over `project_state.objects` and `project_state.links`; they are not persisted in
`project-state.json` and are not runtime source of truth. The event log remains canonical.

## Commands

Use these commands to inspect the typed Phase 7 inputs:

```bash
python3 scripts/decide_me.py show-evidence-register --ai-dir .ai/decide-me
python3 scripts/decide_me.py show-assumption-register --ai-dir .ai/decide-me
python3 scripts/decide_me.py show-risk-register --ai-dir .ai/decide-me
```

Each command reads the persisted runtime projection, builds a deterministic register payload, and
prints JSON to stdout. The commands do not emit events, update projections, create approval
objects, evaluate gates, or mark stale items.

## Output Contract

All register payloads use `schemas/registers.schema.json`:

- `schema_version`: register schema version.
- `register_type`: `evidence`, `assumption`, or `risk`.
- `project_head`: copied from `project_state.state.project_head`.
- `generated_at`: copied from `project_state.state.updated_at` for reproducible read-only output.
- `summary`: type-specific counts.
- `items`: sorted by `object_id`.

## Evidence Register

Evidence items expose the strict typed metadata contract:

- `source`
- `source_ref`
- `summary`
- `confidence`
- `freshness`
- `observed_at`
- `valid_until`

The register also groups outgoing `supports`, `challenges`, and `verifies` links into
`supports_object_ids`, `challenges_object_ids`, `verifies_object_ids`, and `related_link_ids`.

## Assumption Register

Assumption items expose:

- `statement`
- `confidence`
- `validation`
- `invalidates_if_false`
- `expires_at`
- `owner`

The register also groups outgoing `constrains`, `requires`, `derived_from`, and `invalidates`
links into relation-specific target id lists and `related_link_ids`.

## Risk Register

Risk items expose the fields that Step 3 safety gate evaluation will consume:

- `statement`
- `severity`
- `likelihood`
- `risk_tier`
- `reversibility`
- `mitigation_object_ids`
- `approval_threshold`

The register treats `mitigates` as an incoming relation to the risk. It exposes mitigation sources
as `mitigated_by_object_ids`, `mitigation_link_ids`, and `related_link_ids`.

## Boundary

Register projections intentionally stop before safety gate behavior. Step 3 is responsible for
machine evaluation such as evidence coverage, approval requirement, risk tier blocking reasons,
and gate result status. Step 4 is responsible for stale evidence, stale assumptions, verification
gaps, and due revisit diagnostics.

Step 3 safety gate evaluation is exposed through `show-safety-gate` and `show-safety-gates`.
Those commands consume the same object/link facts but remain read-only diagnostics. They do not
persist register or gate state.

Step 4 stale detection is exposed through `show-stale-assumptions`, `show-stale-evidence`,
`show-verification-gaps`, and `show-revisit-due`. Those commands also consume typed object
metadata and links directly from `project-state.json`. `show-verification-gaps` returns structured
JSON, while `export-verification-gaps` remains the derived Markdown export.
