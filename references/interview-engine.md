# Interview Engine

The interview engine works in this order:

1. Discover or refresh visible decisions.
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

When evidence resolves a decision, record a `decision_resolved_by_evidence` event and avoid asking
the user again unless the evidence later becomes stale.

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
