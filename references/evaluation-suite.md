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
    required_status_counts:
      - status: accepted
        mode: exact
        count: 2
      - status: unresolved
        mode: min
        count: 1
      - status: resolved-by-evidence
        mode: min
        count: 1
  expected_questions:
    max_questions: 4
    forbidden_repeated_decision_types:
      - primary_endpoint
    probe_session_ids:
      - S-research-protocol
    advance_steps: 1
  expected_evidence_coverage:
    min_supporting_evidence: 2
    required_evidence_requirement_ids:
      - protocol_or_project_brief
      - data_dictionary
  expected_risks:
    required_domain_risk_types:
      - unclear_endpoint
      - missing_data
    required_risk_tiers:
      - high
    min_high_or_critical_risks: 1
  expected_safety_gates:
    required_rule_ids:
      - validity_review
    required_approval_thresholds:
      - human_review
    min_approval_required_count: 1
    max_approval_required_count: 2
    required_insufficient_evidence_ids:
      - data_dictionary
    forbidden_rule_ids: []
    forbidden_approval_thresholds:
      - external_review
  expected_conflicts:
    count: 0
  expected_plan_executability:
    readiness: conditional
    min_implementation_ready_count: 1
    min_action_count: 1
    max_blocker_count: 0
    require_no_unresolved_conflicts: true
  expected_revisit_quality:
    stale_assumptions:
      mode: exact
      count: 0
    stale_evidence:
      mode: exact
      count: 0
    verification_gaps:
      mode: min
      count: 1
    due_revisits:
      mode: min
      count: 1
  expected_documents:
    - type: research-plan
      format: json
      require_source_traceability: true
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

Decision status expectations use runtime status names verbatim. The allowed decision statuses are
`unresolved`, `proposed`, `blocked`, `accepted`, `deferred`, `resolved-by-evidence`, and
`invalidated`. Evidence-based resolution must be represented as `resolved-by-evidence`; do not add
fixture-only aliases such as `answered_by_codebase`.

Risk expectations describe risk objects and risk tiers. Safety Gate expectations are separate and
describe gate outputs such as applied domain safety rules, approval thresholds, approval-required
counts, and missing domain evidence requirements. They may also express negative expectations with
`max_approval_required_count`, `forbidden_rule_ids`, and `forbidden_approval_thresholds`; generic
low-risk scenarios should use these fields to prove that domain-specific or approval-required gates
do not misfire. Runner code should match these expectations against the projected runtime, register
outputs, Safety Gate diagnostics, and document models.

Question efficiency is evaluated by running `advance_session()` against a temporary pre-close copy
of the scenario runtime. `probe_session_ids` defaults to all scenario sessions and `advance_steps`
defaults to `1`; the probe copy may be mutated, but the main evaluation runtime must remain stable
for document, register, gate, conflict, and snapshot checks.

