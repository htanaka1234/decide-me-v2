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
- Persist writes as `load events -> write transaction file -> rebuild -> validate -> atomic replace projections`.
- If validation fails, reject the write and keep the previous runtime files unchanged.
- `project_state.state.project_head` is a SHA-256 hash over canonical event IDs and replaces
  the old project-wide sequence number.

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
- `project_state.session_graph` contains deterministic `nodes`, explicit `edges`, advisory
  `inferred_candidates`, and `resolved_conflicts`.
- Inferred candidates are derived from shared decision ids, accepted-answer mismatches, workstream
  overlap, and action-slice responsibility mismatches. They are never treated as source-of-truth
  graph edges.
- `semantic_conflict_resolved` records the user's selected winning session for a scoped
  planner-level conflict across explicitly related sessions. It does not remove event files or
  suppress unrelated content from the losing session.

Decision invalidation:

- `decision_invalidated` records project-wide replacement of an older decision by a later one.
- Invalidated decisions remain in the event log and project projection for auditability.
- Normal outputs must hide invalidated decisions from session views, interview turns, close
  summaries, plans, and ADR exports.
