# Review Queue

> **DRAFT / NOT ACCEPTED**
> This file is a readable draft export. It is not canonical runtime state and does not represent accepted decisions.

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 10 |
| Covered | 12 |
| Partial | 1 |
| Missing | 1 |
| Blocking coverage gaps | 2 |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | insufficient_evidence | core.evidence.coverage | coverage_gap | high | Partial evidence does not satisfy required evidence target: DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION. |
| GAP-002 | missing_required_layer | core.layer.strategy | coverage_gap | high | No strategy-layer draft decision exists. |
| GAP-003 | unsupported_recommendation | DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION | draft_decision | high | Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. |

## Review Order
| Rank | Target | Kind | Priority | Layer | Risk | Gap Type | Mode | Readiness | Reasons | Required Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | core.layer.strategy | coverage_gap | P1 | strategy |  | missing_required_layer | blocked | blocked | No strategy-layer draft decision exists. | Resolve blocking diagnostics before promotion. |
| 2 | DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION | draft_decision | P0 | verification | medium |  | individual | review_required | P0 decision, blocking gap diagnostic requires individual review, unsupported_recommendation: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. | Review individually before promotion. |
| 3 | core.evidence.coverage | coverage_gap | P0 |  |  | insufficient_evidence | individual | review_required | Partial evidence does not satisfy required evidence target: DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION. | Review individually before promotion. |
| 4 | DD-001 | draft_decision | P1 | purpose | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 5 | DD-002 | draft_decision | P1 | principle | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 6 | DD-003 | draft_decision | P1 | constraint | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 7 | DD-004 | draft_decision | P1 | design | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 8 | DD-005 | draft_decision | P1 | execution | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 9 | DD-007 | draft_decision | P1 | verification | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 10 | DD-006 | draft_decision | P1 | review | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 11 | GAP-003 | gap_diagnostic |  |  |  | unsupported_recommendation | individual | review_required | unsupported_recommendation on DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. | Review individually before promotion. |

## Blocked Items
| ID | Reasons | Required Action |
| --- | --- | --- |
| core.layer.strategy | No strategy-layer draft decision exists. | Resolve blocking diagnostics before promotion. |

## Individual Review Required
| ID | Priority | Risk | Reasons |
| --- | --- | --- | --- |
| DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION | P0 | medium | P0 decision, blocking gap diagnostic requires individual review, unsupported_recommendation: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. |
| core.evidence.coverage | P0 |  | Partial evidence does not satisfy required evidence target: DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION. |
| DD-001 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-002 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| GAP-003 |  |  | unsupported_recommendation on DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. |

## Bulk Materialize Candidates
| ID | Priority | Risk | Reason |
| --- | --- | --- | --- |
| none recorded |  |  |  |

## Must Not Bulk Promote
| ID | Reasons |
| --- | --- |
| core.layer.strategy | No strategy-layer draft decision exists. |
| DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION | P0 decision, blocking gap diagnostic requires individual review, unsupported_recommendation: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. |
| core.evidence.coverage | Partial evidence does not satisfy required evidence target: DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION. |
| DD-001 | P1 decision, P0/P1 priority requires individual review |
| DD-002 | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 decision, P0/P1 priority requires individual review |
| GAP-003 | unsupported_recommendation on DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION: Draft decision DD-GAP-SOFTWARE-SAFETY-BOUNDARY-VERIFICATION has a recommendation with partial or incomplete supporting evidence. |
