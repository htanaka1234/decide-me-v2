# Invalidation Candidates

Phase 6-4 adds read-only invalidation candidate generation on top of impact analysis. It answers:
given an upstream change and the affected objects found by Phase 6-3, which objects should a
human review, revalidate, revise, invalidate, supersede, verify, or update next?

Invalidation candidates are recommendations only. This diagnostic does not mutate runtime state,
does not write events, does not change object status, and does not create `invalidates` or
`supersedes` links. Step 5 materializes deterministic event specs for candidates that can be
represented mechanically and pass the existing event/projection validators, but approval,
candidate acceptance, and event application remain out of scope.

## API

Use `generate_invalidation_candidates(project_state, object_id, *, change_kind, max_depth=None,
include_low_severity=False, include_invalidated=False)` from
`decide_me.invalidation_candidates`.

The function calls `analyze_impact()` internally, so `change_kind`, root object validation,
traversal, `max_depth`, and `include_invalidated` follow the impact analysis contract.
`project_state` is treated as read-only.

Candidate rules are scoped to the same impact depth. For `add_verification`, the downstream
verification/evidence existence check is limited to the remaining depth after reaching the affected
action. For example, `max_depth=1` can emit `add_verification` for a directly affected action even
when a verification object exists two hops from the root.

Allowed candidate kinds are:

- `review`
- `revalidate`
- `revise`
- `invalidate`
- `supersede`
- `add_verification`
- `update_revisit_trigger`

## CLI

Use `show-invalidation-candidates` for a JSON diagnostic view:

```bash
python3 scripts/decide_me.py show-invalidation-candidates \
  --ai-dir .ai/decide-me \
  --object-id CON-001 \
  --change-kind changed \
  --max-depth 3
```

Optional `--include-low-severity` includes low-severity candidate rows. Optional
`--include-invalidated` includes already invalidated targets in the underlying impact analysis.
The command prints `generate_invalidation_candidates()` output as JSON and remains read-only:
`proposed_events` may contain event specs, but no candidates are accepted and no
`object_status_changed`, `object_updated`, `object_recorded`, or `object_linked` events are
emitted.

## Output

The result matches `schemas/invalidation-candidates.schema.json` and contains:

- `root_object_id`
- `change_kind`
- `generated_at`
- `impact_summary`
- `candidates`

`impact_summary` is copied from the underlying impact report before candidate filtering. For
example, it may still report low-severity affected objects even when `include_low_severity=False`
causes low-severity candidates to be omitted.

Each candidate contains:

- `candidate_id`
- `target_object_id`
- `target_object_type`
- `target_status`
- `layer`
- `severity`
- `candidate_kind`
- `reason`
- `requires_human_approval`
- `approval_threshold`
- `materialization_status`
- `materialization_reason`
- `proposed_events`
- `source_impact`

`proposed_events` contains event specs shaped as `{event_id, event_type, ts, payload}`. Specs are
not persisted event envelopes: `session_id` and transaction fields are intentionally omitted for
the later apply workflow to fill. Payloads include the runtime-required object/link timestamps,
source event ids, `changed_at`, and decision `invalidated_by.invalidated_at` fields so an apply
workflow can wrap them with the existing event builder and validate the resulting projection.

`approval_threshold` is `explicit_acceptance` when `requires_human_approval` is true, otherwise
`none`. `materialization_status` is `materialized` when deterministic event specs are present and
`manual` when a human-authored change is required before the candidate can become events. Decision
invalidation and supersession candidates are materialized only when the invalidating root is a
final decision that satisfies the current `invalidated_by.decision_id` contract.

`candidate_id` is deterministic. It is derived from the root object ID, change kind, target object
ID, candidate kind, and source link ID so repeated runs can compare candidate sets without treating
them as persisted runtime state.

## Future Apply Guard

Phase 7 does not add `apply-invalidation-candidate`. If that workflow is added later, it must
evaluate the safety gate for the candidate target before writing events. Blocked gates must stop the
apply. Gates that need approval must require a matching safety approval artifact before proposed
events are wrapped into a normal transaction.

## Classification

Low-severity candidates are filtered out unless `include_low_severity=True`.

Accepted decisions affected by `change_kind="invalidated"` become `invalidate` candidates.
Accepted decisions affected by `change_kind="superseded"` become `supersede` candidates.
Other high-severity accepted decision impacts become `revalidate` candidates. Unresolved,
proposed, and blocked decisions become `review` candidates.

Actions become `revise` candidates. When the changed root is an invalidated decision, affected
actions also get `invalidate` candidates. Actions with no live downstream verification or evidence
within the remaining impact depth also get `add_verification` candidates.

Verification and evidence objects become `revalidate` candidates, except affected evidence becomes
an `invalidate` candidate when `change_kind="evidence_retracted"`.

Risks reached through `mitigates` become `revalidate` candidates because their mitigation changed.
Other affected risks become `review` candidates. Revisit triggers become
`update_revisit_trigger` candidates. Other affected object types become `review` candidates.

## Materialization

Materialized candidates produce these event specs:

- `invalidate`: `object_status_changed`; decision targets also get `object_updated` for
  `metadata.invalidated_by`.
- `supersede`: decision invalidation specs plus an `object_linked` `supersedes` spec when the
  root object is a valid final decision.
- `add_verification`: a deterministic verification object spec and a `verifies` link spec.

`review`, `revalidate`, `revise`, and `update_revisit_trigger` are manual candidates. They keep
`proposed_events: []` because the correct runtime change depends on human-authored content.
