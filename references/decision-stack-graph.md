# Decision Stack Graph

Phase 6-1 adds a deterministic Decision Stack Graph projection under `project_state.graph`.
The graph is rebuilt from `project_state.objects` and `project_state.links`; it is not canonical
state and must not be edited directly. The event log remains the only runtime source of truth.

## Layers

The fixed decision stack layers are:

- `purpose`: desired outcomes and intent.
- `principle`: criteria and standing rules that guide choices.
- `constraint`: assumptions, boundaries, risks, and limits.
- `strategy`: recommended direction, options, and decisions before detailed design.
- `design`: concrete design artifacts and specified solution shape.
- `execution`: implementation work and produced artifacts.
- `verification`: checks, criteria, evidence, and proof.
- `review`: revisit and review triggers.

## Layer Inference

Objects may carry optional `metadata.layer`. When present, validation requires it to be one of
the fixed layer names above. `schemas/object.schema.json` keeps metadata open; runtime validation
enforces the layer contract.

When `metadata.layer` is missing, the graph projection uses this default mapping:

- `objective` -> `purpose`
- `assumption`, `constraint`, `risk` -> `constraint`
- `criterion` -> `principle`
- `proposal`, `option`, `decision` -> `strategy`
- `artifact` -> `design`
- `action` -> `execution`
- `evidence`, `verification` -> `verification`
- `revisit_trigger` -> `review`

`metadata.stack_role` is intentionally deferred from Phase 6-1. It must not affect graph
projection or validation until a later contract explicitly defines stack roles.

## Graph Shape

`project_state.graph.nodes[]` is derived from objects:

- `object_id`
- `object_type`
- `layer`
- `status`
- `title`
- `is_frontier`: `true` only when `object.metadata.frontier == "now"`
- `is_invalidated`: `true` only when `object.status == "invalidated"`

`project_state.graph.edges[]` is derived from links:

- `link_id`
- `source_object_id`
- `relation`
- `target_object_id`
- `source_layer`
- `target_layer`

`resolved_conflicts` and `inferred_candidates` remain auxiliary projection fields. Persisted
`inferred_candidates` stays empty; inference may be generated for commands when requested.

## Relation Semantics

The Decision Stack Graph uses the object/link relation enum:

- `depends_on`: source cannot be resolved, executed, or evaluated without the target.
- `supports`: source provides positive evidence, rationale, or weight for the target.
- `challenges`: source conflicts with, weakens, or raises doubt about the target.
- `recommends`: source proposal recommends the target option, action, or decision outcome.
- `accepts`: source decision accepts the target proposal, option, assumption, or action.
- `addresses`: source action, decision, proposal, or verification addresses the target.
- `verifies`: source verification or evidence verifies the target object.
- `revisits`: source revisit trigger calls attention back to the target object.
- `supersedes`: source replaces the target while preserving event history.
- `blocked_by`: source is blocked by the target.
- `constrains`: source narrows or limits acceptable target outcomes or implementations.
- `enables`: source makes the target possible or easier to perform.
- `requires`: source has the target as a required prerequisite.
- `invalidates`: source makes the target no longer valid.
- `mitigates`: source reduces the likelihood or impact of the target risk or concern.
- `derived_from`: source was produced from, refined from, or copied from the target.

## Phase 6-1 Boundary

Phase 6-1 fixes only the layer set, relation enum, graph node and edge shape, projection rebuild,
and validation rules. It does not implement impact analysis or cascading invalidation. In
particular, an `invalidates` link does not automatically update the target object's status or
propagate invalidation through downstream graph edges.
