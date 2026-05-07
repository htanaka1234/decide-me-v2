# decide-me-v2

`decide-me-v2` is a Codex Skill for turning ambiguous project work into a
decision-complete action plan. It interviews the user one decision at a time,
checks the codebase, docs, tests, and prior sessions before asking, records the
decisions it reaches, and can close one or more sessions into an implementation
plan.

The repository contains the v2 runtime behind that Skill: an event-sourced
object/link graph, rebuildable projections, taxonomy-aware session search,
object-native close summaries, an evidence source store for authoritative document snapshots and
citation units, and local derived exports for generic documents, plans, ADRs,
software-oriented decision registers, GitHub issue drafts, agent instruction
fragments, arc42 architecture docs, impact reports, traceability matrices, and verification gap
reports.

## Development policy

This project is still in early development. Keeping the codebase clean is the
highest priority, even when that means dropping backward compatibility for older
runtime state or intermediate APIs. Contract changes should update runtime code,
schemas, documentation, and tests together; invalid old state should fail
clearly rather than being silently adapted through compatibility layers.

## Phase 12 completion boundary

Phase 12 extends the MVP runtime stack built across Phases 5 through 11 with an evidence source
store:

- Phase 5: domain-neutral object/link event model and rebuildable projections
- Phase 6: Decision Stack Graph, read-only impact diagnostics, and explicit invalidation apply
- Phase 7: typed Evidence/Risk/Assumption metadata, Safety Gate, stale diagnostics, and approvals
- Phase 8: Document Compiler and derived exports
- Phase 9: built-in and user-defined Domain Packs
- Phase 10: committed scenario Evaluation Suite and release-readiness gate
- Phase 11: simulation benchmark fixtures, source-material validation, quality metrics, and runtime
  performance diagnostics
- Phase 12: immutable source snapshots, citation-unit decomposition, source-unit search, source
  evidence links, and read-only source impact diagnostics

The runtime source of truth is the transaction event log. `project-state.json`, session JSON,
register outputs, document models, indexes, and exports are derived and must be rebuildable.
Authoritative source text lives under `.ai/decide-me/sources/`, not inside `project-state.json`;
source audit events store IDs, hashes, timestamps, methods, counts, and quality flags rather than
full source text.
Invalidation is never applied automatically: candidates are generated from current projections and
only become events after explicit approval through the transaction path. High and critical risk
are controlled by Safety Gate policy; critical risk blocks automatic adoption and requires external
review, split/defer, or reject/rework handling. Domain-specific vocabulary belongs in Domain Packs,
not new core object types. `action` is the executable WorkUnit equivalent.

## What this Skill is for

Use decide-me when the problem is not "write the code now" yet. It is for the
moments where the work is still under-specified:

- a feature needs scope decisions before implementation
- a design has several viable approaches and tradeoffs
- a review surfaced follow-up questions that should not be lost
- parallel conversations need to converge into one plan
- previous decisions should be reused instead of re-litigated

The Skill's job is to reduce user fatigue. It should ask only the next useful
question, include a recommended answer, explain the tradeoff, and stop when the
current milestone is clear enough to execute.

## When to use it

Good fits:

- "Help me decide the MVP auth flow."
- "Turn this rough feature request into an implementation plan."
- "We discussed deployment constraints earlier; continue from that session."
- "Find the previous auth decisions and use them for this plan."
- "Close these discovery sessions and generate an action plan."

Poor fits:

- purely mechanical code edits with no decision to make
- one-off factual questions that can be answered directly from the repository
- long brainstorming where nothing needs to be recorded or carried forward

## How to use the Skill

Ask Codex to use decide-me for the decision thread you want to clarify. Useful
prompts look like this:

```text
Use decide-me to clarify this feature before implementation.
Resume the previous decide-me session about auth and continue.
Close this decide-me session and turn it into a plan.
Find prior decide-me decisions related to audit logging.
Generate a plan from the closed decide-me sessions for the MVP.
```

For a new thread, the Skill creates a session and binds discovered objects to
that session. For a continuing thread, it resumes the existing session, validates
state, and avoids treating stale proposals as silently accepted.

Before asking the user, the Skill should inspect available evidence:

- repository code
- docs and README-like files
- tests
- existing sessions
- prior object/link close summaries

If evidence already resolves a decision, the Skill records that instead of
asking again. Otherwise it asks exactly one question in this shape:

```text
Decision: D-012
Proposal: P-0007
Question: Should the MVP use email magic links or passwords?
Recommendation: Use email magic links for the MVP.
Why: Lower coordination and implementation burden for the current milestone.
If not: Password reset, password policy, and recovery flows become in scope now.
```

