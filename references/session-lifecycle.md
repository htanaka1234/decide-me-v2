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

- `list-sessions` and `show-session` are read-only operations over persisted projections.
- A newly created session has no bound decisions. `advance-session` stays session-local and does
  not pull open decisions from other sessions.
- Resuming a session invalidates any previously active proposal.
- Resolving a decision supersession deactivates any active proposal that still points at the
  superseded decision and removes that decision from normal session output.
- Closing a session generates a `close_summary` first, then emits `session_closed`.
- Closed sessions are read-only inputs for plan generation and search.
- Plan generation only accepts closed sessions.
