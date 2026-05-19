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
- Project head at generation: fa27c681766e44a132f300dd6fc345f8385aa456f04b5a37d00c236a98899078
- Current project head: fa27c681766e44a132f300dd6fc345f8385aa456f04b5a37d00c236a98899078
- Stale: no
- Project state ref: project-state.json
- Domain pack: generic

## Convergence
- Status: blocked
- Iterations: 0
- Stop reason: user_review_required
- Explanation: Detected 2 draft gap(s), including 2 blocking gap(s).

## Summary
| Metric | Value |
| --- | --- |
| Draft decisions | 6 |
| Blocked | 2 |
| Individual review required | 6 |
| Bulk materialize candidates | 0 |
| High/Critical risk | 0 |
| Missing or challenged evidence | 0 |
| Blocking coverage gaps | 2 |

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 8 |
| Covered | 11 |
| Partial | 0 |
| Missing | 2 |
| Blocking coverage gaps | 2 |

## Coverage Matrix
| Axis | Type | Target | Observed | Priority | Required | Status | Blocks | Covered By | Remaining Gaps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core.layer.constraint | decision_stack_layer | constraint | complete | P1 | True | covered | False | DD-003 |  |
| core.layer.design | decision_stack_layer | design | complete | P1 | True | covered | False | DD-004 |  |
| core.layer.execution | decision_stack_layer | execution | complete | P1 | True | covered | False | DD-005 |  |
| core.layer.principle | decision_stack_layer | principle | complete | P1 | True | covered | False | DD-002 |  |
| core.layer.purpose | decision_stack_layer | purpose | complete | P1 | True | covered | False | DD-001 |  |
| core.layer.review | decision_stack_layer | review | complete | P1 | True | covered | False | DD-006 |  |
| core.layer.strategy | decision_stack_layer | strategy | missing | P1 | True | missing | True |  | No strategy-layer draft decision exists. |
| core.layer.verification | decision_stack_layer | verification | missing | P1 | True | missing | True |  | No verification-layer draft decision exists. |
| core.evidence.coverage | evidence_coverage | sufficient | sufficient | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006 |  |
| core.human_review.safety | human_review_safety | individual_required | individual_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006 |  |
| core.promotion.accepted_forbidden | promotion_safety | accepted_forbidden | accepted_forbidden | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006 |  |
| core.promotion.proposal_required | promotion_safety | proposal_required | proposal_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006 |  |
| core.promotion.stale_warning | promotion_safety | stale_warning | fresh | P2 | False | covered | False |  |  |

## Gap Diagnostics
| Metric | Value |
| --- | --- |
| Status | blocked |
| Stop reason | user_review_required |
| Gap count | 2 |
| Blocking gaps | 2 |

| ID | Type | Severity | Target | Blocks | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | missing_required_layer | high | core.layer.strategy | True | No strategy-layer draft decision exists. |
| GAP-002 | missing_required_layer | high | core.layer.verification | True | No verification-layer draft decision exists. |

## Frontier Queue
| ID | Source Gap | Priority | Status | Topic | Evidence Needed | Suggested Expansion |
| --- | --- | --- | --- | --- | --- | --- |
| F-GAP-001 | GAP-001 | P1 | open | strategy layer is missing |  | Add one complete strategy-layer draft decision before review. |
| F-GAP-002 | GAP-002 | P1 | open | verification layer is missing |  | Add one complete verification-layer draft decision before review. |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | missing_required_layer | core.layer.strategy | coverage_gap | high | No strategy-layer draft decision exists. |
| GAP-002 | missing_required_layer | core.layer.verification | coverage_gap | high | No verification-layer draft decision exists. |

## Human Approval Plan
- Review blocked items first.
- Review P0/P1 individual items next.
- Only low-risk bulk candidates may be materialized in bulk.
- No item is accepted by this export.

## Top Review Items
| Rank | Target | Priority | Layer | Risk | Mode | Required Action |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | core.layer.strategy | P1 | strategy |  | blocked | Resolve blocking diagnostics before promotion. |
| 2 | core.layer.verification | P1 | verification |  | blocked | Resolve blocking diagnostics before promotion. |
| 3 | DD-001 | P1 | purpose | low | individual | Review individually before promotion. |
| 4 | DD-002 | P1 | principle | low | individual | Review individually before promotion. |
| 5 | DD-003 | P1 | constraint | low | individual | Review individually before promotion. |
| 6 | DD-004 | P1 | design | low | individual | Review individually before promotion. |
| 7 | DD-005 | P1 | execution | low | individual | Review individually before promotion. |
| 8 | DD-006 | P1 | review | low | individual | Review individually before promotion. |

## Warnings
- none
