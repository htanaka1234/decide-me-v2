# Interview Engine

The interview engine works in this order:

1. Discover or refresh visible decision objects and related objects.
2. Try to resolve them with evidence.
3. Select the highest-value unresolved decision.
4. Issue a single proposal.
5. Accept, reject, defer, or resolve the proposal.

Decision ranking:

- Priority order: `P0`, `P1`, `P2`
- Frontier order: `now`, `later`, `discovered-later`, `deferred`
- Open statuses before closed ones
- Fewer unresolved dependencies first

Evidence-first resolution order:

1. codebase
2. docs
3. tests
4. existing sessions and close summaries
5. user

When evidence resolves a decision, record neutral object status/update/link events and avoid asking
the user again unless the evidence later becomes stale.

Runtime writes:

- Questions, proposals, answers, evidence, risks, actions, and follow-up constraints are projected
  from `object_recorded`, `object_updated`, `object_status_changed`, `object_linked`,
  `object_unlinked`, `session_question_asked`, and `session_answer_recorded`.
- Proposals and decisions are objects. Acceptance is represented by a decision object linked to a
  proposal object with `accepts`.
- Evidence is an object linked with `supports`, `challenges`, or `verifies`; it is not embedded in
  close-summary or plan payloads.

Deterministic runtime helpers:

- `advance-session`:
  - reuses a still-valid active proposal when one exists
  - otherwise tries evidence-first auto-resolution
  - otherwise issues the next question block
- `handle-reply`:
  - accepts `OK`
  - accepts `Accept P-...`
  - accepts `Reject P-...: reason`
  - accepts `Defer D-...: reason`
  - treats short affirmations such as `Sounds good` as explicit acceptance of the active proposal
  - treats other free-form answers as explicit decision answers tied to the active proposal
  - extracts follow-up constraints from clauses such as `only if ...` or `must stay ...`
  - discovers follow-up decisions from clauses such as `we also need ...`
  - infers discovered decision `domain`, `kind`, `priority`, `resolvable_by`,
    `reversibility`, and a source-aware question from each follow-up clause
  - immediately scans newly discovered `codebase` / `docs` / `tests` decisions for evidence before
    selecting the next question