## How to answer its questions

Use short answers when the recommendation is right, and explicit answers when it
is not.

- `OK` accepts the current active proposal only when it is still valid in the
  same session.
- `Accept P-0007` explicitly accepts a proposal and is preferred when there is
  any chance of ambiguity.
- `Reject P-0007: reason` rejects the proposal and records why.
- `Defer D-012: reason` keeps the decision out of the current milestone without
  pretending it is resolved.
- A free-form answer such as `Use passwords because enterprise customers require
  them` becomes the accepted answer for the active proposal.

Free-form replies can also add constraints or discover follow-up decisions. For
example, `Use magic links, but they must expire within 15 minutes and we also
need audit logging` records the answer, captures the constraint, and can create a
new audit logging decision in the same session.

## Typical workflows

Start a new planning conversation:

1. Ask Codex to use decide-me for the feature or design.
2. Answer one decision question at a time.
3. Accept, reject, defer, or answer each proposal.
4. Close the session when the current milestone is clear.

Continue earlier work:

1. Ask Codex to list or show existing sessions.
2. Resume the relevant session.
3. Continue from the next unresolved decision.
4. Use explicit `Accept P-...` if the active proposal became stale.

Merge discovery into an execution plan:

1. Close each relevant session.
2. Generate a plan from the closed sessions.
3. Resolve conflicts or decision replacements if accepted decisions disagree.
4. Use the generated actions as implementation input.

Resolve conflicts and replacements:

- Same-session transaction conflicts use `detect-merge-conflicts` followed by
  `resolve-merge-conflict`.
- Related-session semantic conflicts are read-only diagnostics from `detect-session-conflicts`;
  resolve the underlying decisions with normal object/link events.
- Project-wide decision replacements use `resolve-decision-supersession`.

Resolve same-session transaction merge conflicts:

1. Run `python3 scripts/decide_me.py detect-merge-conflicts --ai-dir .ai/decide-me`.
2. Pick the `tx_id` to keep from the chosen option's `surviving_tx_ids`, and the `tx_id` or IDs
   to reject from that option's `reject_tx_ids`.
3. Run `python3 scripts/decide_me.py resolve-merge-conflict --ai-dir .ai/decide-me --session-id S-... --keep-tx-id T-... --reject-tx-id T-... --reason "..."`.
4. Rebuild or validate state. Rejected transaction files remain in `events/` for audit, but are excluded from normal projections.

Inspect session graph context:

1. Run `python3 scripts/decide_me.py show-session-graph --ai-dir .ai/decide-me --session-id S-... --include-inferred`.
2. Treat inferred graph candidates as advisory. `project_state.graph.nodes/edges` is the
   Decision Stack Graph over objects and links, not persisted session relationships.

Inspect Decision Stack Graph diagnostics:

1. Run `python3 scripts/decide_me.py show-impact --ai-dir .ai/decide-me --object-id O-... --change-kind changed`.
2. Run `python3 scripts/decide_me.py show-invalidation-candidates --ai-dir .ai/decide-me --object-id O-... --change-kind changed`.
3. Run `python3 scripts/decide_me.py show-decision-stack --ai-dir .ai/decide-me --object-id O-... --upstream-depth 1 --downstream-depth 2`.
4. Export a human-readable report with `python3 scripts/decide_me.py export-impact-report --ai-dir .ai/decide-me --object-id O-... --change-kind changed --output .ai/decide-me/exports/impact/O-...md`.
5. Impact report output paths must resolve under `.ai/decide-me/exports/impact/`.
6. `show-impact`, `show-invalidation-candidates`, `show-decision-stack`, and
   `export-impact-report` are read-only diagnostics.
7. To apply a materialized candidate, run
   `python3 scripts/decide_me.py apply-invalidation-candidate --ai-dir .ai/decide-me --object-id O-... --change-kind changed --candidate-id IC-... --session-id S-... --approve --reason "..."`.
   Without `--approve`, this command is dry-run only. Applies regenerate the candidate, evaluate the
   Safety Gate, and write only through the normal event transaction path. High severity candidates
   require a current `--safety-approval-id`; use `approve-safety-gate --candidate-apply-approval`
   when the target gate is otherwise approval-free. Critical severity candidates are not
   automatically applyable in this workflow.

Inspect Phase 7 register inputs:

1. Run `python3 scripts/decide_me.py show-evidence-register --ai-dir .ai/decide-me`.
2. Run `python3 scripts/decide_me.py show-assumption-register --ai-dir .ai/decide-me`.
3. Run `python3 scripts/decide_me.py show-risk-register --ai-dir .ai/decide-me`.
4. These commands return schema-shaped JSON from `project-state.json` only. They do not persist
   register state, evaluate safety gates, mark stale assumptions or evidence, or start approval
   workflows. The assumption register includes incoming `requires` / `derived_from` dependencies
   so it shows the same assumption dependency direction used by Safety Gate evaluation.

