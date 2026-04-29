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
7. Record durable state as object/link events. Projections and exports are derived from
   `.ai/decide-me/events/**/*.jsonl`.
8. Close summaries expose `close_summary.object_ids` and `close_summary.link_ids`; plans expose
   `action_plan.actions` and `action_plan.implementation_ready_actions`.

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
- Plain `OK` can accept only when the target decision's safety gate is `passed`.
- Explicit `Accept P-...` can satisfy only `explicit_acceptance_required` inline. Higher approval
  thresholds require `approve-safety-gate` first.
- Blocked safety gates cannot be accepted by plain or explicit proposal acceptance.
- Evidence-based resolution uses the same safety gate. If recording evidence makes the decision
  `needs_approval`, the runtime records the evidence/link only and leaves the decision open until
  a matching approval is recorded and the evidence resolution is retried.
- If the proposal is stale or ambiguous, restate that and require explicit acceptance.
