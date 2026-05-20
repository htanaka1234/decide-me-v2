# Review Queue

> **DRAFT / NOT ACCEPTED**
> This file is a readable draft export. It is not canonical runtime state and does not represent accepted decisions.

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 9 |
| Covered | 12 |
| Partial | 1 |
| Missing | 1 |
| Blocking coverage gaps | 2 |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | missing_required_layer | core.layer.strategy | coverage_gap | high | No strategy-layer draft decision exists. |
| GAP-002 | missing_required_layer | domain_pack.software.safety_boundary.verification | coverage_gap | high | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |

## Review Order
| Rank | Target | Kind | Priority | Layer | Risk | Gap Type | Mode | Readiness | Reasons | Required Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | core.layer.strategy | coverage_gap | P1 | strategy |  | missing_required_layer | blocked | blocked | No strategy-layer draft decision exists. | Resolve blocking diagnostics before promotion. |
| 2 | domain_pack.software.safety_boundary.verification | coverage_gap | P0 | verification |  | missing_required_layer | individual | review_required | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. | Review individually before promotion. |
| 3 | DD-001 | draft_decision | P1 | purpose | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 4 | DD-002 | draft_decision | P1 | principle | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 5 | DD-003 | draft_decision | P1 | constraint | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 6 | DD-004 | draft_decision | P1 | design | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 7 | DD-005 | draft_decision | P1 | execution | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 8 | DD-007 | draft_decision | P1 | verification | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 9 | DD-006 | draft_decision | P1 | review | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |

## Blocked Items
| ID | Reasons | Required Action |
| --- | --- | --- |
| core.layer.strategy | No strategy-layer draft decision exists. | Resolve blocking diagnostics before promotion. |

## Individual Review Required
| ID | Priority | Risk | Reasons |
| --- | --- | --- | --- |
| domain_pack.software.safety_boundary.verification | P0 |  | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |
| DD-001 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-002 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 | low | P1 decision, P0/P1 priority requires individual review |

## Bulk Materialize Candidates
| ID | Priority | Risk | Reason |
| --- | --- | --- | --- |
| none recorded |  |  |  |

## Must Not Bulk Promote
| ID | Reasons |
| --- | --- |
| core.layer.strategy | No strategy-layer draft decision exists. |
| domain_pack.software.safety_boundary.verification | No complete verification-layer draft decision explicitly binds domain_pack.software.safety_boundary.verification. |
| DD-001 | P1 decision, P0/P1 priority requires individual review |
| DD-002 | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 decision, P0/P1 priority requires individual review |
