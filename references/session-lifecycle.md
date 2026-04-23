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

- Resuming a session invalidates any previously active proposal.
- Closing a session generates a `close_summary` first, then emits `session_closed`.
- Closed sessions are read-only inputs for plan generation and search.
- Plan generation only accepts closed sessions.
