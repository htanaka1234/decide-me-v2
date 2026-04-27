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
- support derived architecture and traceability exports from the same closed-session inputs
- treat generated arc42 docs, traceability matrices, and verification gap reports as exports,
  never as runtime state

Minimum conflict checks:

- same decision ID with different accepted answers
- mutually exclusive workstream scopes
- same action-slice name with different responsibilities

Conflict ids and resolution:

- Planner conflicts include deterministic `conflict_id`, `session_ids`, `scope`, and
  `requires_resolution`.
- `semantic_conflict_resolved` suppresses only the matching losing scope from normal projections.
- When assembling an action plan after resolution, remove only the losing session's scoped item.
  Other accepted decisions, action slices, and workstreams from the losing session remain eligible.
- `detect-session-conflicts --include-related` lists explicit graph relatives first, then reports
  unresolved and resolved semantic conflicts for that graph scope.
- Decision replacements are resolved with `resolve-decision-supersession`, which emits the
  underlying `decision_invalidated` event and removes the superseded decision from normal plan
  inputs.

If unresolved `P0` decisions with `frontier=now` remain, the planner must return a conditional
plan instead of claiming the work is ready.

Phase 4 derived exports:

- `export-architecture-doc --format arc42` renders a Markdown architecture skeleton from closed
  sessions, action slices, final decisions, risks, blockers, and taxonomy terms.
- `export-traceability --format csv|markdown` renders action slices and unresolved blocker/risk
  rows with stable derived `R-###` requirement IDs.
- `export-verification-gaps` reports implementation-ready rows with no explicit test evidence and
  rows with no recorded evidence refs.
- The explicit verification rule is conservative: only tests evidence or `resolvable_by=tests`
  counts as verification already defined.
- Unresolved planner conflicts must fail these exports before writing output.
