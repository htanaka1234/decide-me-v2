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
