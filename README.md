# decide-me-v2

`decide-me-v2` is a Codex Skill for turning ambiguous project work into a
decision-complete action plan. It interviews the user one decision at a time,
checks the codebase, docs, tests, and prior sessions before asking, records the
decisions it reaches, and can close one or more sessions into an implementation
plan.

The repository contains the v2 runtime behind that Skill: an event-sourced
decision log, rebuildable projections, taxonomy-aware session search, close
summaries, and plan exports.

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

For a new thread, the Skill creates a session and binds discovered decisions to
that session. For a continuing thread, it resumes the existing session, validates
state, and avoids treating stale proposals as silently accepted.

Before asking the user, the Skill should inspect available evidence:

- repository code
- docs and README-like files
- tests
- existing sessions
- prior close summaries

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
4. Use the generated action slices as implementation input.

Resolve conflicts and replacements:

- Same-session transaction conflicts use `detect-merge-conflicts` followed by
  `resolve-merge-conflict`.
- Related-session semantic conflicts use `detect-session-conflicts` followed by
  `resolve-session-conflict`.
- Project-wide decision replacements use `resolve-decision-supersession`.

Resolve same-session transaction merge conflicts:

1. Run `python3 scripts/decide_me.py detect-merge-conflicts --ai-dir .ai/decide-me`.
2. Pick the `tx_id` to keep from the chosen option's `surviving_tx_ids`, and the `tx_id` or IDs
   to reject from that option's `reject_tx_ids`.
3. Run `python3 scripts/decide_me.py resolve-merge-conflict --ai-dir .ai/decide-me --session-id S-... --keep-tx-id T-... --reject-tx-id T-... --reason "..."`.
4. Rebuild or validate state. Rejected transaction files remain in `events/` for audit, but are excluded from normal projections.

Resolve semantic conflicts across related sessions:

1. Link explicit parent/child context with `python3 scripts/decide_me.py link-session --ai-dir .ai/decide-me --parent-session-id S-... --child-session-id S-... --relationship refines --reason "..."`.
2. Inspect graph context with `python3 scripts/decide_me.py show-session-graph --ai-dir .ai/decide-me --session-id S-... --include-inferred`.
3. Run `python3 scripts/decide_me.py detect-session-conflicts --ai-dir .ai/decide-me --session-id S-... --include-related`.
4. Resolve the chosen semantic conflict with `python3 scripts/decide_me.py resolve-session-conflict --ai-dir .ai/decide-me --conflict-id C-... --winning-session-id S-... --reject-session-id S-... --reason "..."`.

Resolve decision replacements:

1. Ensure the superseding decision is accepted or resolved by evidence.
2. Run `python3 scripts/decide_me.py resolve-decision-supersession --ai-dir .ai/decide-me --session-id S-... --superseded-decision-id D-old --superseding-decision-id D-new --reason "..."`.
3. The legacy `invalidate-decision` command remains as a compatibility alias, but new workflows
   should use the resolution command above.

Reuse prior context:

1. Search sessions by topic, domain, abstraction level, or tag.
2. Inspect the prior decisions and close summaries.
3. Resume the matching session or start a new one with the old decisions as
   evidence.

## Runtime model, briefly

The runtime lives under `.ai/decide-me/`.

- `events/**/*.jsonl` transaction files are the source of truth.
- `transaction_rejected` control events exclude rejected transaction IDs from
  the effective projection stream without deleting the rejected files.
- `session_linked` records explicit semantic parent/child session graph edges.
- `semantic_conflict_resolved` records user-selected scoped conflict resolution across
  explicitly related sessions. Event files remain for audit, but rejected scoped content is
  suppressed from normal session, search, evidence-reuse, and plan projections.
- `decision_invalidated` records decision supersession from `resolve-decision-supersession`;
  old decisions remain in events for audit and are hidden from normal projections.
- `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` are
  rebuildable projections and the normal hot-path read cache.
- `runtime-index.json` checkpoints the current projection head, event count,
  rejected transaction IDs, last event sort key, and projection file manifest.
- `session-graph-cache.json` may cache full inferred graph output by
  `project_head`; persisted project state keeps inferred candidates empty until
  a command asks for them.
- `exports/` contains human-readable plans, ADRs, structured ADRs, and decision registers.
- `write.lock` protects runtime writes.

Legacy runtimes that still have `.ai/decide-me/event-log.jsonl` are not migrated
automatically by this version. Rebootstrap the runtime, or export the old state
with the previous runtime and recreate it under the transaction-file layout.

Normal users should not edit runtime state by hand. If projections look wrong,
rebuild them from the transaction event files and validate state instead of
patching JSON files directly.

## For maintainers

Python 3.11 or newer is enough for the included runtime. The runtime has no third-party
Python dependency requirement.

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
- `advance-session` and `handle-reply`
- `close-session` and `generate-plan`
- `validate-state` / `validate-state --full` for full event-log validation,
  `validate-state --cached` / `--fast` for projection/index validation, `rebuild-projections`,
  and `compact-runtime`
- `benchmark-runtime` with `DECIDE_ME_PERF=1`

Full event-log replay uses `find` for event file discovery when available. Set
`DECIDE_ME_EVENT_DISCOVERY=python` to force pure Python discovery, or
`DECIDE_ME_EVENT_DISCOVERY=shell` to require shell discovery.

Install development test dependencies before running the full test suite:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run the test suite with:

```bash
PYTHONPATH=. python3 -m unittest discover -v
```

## Project layout

- `SKILL.md`: public Skill entrypoint
- `references/`: protocol, lifecycle, taxonomy, event model, plan generation,
  output contract, and examples
- `schemas/`: JSON contracts for events and projections
- `templates/`: ADR, structured ADR, and action-plan export templates
- `decide_me/`: runtime implementation
- `scripts/decide_me.py`: deterministic CLI
- `requirements-dev.txt`: development-only dependencies for schema validation tests
- `tests/`: unit and integration coverage
