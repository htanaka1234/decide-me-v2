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
- the generated close summary

Plan-generation turns must include one of:

- `Conflicts:`
- `Action Plan:`

Exported files are derived outputs, not runtime state.

Structured ADR exports must include stable YAML frontmatter with:

- `id`, `title`, `status`, `domain`, `kind`, `priority`, `frontier`
- `session_id`, `accepted_via`, `supersedes`, `superseded_by`, `depends_on`
- `evidence_refs`
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
outputs only. They must not record runtime events or call external services.

Phase 4 export commands:

- `export-architecture-doc --format arc42`
- `export-traceability --format csv|markdown`
- `export-verification-gaps`

When `--session-id` is omitted, Phase 4 exports use all closed sessions sorted by session ID.
Repeated `--session-id` narrows the closed-session set. Unknown or non-closed sessions must fail.

Phase 4 exports must fail before writing output when unresolved planner conflicts exist.

Traceability rows must include these matrix columns:

- `Requirement ID`
- `Decision ID`
- `Session ID`
- `Action Slice`
- `Implementation Ready`
- `Evidence Source`
- `Risk`
- `Test / Verification`
- `Status`

`Requirement ID` is a stable derived `R-###` value from sorted export rows. Only
`evidence_source=tests` or test-file evidence refs count as explicit verification.
`resolvable_by=tests` is only a basis for suggested verification. Missing verification and missing
evidence are reported in the verification gap export.