Inspect Phase 7 safety gates:

1. Run `python3 scripts/decide_me.py show-safety-gate --ai-dir .ai/decide-me --object-id O-...`.
2. Run `python3 scripts/decide_me.py show-safety-gates --ai-dir .ai/decide-me`.
3. These commands return read-only safety diagnostics. They do not persist gate state, apply
   invalidation candidates, or write events.
4. Record approval for a gate with `python3 scripts/decide_me.py approve-safety-gate --ai-dir .ai/decide-me --session-id S-... --object-id O-... --approved-by user --reason "..."`.
5. Inspect approval artifacts with `python3 scripts/decide_me.py show-safety-approvals --ai-dir .ai/decide-me --object-id O-...`.
6. Approval is stored as a normal `artifact` object plus `addresses` link. A matching approval is
   valid only for the current `gate_digest`; approval writes require an existing mutable session.
7. Evidence-based resolution records evidence but leaves the decision open when the projected gate
   needs approval. Approve the current digest, then retry the evidence resolution.
8. Critical risk blocks automatic adoption. Explicit approval alone is not sufficient; the gate
   reports required actions for external review, splitting/deferment, or rejection/rework.

Inspect Phase 7 stale diagnostics:

1. Run `python3 scripts/decide_me.py show-stale-assumptions --ai-dir .ai/decide-me --now 2026-04-28T12:00:00Z`.
2. Run `python3 scripts/decide_me.py show-stale-evidence --ai-dir .ai/decide-me --now 2026-04-28T12:00:00Z`.
3. Run `python3 scripts/decide_me.py show-verification-gaps --ai-dir .ai/decide-me --now 2026-04-28T12:00:00Z`.
4. Run `python3 scripts/decide_me.py show-revisit-due --ai-dir .ai/decide-me --now 2026-04-28T12:00:00Z`.
5. These commands return structured read-only diagnostics. Safety gate evaluation consumes stale
   evidence, expired assumptions, and verification gaps directly; the stale commands themselves do
   not write events, update projections, apply invalidation candidates, or create approval objects.
   `export-verification-gaps` remains the Markdown export command.
   Stale evidence output includes indirect affected decisions and representative paths when stale
   evidence reaches decisions through verification, assumption, or proposal links.

Use the Phase 12 evidence source store:

1. Import an XML, HTML, Markdown, text, or PDF snapshot with
   `python3 scripts/decide_me.py import-source --ai-dir .ai/decide-me --type academic_regulation --title "医学部教務規則" --file ./rules.xml --effective-from 2026-04-01`.
2. Decompose XML/HTML/Markdown/text sources with
   `python3 scripts/decide_me.py decompose-source --ai-dir .ai/decide-me --source-id SRC-... --strategy auto`.
3. Search citation units with
   `python3 scripts/decide_me.py search-evidence --ai-dir .ai/decide-me --query "履修登録 締切"`.
4. Link a source unit to a runtime decision or object with
   `python3 scripts/decide_me.py link-evidence --ai-dir .ai/decide-me --session-id S-... --decision-id D-... --source-unit-id NU-... --relevance supports`.
5. Inspect source impact with
   `python3 scripts/decide_me.py show-source-impact --ai-dir .ai/decide-me --source-id SRC-...`.
6. Source impact is read-only. It never invalidates decisions, creates revisit triggers, or applies
   source changes automatically.

Record object relationships:

1. Domain state changes are represented by `object_recorded`, `object_updated`,
   `object_status_changed`, `object_linked`, and `object_unlinked`.
2. `object_updated` may update only `title`, `body`, and `metadata`; identity, type, links,
   and status are not patchable.
3. `object_status_changed` uses audited transitions with `object_id`, `from_status`,
   `to_status`, `reason`, and `changed_at`.
4. Session Q&A state is represented by `session_question_asked` and
   `session_answer_recorded`; answers use `{summary, answered_at, answered_via}`.

Reuse prior context:

1. Search sessions by topic, domain, abstraction level, or tag.
2. Inspect prior objects, links, and close summaries.
3. Resume the matching session or start a new one with the old decisions as
   evidence.

## Runtime model, briefly

The runtime lives under `.ai/decide-me/`.

- `events/**/*.jsonl` transaction files are the source of truth.
- `transaction_rejected` control events exclude rejected transaction IDs from
  the effective projection stream without deleting the rejected files.
