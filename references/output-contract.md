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
Those action entries are the WorkUnit equivalent. When recorded, action metadata may carry
`action_type`, `required_inputs`, `outputs`, `verification_refs`, and `source_decision_refs`; plan
and action-plan document exports surface those fields as execution context, not canonical state
outside the action object.

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
Decision brief exports must surface Phase 12 source-store evidence fields when present, including
source-unit ID, citation, per-link quote, interpretation note, target object, relevance, and
effective dates.

Source-store commands:

- `import-source`
- `decompose-source`
- `search-evidence`
- `link-evidence`
- `list-sources`
- `show-source`
- `show-source-unit`
- `show-source-impact`
- `rebuild-evidence-index`
- `validate-sources`

Source-store search and impact commands are diagnostics over `.ai/decide-me/sources/`,
`index/source_units.sqlite`, and projected evidence links. `show-source-impact` reports direct
affected objects and downstream affected decisions; with `--include-previous-version-links`, it can
include links that still point at prior source snapshots recorded by `source_version_updated`.
It also reports `orphaned_linked_source_units` when projected source-store evidence references a
source unit no longer present in the current `units.jsonl`. `validate-sources` treats those orphaned
source-unit references as validation issues.
`search-evidence` merges SQLite FTS results with a deterministic whitespace-token AND `LIKE`
fallback so Japanese multi-term queries can find units even when FTS tokenization is ineffective.
By default it searches only current canonical source snapshots. Replaced snapshots require
`--include-superseded` or an explicit `--source-id`.
`search-evidence`,
`show-source-impact`, `list-sources`, `show-source`, and `show-source-unit` must not update
runtime projections or event logs. `rebuild-evidence-index` updates only the derived SQLite index.

Draft sidecar commands:

- `/goal` Skill command, not a CLI subcommand
- `autopilot-draft --seed-draft-json <path>|--goal <text>`
- `create-draft-set --draft-json <path>`
- `show-draft-set --draft-set-id DS-...`
- `list-draft-sets`
- `project-draft-set --draft-set-id DS-...`
- `review-draft-set --draft-set-id DS-...`
- `export-draft-set --draft-set-id DS-... --format markdown`

Draft promotion commands:

- `promote-draft-decision --draft-set-id DS-... --draft-decision-id DD-... --session-id S-...`
- `promote-draft-set --draft-set-id DS-... --session-map-json <path> --only-bulk-promotable`

Other derived export commands:

- `export-architecture-doc --format arc42`
- `export-traceability --format csv|markdown`
- `export-verification-gaps`
- `export-document --type decision-brief|action-plan|risk-register|review-memo|research-plan|comparison-table --format markdown|json|csv`

For derived exports that accept `--session-id`, omitting it uses all closed sessions sorted by
session ID. Repeated `--session-id` narrows the closed-session set. Unknown or non-closed sessions
must fail.

Derived exports must fail before writing output when unresolved planner conflicts exist.

PR-5 `/goal` is a Skill command, not a Python CLI subcommand. It may use the deterministic
`autopilot-draft` CLI after generating a seed DraftDecisionSet. It must report:

- `draft_set_id`
- counts for draft decisions, assumptions, risks, actions, and verifications
- draft projection path and gap summary
- convergence `status`, `stop_reason`, and `iterations`
- review summary counts for blocked, individual-review, and bulk candidate items
- export paths for `preflight.md`, `draft-decisions.md`, `review-queue.md`, and
  `assumptions-risks.md`
- an explicit `DRAFT / NOT ACCEPTED` notice

`create-draft-set` returns `status`, `draft_set_id`, `path`, `project_head_at_generation`,
`is_stale`, and `counts`. `show-draft-set` returns `status`, `draft_set`, and `runtime_status`.
`list-draft-sets` returns `status`, `count`, and `draft_sets[]`.

`project-draft-set` returns `status`, `draft_set_id`, `projection_path`, `stale`, `gap_count`,
`blocking_gap_count`, and `stop_reason`. With persistence enabled, it writes only
`.ai/decide-me/draft-sets/DS-.../draft-projection.json`.

`autopilot-draft` returns `status`, `draft_set_id`, `draft_set_path`, `projection_path`, `exports`,
`convergence`, and `canonical_events_created=false`. Its `convergence` object includes `status`,
`stop_reason`, `iterations`, `gap_count`, and `blocking_gap_count`. It may write `draft-set.json`,
`draft-projection.json`, `review-queue.json`, and Markdown exports. It must not create accepted
decisions or canonical events.

`draft-projection.json` must match `schemas/draft-projection.schema.json`. Its required top-level
fields are `schema_version`, `draft_set_id`, `generated_at`, `project_head_at_generation`,
`current_project_head`, `stale`, `canonical_summary`, `draft_summary`, `nodes`, `links`,
`gap_diagnostics`, and `convergence`. Gap diagnostics include `type`, `severity`, `target_id`,
`blocks_convergence`, `blocks_bulk_promotion`, `reason`, and `suggested_resolution`.

Draft set review and export are sidecar-derived outputs. They consume
`.ai/decide-me/draft-sets/DS-.../draft-set.json` and may write only
`.ai/decide-me/draft-sets/DS-.../review-queue.json` plus these Markdown files under that draft
set's `exports/` directory:

- `preflight.md`
- `draft-decisions.md`
- `review-queue.md`
- `assumptions-risks.md`

Every Markdown draft export must include `DRAFT / NOT ACCEPTED`, and managed generated regions
must preserve the trailing `## Human Notes` section on regeneration. The review queue is a
deterministic promotion-input queue, not promotion itself: high or critical risk items, challenged
or missing evidence, conflicts, explicit individual-review flags, and blocked draft fields must not
enter the bulk candidate list. `promotion.promoted_decision_ids` remains sidecar metadata only and
must not let a draft bypass blocked or individual-review classification. `review-draft-set` and
`export-draft-set` must not emit events, create accepted decisions, create canonical proposals, or
update `project-state.json`, `taxonomy-state.json`, or `sessions/*.json`. A stale project head is
reported as a warning and does not block draft export.

Draft promotion is separate from draft review/export. `promote-draft-decision` may write canonical
events, but it must use only existing event types: `object_recorded`, `object_status_changed`,
`object_linked`, and `session_question_asked`. Promotion materializes a normal proposed decision,
active proposal, option, required risk scaffold for `medium`/`high`/`critical` draft risk, and
question state; it never creates an accepted decision. Canonical provenance lives in
`decision.metadata.draft_origin`, while
`.ai/decide-me/draft-sets/DS-.../promotion-log.jsonl` is an audit sidecar. Stale draft sets fail
single promotion unless `--allow-stale` is explicit, in which case `draft_origin.stale_promoted`
is true; bulk promotion always rejects stale draft sets. Proposal acceptance must still pass the
normal explicit/plain-OK guard and safety gate flow.

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
