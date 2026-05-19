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
| GAP-001 | insufficient_evidence | core.evidence.coverage | coverage_gap | high | Missing, challenged, or unknown evidence coverage: DD-001. |
| GAP-002 | insufficient_evidence | DD-001 | draft_decision | high | Draft decision DD-001 evidence_coverage.status is unknown. |

## Review Order
| Rank | Target | Kind | Priority | Layer | Risk | Gap Type | Mode | Readiness | Reasons | Required Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | core.evidence.coverage | coverage_gap | P1 |  |  | insufficient_evidence | blocked | blocked | Missing, challenged, or unknown evidence coverage: DD-001. | Resolve blocking diagnostics before promotion. |
| 2 | DD-001 | draft_decision | P1 | purpose | low |  | individual | review_required | P1 decision, blocking gap diagnostic requires individual review, insufficient_evidence: Draft decision DD-001 evidence_coverage.status is unknown. | Review individually before promotion. |
| 3 | DD-002 | draft_decision | P1 | principle | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 4 | DD-003 | draft_decision | P1 | constraint | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 5 | DD-004 | draft_decision | P1 | strategy | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 6 | DD-005 | draft_decision | P1 | design | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 7 | DD-006 | draft_decision | P1 | execution | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 8 | DD-007 | draft_decision | P1 | verification | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 9 | DD-008 | draft_decision | P1 | review | low |  | individual | review_required | P1 decision, P0/P1 priority requires individual review | Review individually before promotion. |
| 10 | GAP-002 | gap_diagnostic |  |  |  | insufficient_evidence | individual | review_required | insufficient_evidence on DD-001: Draft decision DD-001 evidence_coverage.status is unknown. | Review individually before promotion. |

## Blocked Items
| ID | Reasons | Required Action |
| --- | --- | --- |
| core.evidence.coverage | Missing, challenged, or unknown evidence coverage: DD-001. | Resolve blocking diagnostics before promotion. |

## Individual Review Required
| ID | Priority | Risk | Reasons |
| --- | --- | --- | --- |
| DD-001 | P1 | low | P1 decision, blocking gap diagnostic requires individual review, insufficient_evidence: Draft decision DD-001 evidence_coverage.status is unknown. |
| DD-002 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| DD-008 | P1 | low | P1 decision, P0/P1 priority requires individual review |
| GAP-002 |  |  | insufficient_evidence on DD-001: Draft decision DD-001 evidence_coverage.status is unknown. |

## Bulk Materialize Candidates
| ID | Priority | Risk | Reason |
| --- | --- | --- | --- |
| none recorded |  |  |  |

## Must Not Bulk Promote
| ID | Reasons |
| --- | --- |
| core.evidence.coverage | Missing, challenged, or unknown evidence coverage: DD-001. |
| DD-001 | P1 decision, blocking gap diagnostic requires individual review, insufficient_evidence: Draft decision DD-001 evidence_coverage.status is unknown. |
| DD-002 | P1 decision, P0/P1 priority requires individual review |
| DD-003 | P1 decision, P0/P1 priority requires individual review |
| DD-004 | P1 decision, P0/P1 priority requires individual review |
| DD-005 | P1 decision, P0/P1 priority requires individual review |
| DD-006 | P1 decision, P0/P1 priority requires individual review |
| DD-007 | P1 decision, P0/P1 priority requires individual review |
| DD-008 | P1 decision, P0/P1 priority requires individual review |
| GAP-002 | insufficient_evidence on DD-001: Draft decision DD-001 evidence_coverage.status is unknown. |
