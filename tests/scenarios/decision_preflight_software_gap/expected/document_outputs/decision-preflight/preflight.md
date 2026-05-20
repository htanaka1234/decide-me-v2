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
- Project head at generation: 941da554a7b8e63badb032c6fede520a637b23ee8abe097e00f972af8ca6c32d
- Current project head: 941da554a7b8e63badb032c6fede520a637b23ee8abe097e00f972af8ca6c32d
- Stale: no
- Project state ref: project-state.json
- Domain pack: software

## Convergence
- Status: blocked
- Iterations: 0
- Stop reason: user_review_required
- Explanation: Detected 2 draft gap(s), including 2 blocking gap(s).

## Summary
| Metric | Value |
| --- | --- |
| Draft decisions | 7 |
| Blocked | 1 |
| Individual review required | 8 |
| Bulk materialize candidates | 0 |
| High/Critical risk | 0 |
| Missing or challenged evidence | 0 |
| Blocking coverage gaps | 2 |

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 9 |
| Covered | 12 |
| Partial | 1 |
| Missing | 1 |
| Blocking coverage gaps | 2 |

## Coverage Matrix
| Axis | Type | Source | Label | Target | Match Policy | Observed | Priority | Required | Status | Blocks | Covered By | Remaining Gaps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| domain_pack.software.safety_boundary.verification | decision_stack_layer | domain_pack | Safety boundary | verification | explicit_target_or_domain_axis | unbound_domain_axis | P0 | True | partial | True | DD-007 | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |
| core.layer.constraint | decision_stack_layer | core | Constraint | constraint | layer_complete | complete | P1 | True | covered | False | DD-003 |  |
| core.layer.design | decision_stack_layer | core | Design | design | layer_complete | complete | P1 | True | covered | False | DD-004 |  |
| core.layer.execution | decision_stack_layer | core | Execution | execution | layer_complete | complete | P1 | True | covered | False | DD-005 |  |
| core.layer.principle | decision_stack_layer | core | Principle | principle | layer_complete | complete | P1 | True | covered | False | DD-002 |  |
| core.layer.purpose | decision_stack_layer | core | Purpose | purpose | layer_complete | complete | P1 | True | covered | False | DD-001 |  |
| core.layer.review | decision_stack_layer | core | Review | review | layer_complete | complete | P1 | True | covered | False | DD-006 |  |
| core.layer.strategy | decision_stack_layer | core | Strategy | strategy | layer_complete | missing | P1 | True | missing | True |  | No strategy-layer draft decision exists. |
| core.layer.verification | decision_stack_layer | core | Verification | verification | layer_complete | complete | P1 | True | covered | False | DD-007 |  |
| core.evidence.coverage | evidence_coverage | core | Evidence coverage | sufficient | layer_complete | sufficient | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007 |  |
| core.human_review.safety | human_review_safety | core | Human review safety | individual_required | layer_complete | individual_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007 |  |
| core.promotion.accepted_forbidden | promotion_safety | core | Accepted decisions forbidden | accepted_forbidden | layer_complete | accepted_forbidden | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007 |  |
| core.promotion.proposal_required | promotion_safety | core | Promotion proposal required | proposal_required | layer_complete | proposal_required | P2 | False | covered | False | DD-001, DD-002, DD-003, DD-004, DD-005, DD-006, DD-007 |  |
| core.promotion.stale_warning | promotion_safety | core | Stale draft warning | stale_warning | layer_complete | fresh | P2 | False | covered | False |  |  |

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
| GAP-002 | missing_required_layer | high | domain_pack.software.safety_boundary.verification | True | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |

## Frontier Queue
| ID | Source Gap | Priority | Status | Topic | Evidence Needed | Suggested Expansion |
| --- | --- | --- | --- | --- | --- | --- |
| F-GAP-002 | GAP-002 | P0 | open | verification layer is partial |  | Add one complete verification-layer draft decision before review. |
| F-GAP-001 | GAP-001 | P1 | open | strategy layer is missing |  | Add one complete strategy-layer draft decision before review. |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | missing_required_layer | core.layer.strategy | coverage_gap | high | No strategy-layer draft decision exists. |
| GAP-002 | missing_required_layer | domain_pack.software.safety_boundary.verification | coverage_gap | high | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |

## Human Approval Plan
- Review blocked items first.
- Review P0/P1 individual items next.
- Only low-risk bulk candidates may be materialized in bulk.
- No item is accepted by this export.

## Top Review Items
| Rank | Target | Priority | Layer | Risk | Mode | Required Action |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | core.layer.strategy | P1 | strategy |  | blocked | Resolve blocking diagnostics before promotion. |
| 2 | domain_pack.software.safety_boundary.verification | P0 | verification |  | individual | Review individually before promotion. |
| 3 | DD-001 | P1 | purpose | low | individual | Review individually before promotion. |
| 4 | DD-002 | P1 | principle | low | individual | Review individually before promotion. |
| 5 | DD-003 | P1 | constraint | low | individual | Review individually before promotion. |
| 6 | DD-004 | P1 | design | low | individual | Review individually before promotion. |
| 7 | DD-005 | P1 | execution | low | individual | Review individually before promotion. |
| 8 | DD-007 | P1 | verification | low | individual | Review individually before promotion. |
| 9 | DD-006 | P1 | review | low | individual | Review individually before promotion. |

## Warnings
- none
