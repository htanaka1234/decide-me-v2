# Event And Projection Model

`.ai/decide-me/events/**/*.jsonl` transaction files are the runtime source of truth.

Transaction file layout:

- `events/system/<tx_id>.jsonl`
- `events/sessions/<session_id>/<tx_id>.jsonl`

Event envelope:

```json
{
  "event_id": "E-20260423T101500123456Z-a1b2c3d4",
  "tx_id": "T-20260423T101500123456Z-9f8e7d6c",
  "tx_index": 1,
  "tx_size": 2,
  "ts": "2026-04-23T10:15:00.123456Z",
  "session_id": "S-20260423-101500-a1",
  "event_type": "proposal_issued",
  "payload": {}
}
```

Projection rules:

- Rebuild `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` from the transaction files.
- Never mutate a projection directly without emitting an event.
- Normal reads load the persisted projections plus `runtime-index.json`; they do not replay the
  event log.
- Persist normal writes as `load projections -> apply new transaction incrementally -> validate
  projection bundle -> write transaction file -> atomic replace projections and runtime index`.
- `rebuild-projections` performs full event-log replay and regenerates `runtime-index.json`.
- `validate-state` and `validate-state --full` perform full event-log validation;
  `validate-state --cached` / `--fast` validate only the projection checkpoint and index.
- If validation fails, reject the write and keep the previous runtime files unchanged.
- `decision_discovered` events carry a runtime-assigned `requirement_id`. Event logs without
  decision-scoped requirement IDs are invalid for this schema version.
- `project_state.state.project_head` is a SHA-256 chain hash over canonical event content and the
  previous project head, replacing the old project-wide sequence number. For
  `proposal_issued`, `based_on_project_head` is normalized before hashing so the proposal's
  own auto-filled head does not make the hash self-referential. Projections preserve the event
  payload value; AUTO proposal creation stores the post-event head in that payload.

Legacy runtime layout:

- `.ai/decide-me/event-log.jsonl` is rejected by this runtime. Automatic migration is not
  implemented; rebootstrap the runtime, or export with the previous runtime and recreate it
  under `.ai/decide-me/events/`.

Raw and effective streams:

- Raw reads validate JSON, envelopes, transaction shape, event IDs, file locations, and exactly one
  `project_initialized` before any transaction rejection is applied.
- `transaction_rejected` is a session-scoped control event with payload
  `kept_tx_id`, `rejected_tx_ids`, `reason`, `resolved_at`, `conflict_kind`, and
  `conflict_summary`.
- Rejected transaction files stay in `events/` for audit. Their domain events are excluded from the
  effective stream, while the `transaction_rejected` control event remains and contributes to
  `project_head` and `event_count`.
- Same-session semantic merge conflicts are resolved with
  `detect-merge-conflicts` followed by `resolve-merge-conflict --keep-tx-id ... --reject-tx-id ...`.

Session graph:

- `session_linked` records explicit parent/child graph edges. Supported relationships are
  `derived_from`, `refines`, `supersedes`, `depends_on`, and `contradicts`.
- `derived_from`, `refines`, `supersedes`, and `depends_on` edges must stay acyclic.
  `contradicts` is allowed to point back across the graph because it is not a lineage edge.
- `project_state.session_graph` contains deterministic `nodes`, explicit `edges`,
  `resolved_conflicts`, and an empty `inferred_candidates` list in persisted projections.
- Inferred candidates are derived from shared decision ids, accepted-answer mismatches, workstream
  overlap, and action-slice responsibility mismatches. They are generated on demand for graph
  inspection and conflict detection, may be cached by `project_head`, and are never treated as
  source-of-truth graph edges.
- `semantic_conflict_resolved` records the user's selected winning session for a scoped
  conflict across explicitly related sessions. It does not remove event files, but it suppresses
  the losing scoped content from normal projections so future search, evidence reuse, session
  views, and plans do not reuse the rejected context. Unrelated content from the losing session
  remains visible.

Decision supersession:

- `resolve-decision-supersession` is the preferred public command for project-wide replacement
  of an older decision by a later one.
- The underlying `decision_invalidated` event remains the source-of-truth event for this
  replacement. Invalidated decisions remain in the event log and project projection for
  auditability.
- Normal outputs must hide superseded decisions from session views, interview turns, close
  summaries, plans, and ADR exports.

Agent relevance metadata:

- Decisions may carry optional `agent_relevant: true | false | null` metadata.
- Missing or `null` means agent instruction exports use the conservative keyword-based filter.
- `true` force-includes a final decision in agent instruction exports; `false` force-excludes it.
- The flag does not change decision status rules: only accepted or resolved-by-evidence decisions
  are eligible for agent instruction export.
