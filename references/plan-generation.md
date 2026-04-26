# Plan Generation

Only closed sessions can feed the planner.

The planner returns one of two shapes:

- `Conflicts:` when accepted decisions or workstream scopes disagree
- `Action Plan:` when sessions can be merged into a coherent plan

For `Action Plan:` output:

- preserve merged `action_slices`
- surface `implementation_ready_slices` separately when slices are already evidence-backed or
  otherwise ready to execute
- keep evidence-backed slices near the top of the merged action list

Minimum conflict checks:

- same decision ID with different accepted answers
- mutually exclusive workstream scopes
- same action-slice name with different responsibilities

Conflict ids and resolution:

- Planner conflicts include deterministic `conflict_id`, `session_ids`, `scope`, and
  `requires_resolution`.
- `semantic_conflict_resolved` suppresses only the matching scoped conflict id.
- When assembling an action plan after resolution, remove only the losing session's scoped item.
  Other accepted decisions, action slices, and workstreams from the losing session remain eligible.
- `detect-session-conflicts --include-related` lists explicit graph relatives first, then reports
  unresolved and resolved semantic conflicts for that graph scope.

If unresolved `P0` decisions with `frontier=now` remain, the planner must return a conditional
plan instead of claiming the work is ready.