- The domain-neutral event whitelist is `project_initialized`, `session_created`,
  `session_resumed`, `session_closed`, `close_summary_generated`, `plan_generated`,
  `taxonomy_extended`, `source_document_imported`, `normative_units_extracted`,
  `source_version_updated`, `evidence_linked_to_object`, `transaction_rejected`, `object_recorded`, `object_updated`,
  `object_status_changed`, `object_linked`, `object_unlinked`,
  `session_question_asked`, and `session_answer_recorded`.
- `sources/` stores immutable source snapshots and citation units. `index/source_units.sqlite` is
  a derived source-unit search index and can be rebuilt with `rebuild-evidence-index`.
- Deleted decision/proposal/session-graph compatibility event names are rejected rather than
  migrated or backfilled.
- `project-state.json` is the rebuildable object/link projection. It contains project metadata,
  projection metadata, protocol settings, session index data, counts, `objects`, `links`, and the
  derived Decision Stack Graph.
- `taxonomy-state.json` and `sessions/*.json` are also rebuildable projections and the normal
  hot-path read cache.
- Close summaries store object and link reference sets in `close_summary.object_ids` and
  `close_summary.link_ids`; generated plans consume those references and emit
  `action_plan.actions` plus `action_plan.implementation_ready_actions`.
- An `action` object is the executable WorkUnit equivalent. There is no separate
  `work_unit` object type; WorkUnit attributes live in optional action metadata such as
  `action_type`, `required_inputs`, `outputs`, `verification_refs`, and
  `source_decision_refs`.
- `runtime-index.json` checkpoints the current projection head, event count,
  rejected transaction IDs, last event sort key, and projection file manifest.
- `session-graph-cache.json` may cache full inferred session graph output by
  `project_head`; persisted project state keeps Decision Stack Graph nodes and edges plus empty
  inferred candidates until a command asks for session graph inference.
- `exports/` contains human-readable plans, impact reports, ADRs, structured ADRs,
  software-oriented decision registers, local GitHub issue drafts, agent instruction fragments,
  arc42 architecture docs, traceability matrices, and verification gap reports. These are derived exports, not runtime
  state.
- `write.lock` protects runtime writes.

Legacy runtimes that still have `.ai/decide-me/event-log.jsonl` are not migrated
automatically by this version. Rebootstrap the runtime, or export the old state
with the previous runtime and recreate it under the transaction-file layout.

Normal users should not edit runtime state by hand. If projections look wrong,
rebuild them from the transaction event files and validate state instead of
patching JSON files directly.

## For maintainers

Python 3.11 or newer is required. Install the runtime dependency set before using the bundled
Domain Pack loader:

```bash
python3 -m pip install -r requirements.txt
```

Bootstrap a runtime only when one does not exist:

```bash
python3 scripts/decide_me.py bootstrap \
  --ai-dir .ai/decide-me \
  --project-name "Example Project" \
  --objective "Turn discovery into an implementation-ready action plan" \
  --current-milestone "MVP planning"
```

The CLI is deterministic and is mainly for Skill internals, automation, and
debugging. Use `python3 scripts/decide_me.py --help` for the full subcommand
reference. Common maintainer operations include:

- `list-sessions`, `show-session`, and `resume-session`
- `list-domain-packs` and `show-domain-pack` to inspect available declarative domain packs
- `create-session --domain-pack research|procurement|software|operations|personal_planning|writing|generic`
  to explicitly select a pack;
  omitted packs are inferred from context and unresolved contexts fall back to `generic`
- `list-sessions --domain-pack <id>` to filter sessions by stored pack metadata; sessions created
  before pack metadata are displayed as `generic`
- `advance-session` and `handle-reply`
- `close-session` and `generate-plan`
- `validate-state` / `validate-state --full` for full event-log validation,
  `validate-state --cached` / `--fast` for projection/index validation, `rebuild-projections`,
  and `compact-runtime`
- `benchmark-runtime` with `DECIDE_ME_PERF=1`
- `show-impact`, `show-invalidation-candidates`, and `show-decision-stack` for read-only Decision
  Stack Graph diagnostics; `apply-invalidation-candidate` for explicit approved application of
  materialized invalidation candidates
- `show-evidence-register`, `show-assumption-register`, and `show-risk-register` for read-only
  Phase 7 register inputs
- `show-safety-gate` and `show-safety-gates` for read-only Phase 7 safety gate diagnostics,
  including the effective risk policy for high and critical risk
- `show-stale-assumptions`, `show-stale-evidence`, `show-verification-gaps`, and
  `show-revisit-due` for read-only Phase 7 stale diagnostics
