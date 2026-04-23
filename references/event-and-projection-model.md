# Event And Projection Model

`event-log.jsonl` is the runtime source of truth.

Event envelope:

```json
{
  "event_id": "E-20260423-000123",
  "ts": "2026-04-23T10:15:00Z",
  "session_id": "S-20260423-101500-a1",
  "event_type": "proposal_issued",
  "project_version_after": 12,
  "payload": {}
}
```

Projection rules:

- Rebuild `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` from the event log.
- Never mutate a projection directly without emitting an event.
- Persist writes as `load events -> append event(s) -> rebuild -> validate -> atomic replace`.
- If validation fails, reject the write and keep the previous runtime files unchanged.

Decision invalidation:

- `decision_invalidated` records project-wide replacement of an older decision by a later one.
- Invalidated decisions remain in the event log and project projection for auditability.
- Normal outputs must hide invalidated decisions from session views, interview turns, close
  summaries, plans, and ADR exports.
