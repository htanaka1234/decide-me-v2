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
  "event_type": "object_recorded",
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
- The accepted event whitelist is `project_initialized`, `session_created`,
  `session_resumed`, `session_closed`, `close_summary_generated`, `plan_generated`,
  `taxonomy_extended`, `transaction_rejected`, `object_recorded`, `object_updated`,
  `object_status_changed`, `object_linked`, `object_unlinked`,
  `session_question_asked`, and `session_answer_recorded`.
- Domain state is recorded as objects and links. `object_recorded.payload.object` matches
  `schemas/object.schema.json`; `object_linked.payload.link` matches
  `schemas/link.schema.json`.
- `object_unlinked` removes the link from the active projection. Link history remains in the
  event log.
- `project_state.state.project_head` is a SHA-256 chain hash over canonical event content and the
  previous project head, replacing the old project-wide sequence number.

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

- `project_state.graph` contains deterministic `nodes`, `edges`, `resolved_conflicts`, and an
  empty `inferred_candidates` list in persisted projections.
- Phase 5-3 does not persist explicit session graph or semantic conflict resolution events.
  Inferred candidates remain advisory output generated from projections when requested.

Object supersession:

- Replacement is represented with normal object/link events: update the superseded object status,
  update its metadata, and record a `supersedes` link from the replacement object to the
  superseded object.

Agent relevance metadata:

- Decisions may carry optional `agent_relevant: true | false | null` metadata.
- Missing or `null` means agent instruction exports use the conservative keyword-based filter.
- `true` force-includes a final decision in agent instruction exports; `false` force-excludes it.
- The flag does not change decision status rules: only accepted or resolved-by-evidence decisions
  are eligible for agent instruction export.
