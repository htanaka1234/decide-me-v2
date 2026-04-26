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