Plan executability is diagnostic-only unless `expected_plan_executability` is present. When present,
the suite checks action-plan readiness, implementation-ready action count, and any configured total
action or blocker bounds. `require_no_unresolved_conflicts` defaults to `true` whenever plan
expectations are present; unresolved semantic conflicts fail the plan metric even if the raw action
plan output is otherwise `ready`. Conflict-detection scenarios should usually omit plan
executability expectations, or explicitly set this guard to `false` only when they are intentionally
testing raw action-plan output in isolation. Revisit quality is diagnostic-only unless
`expected_revisit_quality` is present; when present, stale assumptions, stale evidence, verification
gaps, and due revisits are checked independently. When document `require_source_traceability` is
true, the compiled document must carry non-empty source object and link traceability, and a
`source-traceability` section must be non-empty when the document type emits that section.

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
      "action_count": 2,
      "implementation_ready_count": 1,
      "blocker_count": 0,
      "unresolved_conflict_count": 0,
      "passed": true
    },
    "document_readability": {
      "required_sections_present": true,
      "empty_required_sections": [],
      "missing_source_traceability": [],
      "passed": true
    },
    "revisit_quality": {
      "stale_assumption_count": 0,
      "stale_evidence_count": 0,
      "verification_gap_count": 1,
      "due_revisit_count": 1,
      "passed": true
    }
  },
  "failures": []
}
```

Failures identify the metric, include a human-readable message, and may include a JSON path plus
the expected and actual values that caused the mismatch.

The report schema validates both structure and pass/fail consistency:

- `status: "passed"` requires all metric `passed` flags to be true and `failures` to be empty.
- `status: "failed"` requires at least one metric `passed` flag to be false and at least one
  failure entry.

Runtime-derived semantic checks still belong in the Evaluation Suite runner and assertion helpers.
Those helpers decide whether projections, registers, Safety Gate diagnostics, and compiled
documents satisfy the scenario. The report schema guarantees that the runner cannot emit a
self-contradictory report.

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

Step 5 stores committed baselines under each scenario's `expected_outputs/` directory:

- `project-state.json` (the normalized full project-state projection)
- `evaluation-report.json`
- `safety-gates.json`
- `risk-register.json`
- `documents/<document-type>.json`
- `documents/<document-type>.md` or `.csv` when the scenario asks for Markdown or CSV output

Markdown snapshots compare only the generated region when `decide-me` markers are present, ignoring
marker attributes and human-authored notes outside the region. Malformed marker blocks are invalid
snapshots and should fail normalization. JSON object keys named `project_head` are treated as
volatile, but rendered Markdown lines such as `Project head: ...` remain in snapshots because
scenario event streams are deterministic and the rendered line is part of the document contract. CSV
snapshots preserve the header and sort data rows deterministically. Normal tests never update
baselines automatically; explicit snapshot update support belongs to the Step 6 scenario runner.

## Scenario runner

Step 6 adds a development-only runner for local evaluation and explicit snapshot updates:

```bash
python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios
python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json
python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --update-snapshots
```

`--scenarios` accepts either a directory containing `*/scenario.yaml` files or a single
`scenario.yaml` file. The runner uses the same Python helper APIs as the integration tests: it
loads each scenario, builds a temporary runtime, runs the evaluation metrics, collects snapshots,
and compares them against `expected_outputs/`. It continues through all scenarios after failures
and exits non-zero when any evaluation fails or any snapshot drifts.

Snapshot updates are opt-in. With `--update-snapshots`, the runner rewrites `expected_outputs/`
only for scenarios whose evaluation report passes; failed evaluations are never blessed as new
baselines. Text output is intended for local scanning. JSON output reports aggregate status plus
per-scenario evaluation, snapshot, failure, mismatch, and update counts for automation.

## Maintainer commands

Use the Phase 10 release-readiness gate for CI and local final checks:

```bash
PYTHONPATH=. python3 scripts/run_phase10_gate.py
```

The gate runs the pytest `unit or phase_gate` slice first, then runs the committed scenario
evaluation runner in JSON mode. The corresponding GitHub Actions workflow is `.github/workflows/phase10-gate.yml`.
Schema validation tests use `jsonschema` with `referencing.Registry` resources for local `$ref`
resolution and avoid the deprecated resolver path from older `jsonschema` usage.

Use the scenario integration test for committed snapshot drift:

```bash
PYTHONPATH=. python3 -m unittest tests.integration.test_evaluation_scenarios -v
```

Use the development runner when iterating locally or when automation needs a JSON summary:

```bash
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json
```

Snapshot updates are never automatic in tests. Refresh baselines only after reviewing the behavior
change:

```bash
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --update-snapshots
```

Pytest markers are assigned automatically during collection:

```bash
PYTHONPATH=. python3 -m pytest -m "unit" -q
PYTHONPATH=. python3 -m pytest -m "phase_gate" -q
PYTHONPATH=. python3 -m pytest -m "evaluation" -q
PYTHONPATH=. python3 -m pytest -m "integration and not slow" -q
PYTHONPATH=. python3 -m pytest -m "slow" -q
```

## Distribution boundary

The evaluation contracts and this reference are bundled with the Skill because `schemas/` and
`references/` are part of the public distribution. Development fixtures and runners are not part of
the installable Skill package:

- include: `references/evaluation-suite.md`
- include: `schemas/evaluation-scenario.schema.json`
- include: `schemas/evaluation-report.schema.json`
- exclude: `tests/scenarios/**`
- exclude: `scripts/evaluate_scenarios.py`
- exclude: `__pycache__/**`
- exclude: `*.pyc`
- exclude: `*.pyo`
