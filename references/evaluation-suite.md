# Evaluation Suite

Phase 11 turns the development-side scenario suite into a simulation benchmark harness. It
evaluates quality and runtime performance in the same deterministic runner so the Skill cannot
look correct while losing evidence, missing conflicts, producing unusable documents, or becoming
too slow at larger event counts.

The public contracts are:

- `schemas/evaluation-scenario.schema.json`
- `schemas/evaluation-report.schema.json`

The runner remains development-only and does not call an LLM.

## Scenario Layout

Committed benchmark scenarios live under `tests/scenarios/`. The canonical Phase 11 scenario set is:

- `software_project`
- `research_protocol`
- `procurement_decision`
- `policy_interpretation`
- `operations_incident`
- `personal_planning`
- `writing_project`

A scenario directory contains:

- `scenario.yaml`: the schema-versioned orchestrator with project, sessions, seed event files, and
  deterministic evaluation clock.
- `input_context.md`: the human-facing scenario brief.
- `source_materials/`: local source files referenced by evidence object metadata.
- `events*.jsonl`: deterministic EventSpec rows used to build a temporary runtime.
- `expected/*.yaml`: semantic expectations for quality and optional performance gates.
- `expected/document_outputs/`: normalized generated baselines plus `manifest.yaml` for document
  expectations.

`scenario.yaml` is intentionally lean:

```yaml
schema_version: 2
scenario_id: policy_interpretation
label: Policy interpretation benchmark
domain_pack: generic

project:
  name: Demo policy project
  objective: Interpret an internal policy exception with rationale, risk, and action follow-up.
  current_milestone: Policy interpretation recommendation

sessions:
  - session_id: S-policy-interpretation
    context: Interpret whether a limited exception can proceed under the policy excerpt.
    seed_events: events.jsonl
    close: true

evaluation:
  now: "2026-04-29T00:00:00Z"
```

Semantic expectations are split by concern:

- `expected/decisions.yaml`: required domain decision types and status counts.
- `expected/unresolved_questions.yaml`: maximum question count, repeated-question guards, and
  optional probe session settings.
- `expected/evidence.yaml`: linked evidence minimums, required evidence requirement IDs, and
  required source refs.
- `expected/conflicts.yaml`: expected conflict count plus required IDs or types.
- `expected/risks.yaml`: required risk types, tiers, high/critical counts, and nested Safety Gate
  expectations when relevant.
- `expected/assumptions.yaml`: required assumption exposure and stale/evidence/gap/revisit
  diagnostics.
- `expected/action_plan.yaml`: action-plan readiness, executable action bounds, blocker bounds, and
  unresolved-conflict policy.
- `expected/performance.yaml`: optional performance thresholds such as `max_total_seconds` and
  `max_load_runtime_seconds`.
- `expected/document_outputs/manifest.yaml`: document type, format, required sections, session
  scope, and source-traceability requirements.

Evidence `metadata.source_ref` must point to `input_context.md` or a file under
`source_materials/`. Absolute paths, parent-directory traversal, and missing source files are
invalid fixtures.

## Metrics

The Phase 11 report emits these metrics:

- `decision_coverage`: required decision types and status counts.
- `question_efficiency`: questions asked in probe runs and forbidden repeated question types.
- `conflict_detection_recall`: required conflicts were detected.
- `conflict_precision`: unexpected conflicts were not over-reported.
- `evidence_linkage_rate`: evidence is linked to decisions/actions and source refs are valid.
- `assumption_exposure`: assumptions and stale/revisit diagnostics are explicit.
- `risk_coverage`: expected risks and Safety Gate outputs are present.
- `action_executability`: generated actions are executable under the scenario expectations.
- `document_validity`: compiled documents contain required non-empty sections and traceability.
- `runtime_performance`: event/session/object counts and timing diagnostics.

Runtime performance is recorded for every scenario. It fails a scenario only when
`expected/performance.yaml` defines thresholds.

## Report Shape

The report is a schema-shaped JSON object with deterministic `generated_at` from `evaluation.now`.
Timing values are present in the live report but normalized out of committed snapshots.

```json
{
  "schema_version": 2,
  "scenario_id": "policy_interpretation",
  "status": "passed",
  "generated_at": "2026-04-29T00:00:00Z",
  "metrics": {
    "decision_coverage": {"required_count": 2, "covered_count": 2, "missing_ids": [], "passed": true},
    "question_efficiency": {"asked_count": 0, "max_allowed": 1, "repeated_forbidden_decision_types": [], "passed": true},
    "conflict_detection_recall": {"expected_count": 0, "actual_count": 0, "missing_conflict_ids": [], "missing_conflict_types": [], "passed": true},
    "conflict_precision": {"expected_count": 0, "actual_count": 0, "unexpected_conflict_ids": [], "false_positive_count": 0, "passed": true},
    "evidence_linkage_rate": {"required_count": 1, "covered_count": 1, "linked_evidence_count": 1, "total_evidence_count": 1, "linkage_rate": 1.0, "missing_ids": [], "invalid_source_refs": [], "passed": true},
    "assumption_exposure": {"required_count": 1, "covered_count": 1, "assumption_count": 1, "stale_assumption_count": 0, "stale_evidence_count": 0, "verification_gap_count": 1, "due_revisit_count": 0, "missing_ids": [], "passed": true},
    "risk_coverage": {"required_count": 1, "covered_count": 1, "missing_ids": [], "passed": true},
    "action_executability": {"readiness": "conditional", "action_count": 3, "implementation_ready_count": 0, "blocker_count": 0, "unresolved_conflict_count": 0, "passed": true},
    "document_validity": {"required_sections_present": true, "empty_required_sections": [], "missing_source_traceability": [], "passed": true},
    "runtime_performance": {"total_seconds": 0.1, "load_runtime_seconds": 0.01, "event_count": 20, "session_count": 1, "object_count": 8, "decision_count": 2, "max_total_seconds": null, "max_load_runtime_seconds": null, "passed": true}
  },
  "failures": []
}
```

`status: "passed"` requires all metric `passed` flags to be true and no failures. `status:
"failed"` requires at least one failed metric and at least one failure object.

## Runner

Use the development runner for local iteration:

```bash
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --update-snapshots
```

`--scenarios` accepts either a directory containing `*/scenario.yaml`, one scenario directory, or a
single `scenario.yaml`. The runner builds temporary runtimes, evaluates all metrics, compares
snapshots under `expected/document_outputs/`, continues after failures, and exits non-zero if any
scenario fails.

Snapshot updates are opt-in. With `--update-snapshots`, the runner rewrites
`expected/document_outputs/` only for scenarios whose semantic evaluation passed.

## Maintainer Commands

Use the Phase 11 release-readiness gate for CI and local final checks:

```bash
PYTHONPATH=. python3 scripts/run_phase11_gate.py
```

The gate runs the `phase_gate and not slow` pytest slice, then the scenario runner in JSON mode.
The corresponding GitHub Actions workflow is `.github/workflows/phase11-gate.yml`.

Snapshot drift checks:

```bash
PYTHONPATH=. python3 -m unittest tests.integration.test_evaluation_scenarios -v
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json
```

## Distribution Boundary

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
