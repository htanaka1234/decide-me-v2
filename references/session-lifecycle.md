# Session Lifecycle

Session statuses:

- `active`: current working thread
- `idle`: no recent activity but safe to resume
- `stale`: not current and needs explicit resume
- `closed`: interview finished and close summary frozen

Public operations:

- `list-sessions`
- `show-session`
- `resume-session`
- `close-session`
- `generate-plan`

Lifecycle rules:

- `list-sessions` and `show-session` may persist compatibility backfill events for closed
  sessions before returning the read model.
- A newly created session has no bound decisions. `advance-session` stays session-local and does
  not pull open decisions from other sessions.
- Resuming a session invalidates any previously active proposal.
- Invalidating a decision deactivates any active proposal that still points at that decision and
  removes the invalidated decision from normal session output.
- Closing a session generates a `close_summary` first, then emits `session_closed`.
- Closed sessions are read-only inputs for plan generation and search.
- Plan generation only accepts closed sessions.
