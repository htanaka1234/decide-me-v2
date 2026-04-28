# Invalidation Candidates

Phase 6-4 adds read-only invalidation candidate generation on top of impact analysis. It answers:
given an upstream change and the affected objects found by Phase 6-3, which objects should a
human review, revalidate, revise, invalidate, supersede, verify, or update next?

Invalidation candidates are recommendations only. This phase does not mutate runtime state, does
not write events, does not change object status, and does not create `invalidates` or `supersedes`
links. Phase 6-5 exposes candidates through CLI and impact report exports, but approval,
candidate acceptance, and conversion into events remain out of scope.

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
`proposed_events` is empty, no candidates are accepted, and no `object_status_changed` or
`object_linked` events are emitted.

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
- `proposed_events`
- `requires_human_approval`
- `source_impact`

`proposed_events` is always an empty array in Phase 6-4. It is reserved for a later approval phase
that may convert approved candidates into `object_status_changed` or `object_linked` events.

`candidate_id` is deterministic. It is derived from the root object ID, change kind, target object
ID, candidate kind, and source link ID so repeated runs can compare candidate sets without treating
them as persisted runtime state.

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
