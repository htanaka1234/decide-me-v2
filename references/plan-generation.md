# Plan Generation

Only closed sessions can feed the planner.

The planner returns one of two shapes:

- `Conflicts:` when accepted answers or generated actions disagree
- `Action Plan:` when sessions can be merged into a coherent plan

For `Action Plan:` output:

- resolve plan content from `close_summary.object_ids`, `close_summary.link_ids`,
  `project_state.objects`, and `project_state.links`
- preserve merged `actions`
- surface `implementation_ready_actions` separately when actions are already evidence-backed or
  otherwise ready to execute
- keep evidence-backed actions near the top of the merged action list
- support derived architecture and traceability exports from the same closed-session inputs
- treat generated arc42 docs, traceability matrices, and verification gap reports as exports,
  never as runtime state

Minimum conflict checks:

- same decision ID with different accepted answers
- same action name with different responsibilities

Conflict ids and resolution:

- Planner conflicts include deterministic `conflict_id`, `session_ids`, `scope`, and
  `requires_resolution`.
- Phase 5-3 does not persist explicit semantic conflict resolution events; plan generation should
  surface unresolved conflicts rather than silently choosing between incompatible closed sessions.
- When assembling an action plan after resolution, remove only the losing session's scoped item.
  Other object/link references from the losing session remain eligible.
- `detect-session-conflicts --include-related` lists explicit graph relatives first, then reports
  unresolved and resolved semantic conflicts for that graph scope.
- Decision replacements are resolved with `resolve-decision-supersession`, which emits the
  underlying object status/update plus `supersedes` link events and removes the superseded decision from normal plan
  inputs.

If unresolved `P0` decisions with `frontier=now` remain, the planner must return a conditional
plan instead of claiming the work is ready.

Phase 4 derived exports:

- `export-architecture-doc --format arc42` renders a Markdown architecture skeleton from closed
  sessions, actions, final decisions, risks, blockers, and taxonomy terms.
- `export-traceability --format csv|markdown` renders action and unresolved blocker/risk
  rows with stable derived `R-###` requirement IDs.
- `export-verification-gaps` reports implementation-ready rows with no explicit test evidence and
  rows with no recorded evidence refs.
- The explicit verification rule is conservative: only `evidence_source=tests` or test-file
  evidence refs count as verification already defined. `resolvable_by=tests` is only used for
  suggested verification.
- Unresolved planner conflicts must fail these exports before writing output.
