# Output Contract

Question turns must include:

- `Decision:`
- `Proposal:`
- `Question:`
- `Recommendation:`
- `Why:`
- `If not:`

Acceptance turns must include:

- `Accepted: D-...` or `Accepted: B-...`

Close-session turns must include:

- `Closed: S-...`
- the generated object/link close summary

Close summary payloads must include:

- `work_item`
- `readiness`
- `object_ids`
- `link_ids`
- `generated_at`

`close_summary.object_ids` groups referenced object IDs by section, including decisions, blockers,
risks, actions, evidence, verifications, and revisit triggers. Decision acceptance or deferral is
read from each referenced decision object’s `status`. `close_summary.link_ids` lists the links that
justify or connect those objects.

Plan-generation turns must include one of:

- `Conflicts:`
- `Action Plan:`

Action plan payloads must include `readiness`, `goals`, `workstreams`, `actions`,
`implementation_ready_actions`, `blockers`, `risks`, `evidence`, `source_object_ids`, and
`source_link_ids`. Plan payloads are closed to additional fields.
In generated plan JSON, executable work lives under `plan.action_plan.actions`; already-ready work
lives under `plan.action_plan.implementation_ready_actions`.

Exported files are derived outputs, not runtime state.

Structured ADR exports must include stable YAML frontmatter with:

- `id`, `title`, `status`, `domain`, `kind`, `priority`, `frontier`
- `session_id`, `accepted_via`, `supersedes`, `superseded_by`, `depends_on`
- `evidence`
- `risk`
- `audit`

Structured ADR `risk.technical` and `risk.operational` are reserved fields. Until the
decision model records risk evaluation data, exporters must render them as `null` to mean
unavailable rather than low or no risk.

Decision register exports must include `schema_version`, `generated_at`, `project_head`,
and a decision list sorted by decision ID.

GitHub issue draft exports are local derived outputs only. They must not call GitHub APIs or
record runtime events.

GitHub issue draft `issues.json` must include:

- `schema_version`, `generated_at`, `project_head`
- `source_session_ids`
- `plan_status`
- `issues`

Issue body paths must be relative POSIX paths under `issues/`. Issue bodies must include the
source decision, session, or conflict IDs needed to trace each draft back to the decide-me event
runtime.

`issues.json` and `issues/` are generated together. Re-exporting to the same output directory
must replace the generated `issues/` directory so stale issue body drafts from prior session
inputs are removed.

Agent instruction exports are local derived outputs only. They must not call external agent
services or record runtime events.

Agent instruction export payloads must include:

- `schema_version`, `generated_at`, `project_head`
- `rules`

Each rule must include the rendered instruction text, its section, and the source decision ID.
Normal exports must exclude invalidated decisions and include only final agent-relevant decisions.
Decision metadata `agent_relevant` is a tri-state export override: `true` force-includes a final
decision, `false` force-excludes it, and missing or `null` preserves keyword-based detection.
Forced-included decisions use normal section keyword detection, falling back to `Development Rules`
when no section keyword matches.
AGENTS.md exports must use `<!-- decide-me:start -->` and `<!-- decide-me:end -->` markers when
creating or updating managed content. Existing unmarked AGENTS.md files may be overwritten only
when the user passes `--force`.

Architecture documentation, traceability matrix, and verification gap reports are local derived
outputs only. They must not record runtime events or call external services. These
software-oriented exports may use software labels such as ADRs, issues, requirements, and
verification, but they remain derived views over the object/link runtime.

Generic document exports are local derived outputs only. They must compile a schema-shaped
`DocumentModel` from runtime projections, closed sessions, registers, safety gates, stale
diagnostics, and object/link traceability before rendering Markdown, JSON, or supported CSV.
Document exports must not call `generate_plan()`, record `plan_generated`, create artifact
objects, or update runtime projections. Markdown document exports use
`<!-- decide-me:generated:start ... -->` and `<!-- decide-me:generated:end -->` markers by default
so re-export replaces only generated content and preserves human notes outside the marker block.

Derived export commands:

- `export-architecture-doc --format arc42`
- `export-traceability --format csv|markdown`
- `export-verification-gaps`
- `export-document --type decision-brief|action-plan|risk-register|review-memo|research-plan|comparison-table --format markdown|json|csv`

When `--session-id` is omitted, derived exports use all closed sessions sorted by session ID.
Repeated `--session-id` narrows the closed-session set. Unknown or non-closed sessions must fail.

Derived exports must fail before writing output when unresolved planner conflicts exist.

Traceability rows must include these matrix columns:

- `Requirement ID`
- `Decision ID`
- `Session ID`
- `Action`
- `Implementation Ready`
- `Evidence Source`
- `Risk`
- `Test / Verification`
- `Status`

`Requirement ID` is a decision-scoped persistent `R-###` value stored in runtime state.
It must not be derived from the current export row order, and filtered exports may
therefore contain non-contiguous IDs. Only
`evidence_source=tests` or test-file evidence references count as explicit verification.
`resolvable_by=tests` is only a basis for suggested verification. Missing verification and missing
evidence are reported in the verification gap export.