- `export-impact-report` to write a derived Markdown impact report without changing runtime state
- `export-document --type decision-brief|action-plan|risk-register|review-memo|research-plan|comparison-table`
  to write generic Markdown, JSON, or supported CSV documents under `.ai/decide-me/exports/documents/`
  and `export-document --domain-pack <id>` to apply a pack document profile when the pack defines
  one. When omitted, export uses the single pack represented by the selected closed sessions, falls
  back to the generic profile when it defines the document type, and fails for pack-specific
  documents that the selected pack does not define. Current profiles record metadata and prioritize
  required sections; richer pack-specific sections are later builder work.
- `export-github-templates` to write local issue forms under `.github/ISSUE_TEMPLATE`
- `export-architecture-doc --format arc42` for a derived architecture skeleton
- `export-traceability --format csv|markdown` for decision/action/verification traceability
- `export-verification-gaps` for Markdown missing verification and evidence reports
- `export-github-issues` to write local issue body Markdown and `issues.json` from closed sessions
  Re-exporting replaces the generated `issues/` directory, so do not keep hand-edited files there.
- `export-agent-instructions` to write derived AGENTS.md, Cursor rule, Claude fragment, or Codex
  profile fragment files from final agent-relevant decisions. Decision metadata
  `agent_relevant: true | false | null` can override the conservative keyword filter; missing or
  `null` keeps the default detection.

Full event-log replay uses `find` for event file discovery when available. Set
`DECIDE_ME_EVENT_DISCOVERY=python` to force pure Python discovery, or
`DECIDE_ME_EVENT_DISCOVERY=shell` to require shell discovery.

Install development test dependencies before running the full test suite. The development
requirements include the runtime requirements:

```bash
python3 -m pip install -r requirements-dev.txt
```

Schema contract tests use `jsonschema` with the `referencing` registry API for local `$ref`
resolution. They intentionally avoid the deprecated resolver path from older `jsonschema` usage.

Run the focused suites with:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests/unit -v
PYTHONPATH=. python3 -m unittest discover -s tests/smoke -v
PYTHONPATH=. python3 -m unittest discover -s tests/integration -v
```

Pytest is also supported for marked release and maintenance slices:

```bash
PYTHONPATH=. python3 -m pytest -m "unit" -q
PYTHONPATH=. python3 -m pytest -m "phase_gate and not slow" -q
PYTHONPATH=. python3 -m pytest -m "evaluation" -q
PYTHONPATH=. python3 -m pytest -m "integration and not slow" -q
PYTHONPATH=. python3 -m pytest -m "slow" -q
```

Run the Phase 11 release-readiness gate with:

```bash
PYTHONPATH=. python3 scripts/run_phase11_gate.py
```

The gate runs the `phase_gate and not slow` pytest slice, including an explicit lightweight unit
contract subset, and then the committed Phase 11 scenario evaluation runner in JSON mode. Slow
evaluation snapshot tests remain available for nightly or manual checks.

Run the Phase 12 source-store gate with:

```bash
PYTHONPATH=. python3 scripts/run_phase12_gate.py
```

Run the full test suite with:

```bash
PYTHONPATH=. python3 -m unittest discover -v
```

Run the Phase 11 evaluation scenarios with committed snapshots:

```bash
PYTHONPATH=. python3 -m unittest tests.integration.test_evaluation_scenarios -v
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --format json
```

Update evaluation snapshots only when the scenario behavior change is intentional:

```bash
PYTHONPATH=. python3 scripts/evaluate_scenarios.py --scenarios tests/scenarios --update-snapshots
```

## Project layout

- `SKILL.md`: public Skill entrypoint
- `references/`: protocol, lifecycle, taxonomy, event model, domain packs, plan generation,
  output contract, document compiler behavior, evaluation suite behavior, and examples
- `schemas/`: JSON contracts for events and projections
- `templates/`: plan, ADR, structured ADR, GitHub issue, traceability, verification gap, domain
  document, and agent instruction export templates
- `decide_me/`: runtime implementation
- `scripts/decide_me.py`: deterministic CLI
- `scripts/evaluate_scenarios.py`: development-only Phase 11 evaluation runner
- `scripts/run_phase11_gate.py`: CI/local Phase 11 release-readiness gate
- `scripts/run_phase12_gate.py`: CI/local Phase 12 source-store gate
- `requirements.txt`: runtime dependency declarations, including PyYAML for declarative pack YAML
  loading
- `requirements-dev.txt`: development-only dependencies for schema validation tests
- `tests/`: unit, integration, Phase 11 scenario coverage, and Phase 12 source-store coverage
