# Migration From Legacy Model

Phase 5 is a breaking migration from the legacy decision projection to the domain-neutral object
graph.

What is removed:

- Top-level `project-state.json.decisions`.
- Top-level `project-state.json.proposals`.
- Top-level `project-state.json.action_slices`.
- Decision attributes that embed options, recommendations, accepted answers, evidence refs, risks,
  blockers, revisit triggers, or action slices as nested state.

What replaces it:

- Legacy decisions become `decision` objects.
- Legacy decision options become `option` objects.
- Legacy recommendations become `proposal` objects.
- Legacy accepted answers are represented by `decision accepts proposal` and related links.
- Legacy evidence refs become `evidence` objects linked with `supports`, `challenges`, or
  `verifies`.
- Legacy blockers and risks become `risk` or `constraint` objects linked with `blocked_by` or
  `challenges`.
- Legacy action slices become `action` objects linked with `addresses`, `depends_on`, `blocked_by`,
  or `verifies`.
- Legacy revisit triggers become `revisit_trigger` objects linked with `revisits`.

Migration policy:

- There is no automatic compatibility layer in Phase 5-1.
- New schemas reject legacy projection shapes so invalid old state fails clearly.
- A future migration command, if added, must read legacy event logs or exported legacy state and
  emit explicit Phase 5 events. It must not silently reinterpret old projections at runtime.
- Human-readable legacy plans, ADRs, and summaries may be used as evidence for a migration, but
  they must not become canonical runtime state.
- After migration, rebuilding projections from Phase 5 events must recreate the same objects,
  links, counts, and project head.

Phase 5-1 scope:

- Define the new object and link contracts.
- Define the new `project-state.json` shape.
- Document the intended mapping from legacy concepts.
- Do not change the current runtime projection code in this PR.

