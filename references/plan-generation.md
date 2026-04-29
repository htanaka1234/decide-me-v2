# Plan Generation

Only closed sessions can feed the planner.

The planner returns one of two shapes:

- `Conflicts:` when accepted proposals or generated actions disagree
- `Action Plan:` when sessions can be merged into a coherent plan

For `Action Plan:` output:

- resolve plan content from `close_summary.object_ids`, `close_summary.link_ids`,
  `project_state.objects`, and `project_state.links`
- preserve merged `actions`
- attach a compact `safety_gate` summary to actions
- surface `implementation_ready_actions` only when actions are declared ready and their safety gate
  is `passed`
- treat action-level `metadata.reversibility` as gate input, so irreversible actions require
  approval before they can become implementation-ready
- include object-native `evidence`, `source_object_ids`, and `source_link_ids`
- keep evidence-backed actions near the top of the merged action list
- support derived architecture and traceability exports from the same closed-session inputs
- treat generated arc42 docs, traceability matrices, and verification gap reports as exports,
  never as runtime state

Minimum conflict checks:

- same decision ID with multiple accepted proposal IDs
- same action name with different responsibilities

Conflict ids and resolution:

- Planner conflicts include deterministic `conflict_id`, `session_ids`, `scope`, and
  `requires_resolution`.
- The current domain-neutral event model does not persist explicit semantic conflict resolution
  events; plan generation should surface unresolved conflicts rather than silently choosing between
  incompatible closed sessions.
- When assembling an action plan after resolution, remove only the losing session's scoped item.
  Other object/link references from the losing session remain eligible.
- `detect-session-conflicts --include-related` lists explicit graph relatives first, then reports
  unresolved and resolved semantic conflicts for that graph scope.
- Decision replacements are resolved with `resolve-decision-supersession`, which emits the
  underlying object status/update plus `supersedes` link events and removes the superseded decision from normal plan
  inputs.

If unresolved `P0` decisions with `frontier=now` remain, the planner must return a conditional
plan instead of claiming the work is ready.

If a declared implementation-ready action has a `needs_approval` gate, the plan readiness is at
least `conditional` and the action is excluded from `implementation_ready_actions`. If such an
action has a `blocked` gate, plan readiness is `blocked`.

Derived software-oriented exports:

- `export-architecture-doc --format arc42` renders a Markdown architecture skeleton from closed
  sessions, actions, final decisions, risks, blockers, and taxonomy terms.
- `export-traceability --format csv|markdown` renders action and unresolved blocker/risk
  rows with stable derived `R-###` requirement IDs.
- `export-verification-gaps` reports implementation-ready rows with no explicit test evidence and
  rows with no recorded evidence.
- The explicit verification rule is conservative: only `evidence_source=tests` or test-file
  evidence references count as verification already defined. `resolvable_by=tests` is only used for
  suggested verification.
- Unresolved planner conflicts must fail these exports before writing output.
