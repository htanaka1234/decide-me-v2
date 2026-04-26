# Protocol Overview

Use this skill to turn an ambiguous project request into a decision-complete action plan with
minimal user fatigue.

Core rules:

1. Optimize for milestone readiness, not exhaustive certainty.
2. Ask one question at a time.
3. Prefer evidence from the codebase, docs, tests, and prior sessions over asking the user.
4. Keep at most one active proposal per session.
5. Treat plain `OK` as acceptance only when the active proposal is still valid.
6. Stop when all relevant `P0` decisions with `frontier=now` are resolved, accepted, or explicitly
   deferred.

Question block contract:

```text
Decision: D-012
Proposal: P-0007
Question: Should the MVP use email magic links or passwords?
Recommendation: Use email magic links for the MVP.
Why: Lower coordination and implementation burden for the current milestone.
If not: Password reset, password policy, and recovery flows become in scope now.
```

Acceptance rules:

- `Accept P-0007` always wins over plain `OK`.
- Plain `OK` is valid only for the immediate next reply in the same session and only when the
  proposal's `based_on_project_head` still matches the current project head.
- If the proposal is stale or ambiguous, restate that and require explicit acceptance.
