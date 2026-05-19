# Decision Preflight Brief

> **DRAFT / NOT ACCEPTED**
> This file is a readable draft export. It is not canonical runtime state and does not represent accepted decisions.

## Goal
- Goal ID: G-20260513-001
- Title: Add draft decision sets
- Desired outcome: Store draft sets safely.
- Constraints: Do not mutate canonical runtime

## Source Context
- Draft set: DS-20260429-001
- Generated at: 2026-04-29T00:00:00Z
- Project head at generation: 056efe3202fc020a882fd0f68d5d3b7d4074802fd19654142c7894454d24f433
- Current project head: 056efe3202fc020a882fd0f68d5d3b7d4074802fd19654142c7894454d24f433
- Stale: no
- Project state ref: project-state.json
- Domain pack: generic

## Convergence
- Status: blocked
- Iterations: 0
- Stop reason: risk_gate_triggered
- Explanation: Detected 2 draft gap(s), including 2 blocking gap(s).

## Summary
| Metric | Value |
| --- | --- |
| Draft decisions | 8 |
| Blocked | 1 |
| Individual review required | 9 |
| Bulk materialize candidates | 0 |
| High/Critical risk | 1 |
| Missing or challenged evidence | 0 |
| Blocking coverage gaps | 1 |

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 9 |
| Covered | 12 |
| Partial | 0 |
| Missing | 1 |
| Blocking coverage gaps | 1 |

## Coverage Matrix
| Axis | Type | Target | Observed | Priority | Required | Status | Blocks | Covered By | Remaining Gaps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core.layer.constraint | decision_stack_layer | constraint | complete | P1 | True | covered | False | DD-003 |  |
| core.layer.design | decision_stack_layer | design | complete | P1 | True | covered | False | DD-005 |  |
| core.layer.execution | decision_stack_layer | execution | complete | P1 | True | covered | False | DD-006 |  |
| core.layer.principle | decision_stack_layer | principle | complete | P1 | True | covered | False | DD-002 |  |
| core.layer.purpose | decision_stack_layer | purpose | complete | P1 | True | covered | False | DD-001 |  |
| core.layer.review | decision_stack_layer | review | complete | P1 | True | covered | False | DD-008 |  |
| core.layer.strategy | decision_stack_layer | strategy | complete | P1 | True | covered | False | DD-004 |  |
| core.layer.verification | decision_stack_layer | verification | complete | P1 | True | covered | False | DD-007 |  |
| core.evidence.coverage | evidence_coverage | sufficient | sufficient | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.human_review.safety | human_review_safety | individual_required | blocked | P0 | True | missing | True | DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. |
| core.promotion.accepted_forbidden | promotion_safety | accepted_forbidden | accepted_forbidden | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.promotion.proposal_required | promotion_safety | proposal_required | proposal_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.promotion.stale_warning | promotion_safety | stale_warning | fresh | P2 | False | covered | False |  |  |

## Gap Diagnostics
| Metric | Value |
| --- | --- |
| Status | blocked |
| Stop reason | risk_gate_triggered |
| Gap count | 2 |
| Blocking gaps | 2 |

| ID | Type | Severity | Target | Blocks | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | unsafe_bulk_review | critical | DD-001 | True | Draft decision DD-001 is high risk but requests bulk review. |
| GAP-002 | unsafe_bulk_review | high | core.human_review.safety | True | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. |

## Frontier Queue
| ID | Source Gap | Priority | Status | Topic | Evidence Needed | Suggested Expansion |
| --- | --- | --- | --- | --- | --- | --- |
| F-GAP-002 | GAP-002 | P0 | open | human review safety is missing |  | Route unsafe or unclear review targets to individual human review. |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | unsafe_bulk_review | DD-001 | draft_decision | critical | Draft decision DD-001 is high risk but requests bulk review. |
| GAP-002 | unsafe_bulk_review | core.human_review.safety | coverage_gap | high | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. |

## Human Approval Plan
- Review blocked items first.
- Review P0/P1 individual items next.
- Only low-risk bulk candidates may be materialized in bulk.
- No item is accepted by this export.

## Top Review Items
| Rank | Target | Priority | Layer | Risk | Mode | Required Action |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | core.human_review.safety | P0 |  |  | blocked | Resolve blocking diagnostics before promotion. |
| 2 | DD-002 | P1 | principle | low | individual | Review individually before promotion. |
| 3 | DD-003 | P1 | constraint | low | individual | Review individually before promotion. |
| 4 | DD-004 | P1 | strategy | low | individual | Review individually before promotion. |
| 5 | DD-005 | P1 | design | low | individual | Review individually before promotion. |
| 6 | DD-006 | P1 | execution | low | individual | Review individually before promotion. |
| 7 | DD-007 | P1 | verification | low | individual | Review individually before promotion. |
| 8 | DD-008 | P1 | review | low | individual | Review individually before promotion. |
| 9 | DD-001 | P2 | purpose | high | individual | Review individually before promotion. |
| 10 | GAP-001 |  |  |  | individual | Review individually before promotion. |

## Warnings
- none
