# Impact Analysis

Phase 6-3 adds read-only impact analysis over the Decision Stack Graph. It answers: if one
object changes, is challenged, is invalidated, is superseded, has an assumption fail, or has
evidence retracted, which downstream objects should a human reconsider?

Impact analysis is diagnostic only. It does not mutate runtime state, does not write events, does
not create `invalidates` links, and does not call `object_status_changed`. Automatic invalidation,
invalidation candidates, approval workflow, CLI commands, and exports are deferred to later
phases.

## API

Use `analyze_impact(project_state, object_id, *, change_kind, max_depth=None,
include_invalidated=False)` from `decide_me.impact_analysis`.

Allowed `change_kind` values are:

- `changed`
- `invalidated`
- `superseded`
- `challenged`
- `assumption_failed`
- `evidence_retracted`

The function validates that the root object exists in `project_state.graph.nodes[]`. Unknown root
objects and unknown change kinds raise `ValueError`.

## Traversal

Impact analysis uses `descendants_with_paths(..., direction="influence")` from the graph traversal
helpers. This follows Phase 6-2 influence direction semantics and returns path evidence without
changing the existing `descendants()` return shape.

`max_depth=None` walks all reachable downstream objects. `max_depth=0` returns no affected
objects. Cycles are bounded by the traversal visited set and cannot loop forever.

By default, invalidated target objects are excluded from the affected object list. Traversal still
walks through invalidated bridge nodes, so a live downstream object is not hidden only because an
intermediate graph node is already invalidated. Passing `include_invalidated=True` includes
invalidated target objects.

## Output

The result matches `schemas/impact-analysis.schema.json` and contains:

- `root_object_id`
- `change_kind`
- `generated_at`
- `summary`
- `affected_objects`
- `affected_links`
- `paths`

`affected_objects` has one entry per affected object. Duplicate routes to the same object are kept
in `paths`; the object entry keeps the strongest severity, then shortest distance, then smallest
link ID when multiple routes exist.

`affected_links` is a stable unique list of link IDs from retained paths. `summary.affected_count`
counts unique affected objects. `summary.affected_layers` follows the Decision Stack Graph layer
order.

## Classification

Classification is based on target object type, target status, and the relation used to reach the
target. The final severity is the higher of the object severity and relation severity.

Object classification:

- accepted `decision`: `decision_review_required`, `high`
- other `decision`: `decision_review_required`, `medium`
- `action`: `action_rework_candidate`, `medium`
- `verification`: `verification_review_required`, `medium`
- `evidence`: `evidence_review_required`, `medium`
- `risk`: `risk_review_required`, `medium`
- `revisit_trigger`: `revisit_condition_review`, `low`
- other object types: `object_review_required`, `low`

Relation severity:

- `invalidates`, `constrains`, `requires`, `depends_on`, `blocked_by`, `accepts`,
  `challenges`, `supersedes`: `high`
- `addresses`, `supports`, `verifies`, `mitigates`, `derived_from`, `enables`,
  `recommends`: `medium`
- `revisits`: `low`
