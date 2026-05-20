# Review Queue

> **DRAFT / NOT ACCEPTED**
> This file is a readable draft export. It is not canonical runtime state and does not represent accepted decisions.

## Coverage Summary
| Metric | Value |
| --- | --- |
| Required targets | 9 |
| Covered | 12 |
| Partial | 0 |
| Missing | 1 |
| Blocking coverage gaps | 1 |

## Blocking Gaps
| ID | Type | Target | Kind | Severity | Reason |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | unsafe_bulk_review | DD-001 | draft_decision | critical | Draft decision DD-001 is high risk but requests bulk review. |
| GAP-002 | unsafe_bulk_review | core.human_review.safety | coverage_gap | high | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. |

## Review Order
| Rank | Target | Kind | Priority | Layer | Risk | Gap Type | Mode | Readiness | Reasons | Required Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | core.human_review.safety | coverage_gap | P0 |  |  | unsafe_bulk_review | blocked | blocked | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. | Resolve blocking diagnostics before promotion. |
| 2 | DD-002 | draft_decision | P1 | principle | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 3 | DD-003 | draft_decision | P1 | constraint | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 4 | DD-004 | draft_decision | P1 | strategy | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 5 | DD-005 | draft_decision | P1 | design | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 6 | DD-006 | draft_decision | P1 | execution | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 7 | DD-007 | draft_decision | P1 | verification | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 8 | DD-008 | draft_decision | P1 | review | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 9 | DD-001 | draft_decision | P2 | purpose | high |  | individual | review_required | blocking gap diagnostic requires individual review, unsafe_bulk_review: Draft decision DD-001 is high risk but requests bulk review. | Review individually before promotion. |
| 10 | GAP-001 | gap_diagnostic |  |  |  | unsafe_bulk_review | individual | review_required | unsafe_bulk_review on DD-001: Draft decision DD-001 is high risk but requests bulk review. | Review individually before promotion. |

## Blocked Items
| ID | Reasons | Required Action |
| --- | --- | --- |
| core.human_review.safety | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. | Resolve blocking diagnostics before promotion. |

## Individual Review Required
| ID | Priority | Risk | Reasons |
| --- | --- | --- | --- |
| DD-002 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-008 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-001 | P2 | high | blocking gap diagnostic requires individual review, unsafe_bulk_review: Draft decision DD-001 is high risk but requests bulk review. |
| GAP-001 |  |  | unsafe_bulk_review on DD-001: Draft decision DD-001 is high risk but requests bulk review. |

## Bulk Materialize Candidates
| ID | Priority | Risk | Reason |
| --- | --- | --- | --- |
| none recorded |  |  |  |

## Must Not Bulk Promote
| ID | Reasons |
| --- | --- |
| core.human_review.safety | Unsafe bulk review requested for high/critical risk draft decisions: DD-001. |
| DD-002 | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 decision, P0/P1 priority requires individual review |
| DD-008 | P1 decision, P0/P1 priority requires individual review |
| DD-001 | blocking gap diagnostic requires individual review, unsafe_bulk_review: Draft decision DD-001 is high risk but requests bulk review. |
| GAP-001 | unsafe_bulk_review on DD-001: Draft decision DD-001 is high risk but requests bulk review. |
