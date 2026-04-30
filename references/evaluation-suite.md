# Evaluation Suite

Phase 10 adds a development-side Evaluation Suite for the runtime capabilities built in Phases 5
through 9: the domain-neutral object/link core, Decision Stack Graph, Safety Gate, Document
Compiler, and Domain Packs. It is a regression detection harness, not a new user-facing interview
behavior.

The suite keeps expectations in scenario fixtures so tests do not hard-code every domain outcome.
The contracts are:

- `schemas/evaluation-scenario.schema.json`
- `schemas/evaluation-report.schema.json`

## Scenario layout

Scenario fixtures live outside the distributed Skill package, under `tests/scenarios/` in this
repository. A scenario directory contains:

- `scenario.yaml`: the evaluation scenario contract.
- `events.jsonl`: seed transaction events used to build the test runtime.
- `expected_outputs/`: normalized JSON, Markdown, or CSV snapshots.

The scenario contract records the pack and project context, one or more seeded sessions, a fixed
evaluation clock, and the expected decision, evidence, risk, conflict, and document outcomes.

```yaml
schema_version: 1
scenario_id: research_protocol
label: Research protocol planning
domain_pack: research

project:
  name: Demo research project
  objective: Define a reproducible retrospective cohort study.
  current_milestone: Protocol decisions

sessions:
  - session_id: S-research-protocol
    context: Plan a retrospective cohort study with endpoint and missing-data decisions.
    seed_events: events.jsonl
    close: true

evaluation:
  now: "2026-04-29T00:00:00Z"
  expected_decision_coverage:
    required_domain_decision_types:
      - research_question
      - cohort_definition
      - primary_endpoint
      - missing_data_strategy
    required_statuses:
      accepted: 2
      unresolved_min: 1
  expected_questions:
    max_questions: 4
    forbidden_repeated_decision_types:
      - primary_endpoint
  expected_evidence_coverage:
    min_supporting_evidence: 2
    required_evidence_requirement_ids:
      - protocol_or_project_brief
      - data_dictionary
  expected_risks:
    required_domain_risk_types:
      - unclear_endpoint
      - missing_data
    min_high_or_critical_risks: 1
  expected_conflicts:
    count: 0
  expected_documents:
    - type: research-plan
      format: json
      required_sections:
        - objective
        - research-question-decision-targets
        - evidence-base
        - analysis-verification-plan
        - risks-and-mitigations
        - source-traceability
```

`domain_pack` is an identifier rather than a fixed enum so future custom packs can be evaluated
with the same harness. `sessions[].seed_events` must be a safe relative `.jsonl` path. Absolute
paths, parent-directory traversal, and non-JSONL files are invalid.

## Evaluation report

The report is a schema-shaped JSON object with deterministic timestamps. Runners should set
`generated_at` from `evaluation.now` unless a test explicitly exercises clock behavior.

```json
{
  "schema_version": 1,
  "scenario_id": "research_protocol",
  "status": "passed",
  "generated_at": "2026-04-29T00:00:00Z",
  "metrics": {
    "question_efficiency": {
      "asked_count": 3,
      "max_allowed": 4,
      "passed": true
    },
    "decision_completeness": {
      "required_count": 4,
      "covered_count": 4,
      "passed": true
    },
    "evidence_coverage": {
      "required_count": 2,
      "covered_count": 2,
      "passed": true
    },
    "risk_coverage": {
      "required_count": 2,
      "covered_count": 2,
      "passed": true
    },
    "conflict_detection": {
      "expected_count": 0,
      "actual_count": 0,
      "passed": true
    },
    "plan_executability": {
      "readiness": "conditional",
      "implementation_ready_count": 1,
      "passed": true
    },
    "document_readability": {
      "required_sections_present": true,
      "empty_required_sections": [],
      "passed": true
    },
    "revisit_quality": {
      "due_revisit_count": 1,
      "passed": true
    }
  },
  "failures": []
}
```

Failures identify the metric, include a human-readable message, and may include a JSON path plus
the expected and actual values that caused the mismatch.

## Read-only behavior

Evaluation runs may build a temporary runtime from seed events, validate that runtime, rebuild
projections, compile documents, and compute diagnostics. They must not mutate the source scenario
fixtures or write events back into the repository runtime.

Use direct Python APIs for evaluation behavior where possible:

- runtime validation and projection rebuilds
- decision coverage from `project-state.json`
- evidence and risk registers
- Safety Gate diagnostics
- conflict detection
- document compilation and rendering

CLI checks should remain smoke tests for the CLI surface rather than the main Evaluation Suite
execution path.

## Snapshot expectations

Snapshots should compare normalized outputs only. Prefer fixed event timestamps and
`evaluation.now` for deterministic output. Remove only nonessential volatile fields such as
`generated_at`, `project_head`, `last_event_id`, and `tx_id` when they cannot be made stable by the
scenario clock.

Markdown snapshots should compare generated regions, preserving human-authored notes outside
managed markers. CSV snapshots should use deterministic row ordering.

## Distribution boundary

The evaluation contracts and this reference are bundled with the Skill because `schemas/` and
`references/` are part of the public distribution. Development fixtures and runners are not part of
the installable Skill package:

- include: `references/evaluation-suite.md`
- include: `schemas/evaluation-scenario.schema.json`
- include: `schemas/evaluation-report.schema.json`
- exclude: `tests/scenarios/**`
- exclude: `scripts/evaluate_scenarios.py`
