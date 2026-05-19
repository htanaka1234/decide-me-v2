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
- Project head at generation: 5441e0b65c8e1725e79430c4a7463fddd72b9f8e805a3afe622eb772cb71198d
- Current project head: 5441e0b65c8e1725e79430c4a7463fddd72b9f8e805a3afe622eb772cb71198d
- Stale: no
- Project state ref: project-state.json
- Domain pack: generic

## Convergence
- Status: blocked
- Iterations: 0
- Stop reason: evidence_gap_blocked
- Explanation: Detected 2 draft gap(s), including 2 blocking gap(s).

## Summary
| Metric | Value |
| --- | --- |
| Draft decisions | 8 |
| Blocked | 1 |
| Individual review required | 9 |
| Bulk materialize candidates | 0 |
| High/Critical risk | 0 |
| Missing or challenged evidence | 1 |
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
| core.evidence.coverage | evidence_coverage | sufficient | unknown | P1 | True | missing | True | DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 | Missing, challenged, or unknown evidence coverage: DD-001. |
| core.human_review.safety | human_review_safety | individual_required | individual_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.promotion.accepted_forbidden | promotion_safety | accepted_forbidden | accepted_forbidden | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.promotion.proposal_required | promotion_safety | proposal_required | proposal_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007, DD-008 |  |
| core.promotion.stale_warning | promotion_safety | stale_warning | fresh | P2 | False | covered | False |  |  |

## Gap Diagnostics
| Metric | Value |
| --- | --- |
| Status | blocked |
| Stop reason | evidence_gap_blocked |
| Gap count | 2 |
| Blocking gaps | 2 |

| ID | Type | Severity | Target | Blocks | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | insufficient_evidence | high | core.evidence.coverage | True | Missing, challenged, or unknown evidence coverage: DD-001. |
| GAP-002 | insufficient_evidence | high | DD-001 | True | Draft decision DD-001 evidence_coverage.status is unknown. |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | insufficient_evidence | core.evidence.coverage | coverage_gap | high | Missing, challenged, or unknown evidence coverage: DD-001. |
| GAP-002 | insufficient_evidence | DD-001 | draft_decision | high | Draft decision DD-001 evidence_coverage.status is unknown. |

## Human Approval Plan
- Review blocked items first.
- Review P0/P1 individual items next.
- Only low-risk bulk candidates may be materialized in bulk.
- No item is accepted by this export.

## Top Review Items
| Rank | Target | Priority | Layer | Risk | Mode | Required Action |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | core.evidence.coverage | P1 |  |  | blocked | Resolve blocking diagnostics before promotion. |
| 2 | DD-001 | P1 | purpose | low | individual | Review individually before promotion. |
| 3 | DD-002 | P1 | principle | low | individual | Review individually before promotion. |
| 4 | DD-003 | P1 | constraint | low | individual | Review individually before promotion. |
| 5 | DD-004 | P1 | strategy | low | individual | Review individually before promotion. |
| 6 | DD-005 | P1 | design | low | individual | Review individually before promotion. |
| 7 | DD-006 | P1 | execution | low | individual | Review individually before promotion. |
| 8 | DD-007 | P1 | verification | low | individual | Review individually before promotion. |
| 9 | DD-008 | P1 | review | low | individual | Review individually before promotion. |
| 10 | GAP-002 |  |  |  | individual | Review individually before promotion. |

## Warnings
- none
