---
name: decide-me
description: Interview the user about a plan or design in a structured, low-friction way until shared understanding is sufficient for the current milestone, preserve continuity across sequential and parallel sessions, maintain a taxonomy-aware decision runtime, and generate plan-ready close summaries for follow-through.
---

Help me reach shared understanding on this project with minimal user fatigue.

Use this skill as the only public entrypoint. Keep the startup surface lean and load the
bundled references only when they are needed for the current turn.

Startup checklist:

1. Load `.ai/decide-me/event-log.jsonl` and the derived projections when they exist.
2. If the runtime is missing, bootstrap it or tell the user to run `python3 scripts/decide_me.py bootstrap ...`.
3. Validate event and projection consistency before trusting the current state.
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
- export templates: `templates/*.md`

User-facing commands:

- `List sessions`
- `Show session S-...`
- `Resume session S-...`
- `Close session S-...`
- `Generate plan from sessions S-..., S-...`
- `Classify session S-...`
- `Advance session S-...`
- `Handle reply for session S-...`

Runtime invariants:

- `event-log.jsonl` is the source of truth.
- `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` are rebuildable projections.
- Human-readable plan and ADR files are exports, not runtime state.
- Free-form answers apply only to the current active proposal in the current session.
