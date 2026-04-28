# Link Relations

Links are directed edges from `source_object_id` to `target_object_id`.

Common link envelope:

- `id`: stable link id.
- `source_object_id`: object id where the relation starts.
- `relation`: one of the defined relation names.
- `target_object_id`: object id where the relation points.
- `rationale`: short explanation for the edge, or `null`.
- `created_at`: timestamp from the event that created the link.
- `source_event_ids`: effective event ids that justify the projected link.

Defined relations:

- `depends_on`: source cannot be resolved, executed, or evaluated without the target.
- `supports`: source provides positive evidence, rationale, or weight for the target.
- `challenges`: source conflicts with, weakens, or raises doubt about the target.
- `recommends`: source proposal recommends the target option, action, or decision outcome.
- `accepts`: source decision accepts the target proposal, option, assumption, or action.
- `addresses`: source action, decision, proposal, or verification addresses the target objective,
  constraint, risk, criterion, or revisit trigger.
- `verifies`: source verification or evidence verifies the target object.
- `revisits`: source revisit trigger re-opens or calls attention back to the target object.
- `supersedes`: source replaces the target. Normal outputs should prefer the source while retaining
  the target in event history.
- `blocked_by`: source is blocked by the target risk, constraint, missing evidence, open decision,
  or action.
- `constrains`: source narrows or limits the acceptable target outcomes, designs, or execution
  paths.
- `enables`: source makes the target possible, easier, or appropriate to perform.
- `requires`: source has the target as a required prerequisite.
- `invalidates`: source makes the target no longer valid. Phase 6-1 records the edge only; it does
  not cascade status changes.
- `mitigates`: source reduces the likelihood or impact of the target risk or concern.
- `derived_from`: source was produced from, refined from, or copied from the target.

Direction rules:

- Use active phrasing from source to target: evidence `supports` proposal, decision `accepts`
  proposal, action `addresses` risk.
- Do not create inverse relation names. Query code can derive reverse views from the link set.
- Do not store relation arrays on objects such as `depends_on`, `blocked_by`, `options`, or
  `evidence`.
- When a semantic relation changes, project a new event-derived link state instead of editing a
  human-readable export.
