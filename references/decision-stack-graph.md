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

## Traversal Direction Semantics

Phase 6-2 adds read-only traversal helpers over `project_state.graph.nodes[]` and
`project_state.graph.edges[]`. The helpers do not read `project_state.objects`,
`project_state.links`, or event logs, and they do not edit graph projection state.

Traversal supports two direction modes. Public traversal helpers default to `influence`; callers
must explicitly pass `direction="raw"` when they need stored edge direction.

- `raw`: always follows the stored link direction, `source_object_id -> target_object_id`.
- `influence`: follows the direction in which one object influences another for later impact
  analysis foundations.

In `influence` mode, these relations are traversed in reverse of the stored link direction:

- `depends_on`
- `blocked_by`
- `requires`
- `addresses`
- `accepts`
- `derived_from`

In `influence` mode, these relations are traversed in the stored link direction:

- `constrains`
- `enables`
- `invalidates`
- `mitigates`
- `supports`
- `challenges`
- `verifies`
- `revisits`
- `supersedes`
- `recommends`

`direct_upstream()`, `direct_downstream()`, `ancestors()`, and `descendants()` return edge context
items, not only object IDs:

- `object_id`
- `layer`
- `via_link_id`
- `relation`
- `distance`

`descendants_with_paths()` preserves the same downstream traversal semantics as `descendants()`
and adds `path.node_ids` plus `path.link_ids` for each returned item. It is intended for
diagnostics that need path evidence, including impact analysis, without changing the existing
`descendants()` shape.

Path output uses the same node-level visited traversal as `descendants()`. It is representative
path evidence, not exhaustive all-path enumeration through convergent graph nodes. Duplicate direct
paths to the same target may be returned, but once traversal reaches a convergent node, deeper
descendants are explored from the first visited route.

Use `direct_upstream_ids()`, `direct_downstream_ids()`, `ancestor_ids()`, or `descendant_ids()`
when only stable unique object IDs are needed.

`ancestors()` and `descendants()` perform breadth-first traversal, exclude the seed object from
returned items, and track visited object IDs so cycles cannot loop forever. `max_depth=None` means
unbounded traversal, `max_depth=0` returns no transitive items, and negative depths are invalid.

`relations` filters by raw relation name and is a traversal boundary. `layers` filters returned
neighboring node layers only; traversal continues through non-matching intermediate layers. For
example, `objective -> decision -> action` with `layers={"execution"}` still reaches the action.

`bounded_subgraph()` returns `root_object_id`, `nodes`, and `edges`. It uses asymmetric
`upstream_depth` and `downstream_depth`, defaults to one upstream hop and two downstream hops, and
returns original graph edge records rather than synthetic oriented edges. The seed node is included
even when a layer filter is present. When `layers` is set, matching reachable nodes are filtered,
but bridge nodes and edges required to show the path from the root to each matching node are also
included so the returned subgraph is not disconnected from its traversal evidence.

Use `show-decision-stack` for a JSON bounded graph view from the CLI:

```bash
python3 scripts/decide_me.py show-decision-stack \
  --ai-dir .ai/decide-me \
  --object-id DEC-001 \
  --upstream-depth 2 \
  --downstream-depth 3
```

The command reads `project-state.json`, builds the graph index, calls `bounded_subgraph()`, and
prints `root_object_id`, `nodes`, and `edges`. It is a read-only diagnostic and does not emit
events or update runtime projections.

`objects_by_layer(project_state, layer)` reads only `project_state.graph.nodes[]`, returns graph
node payloads for the requested layer, and excludes invalidated nodes unless
`include_invalidated=True` is passed.

Phase 6-3 adds read-only impact analysis on top of these helpers. Phase 6-4 adds read-only
invalidation candidates derived from that impact report. Phase 6-5 exposes these diagnostics
through CLI commands and derived Markdown impact reports. These diagnostics do not cascade
invalidation, create links, change object status, accept candidates, or run approval workflows.

## Phase 6-1 Boundary

Phase 6-1 fixes only the layer set, relation enum, graph node and edge shape, projection rebuild,
and validation rules. It does not implement impact analysis or cascading invalidation. In
particular, an `invalidates` link does not automatically update the target object's status or
propagate invalidation through downstream graph edges.
