---
name: decide-me
description: Interview the user about a plan or design in a structured, low-friction way until shared understanding is sufficient for the current milestone, preserve continuity across sequential and parallel sessions, maintain a taxonomy-aware decision runtime, and generate plan-ready close summaries for follow-through.
---

Help me reach shared understanding on this project with minimal user fatigue.

Use this skill as the only public entrypoint. Keep the startup surface lean and load the
bundled references only when they are needed for the current turn.

Startup checklist:

1. Load the derived projections and `.ai/decide-me/runtime-index.json` when they exist. Use full
   event-log replay only for `validate-state`, `validate-state --full`, conflict detection,
   `compact-runtime`, or `rebuild-projections`.
2. If the runtime is missing, bootstrap it or tell the user to run `python3 scripts/decide_me.py bootstrap ...`.
3. Validate event and projection consistency before trusting the current state.
   If validation reports an unresolved same-session merge conflict, run
   `python3 scripts/decide_me.py detect-merge-conflicts --ai-dir .ai/decide-me` and ask the user
   which candidate transaction to keep from the selected option's `surviving_tx_ids` before
   resolving it.
   If plan generation reports semantic conflicts across related sessions, inspect
   `show-session-graph` and use `detect-session-conflicts --include-related` before asking the
   user which session's scoped answer should win.
4. Create a session when the user starts a new decision thread; resume an existing one only when
   the user explicitly asks or the runtime already identifies the current session.
5. Before asking a question, scan the codebase, docs, tests, existing sessions, and prior close
   summaries for evidence that already resolves the decision.
6. Ask exactly one question at a time, and always include `Decision:`, `Proposal:`,
   `Recommendation:`, `Why:`, and `If not:`.
7. Treat plain `OK` as acceptance only when the same session still has a valid active proposal.
   If the proposal is stale or ambiguous, require `Accept P-...`.
8. When closing a session, generate a schema-shaped close summary and do not ask a new question in
   the same response.

Read only the reference file needed for the turn:

- [references/protocol-overview.md](references/protocol-overview.md)
- [references/interview-engine.md](references/interview-engine.md)
- [references/session-lifecycle.md](references/session-lifecycle.md)
- [references/search-and-taxonomy.md](references/search-and-taxonomy.md)
- [references/event-and-projection-model.md](references/event-and-projection-model.md)
- [references/plan-generation.md](references/plan-generation.md)
- [references/output-contract.md](references/output-contract.md)
- [references/examples.md](references/examples.md)

Bundled assets:

- deterministic CLI: `python3 scripts/decide_me.py ...`
- JSON contracts: `schemas/*.json`
- export templates: `templates/`

User-facing commands:

- `List sessions`
- `Show session S-...`
- `Resume session S-...`
- `Close session S-...`
- `Generate plan from sessions S-..., S-...`
- `Detect merge conflicts`
- `Resolve merge conflict by keeping tx T-... and rejecting tx T-...`
- `Link session S-child to parent S-parent`
- `Show session graph`
- `Detect session conflicts`
- `Resolve session conflict by choosing session S-...`
- `Resolve decision supersession by choosing decision D-... over D-...`
- `Classify session S-...`
- `Advance session S-...`
- `Handle reply for session S-...`
- `Export GitHub issue templates`
- `Export GitHub issue drafts from sessions S-..., S-...`
- `Export agent instructions for AGENTS.md, Cursor, Claude, or Codex`

Runtime invariants:

- `.ai/decide-me/events/**/*.jsonl` transaction files are the source of truth.
- Legacy `.ai/decide-me/event-log.jsonl` runtimes are not migrated automatically; rebootstrap
  or recreate them from exports produced by the previous runtime before using this version.
- `transaction_rejected` events record user-selected transaction rejection; rejected transaction
  files remain on disk for audit and are ignored only in the effective projection stream.
- `session_linked` events are the source of truth for explicit session graph edges; inferred
  candidates are advisory and must not silently become graph edges.
- `semantic_conflict_resolved` events record user-selected session-level conflict resolution and
  suppress the losing scoped content from normal projections, while keeping unrelated losing
  session content available.
- `decision_invalidated` events are emitted by the public decision-supersession resolution flow;
  `invalidate-decision` is a compatibility command, not the preferred UX.
- `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` are rebuildable projections
  and the normal hot-path read cache.
- `runtime-index.json` checkpoints projection freshness; refresh it with `compact-runtime` only
  after it verifies projections against the event log, or regenerate it with `rebuild-projections`.
- Human-readable plan, ADR, structured ADR, decision register, GitHub issue draft, and agent
  instruction files are exports, not runtime state.
- Free-form answers apply only to the current active proposal in the current session.
