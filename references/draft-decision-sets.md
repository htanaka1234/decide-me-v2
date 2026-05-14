# Draft Decision Sets

DraftDecisionSet files are sidecar review artifacts. They help a human inspect a decision space before
any canonical decision is promoted into a normal session proposal flow.

## Boundary

`.ai/decide-me/draft-sets/DS-.../draft-set.json` is not canonical event-log state and is not the
runtime source of truth. Creating, showing, listing, projecting, reviewing, exporting, and
`autopilot-draft` iteration must not emit events, mutate `project-state.json`, update
`taxonomy-state.json`, or edit `sessions/*.json`.

Draft sets may contain recommendations, risks, assumptions, actions, verification notes, and promotion
metadata, but those fields remain draft sidecar data until a user explicitly promotes a draft decision.
Every human-readable draft export must clearly say `DRAFT / NOT ACCEPTED`.

## Directory Layout

```text
.ai/decide-me/draft-sets/
  DS-YYYYMMDD-NNN/
    draft-set.json
    draft-projection.json
    review-queue.json
    promotion-log.jsonl
    exports/
      preflight.md
      draft-decisions.md
      review-queue.md
      assumptions-risks.md
```

`draft-set.json` is the structured sidecar. `draft-projection.json` is a derived sidecar artifact built
from the canonical projection plus the draft set; it is not source of truth and is not replayed from the
event log. `review-queue.json` and the Markdown files are derived from draft sidecars plus the current
project head. `promotion-log.jsonl` is an audit sidecar for promotion attempts; it is not part of the
canonical event whitelist.

## Schema Summary

Draft sets must match `schemas/draft-decision-set.schema.json`. `create-draft-set` normalizes the
top-level `schema_version`, `id`, `status`, `mode`, `created_at`, `generated_by`, `source_context`,
`convergence`, optional annotation arrays, and `promotion` defaults when omitted.

The Skill-generated payload must still provide a complete `goal` object and schema-shaped
`draft_decisions`. Each draft decision requires:

- `id`
- `status`
- `layer`
- `priority`
- `frontier`
- `kind`
- `question`
- `recommendation`
- `rationale`
- `alternatives`
- `risk_tier`
- `reversibility`
- `evidence_coverage`
- `human_review`
- `promotion_recipe`

`draft_assumptions`, `draft_risks`, `draft_actions`, and `draft_verifications` are intentionally loose
sidecar annotations. They are not strict canonical object contracts and must not be promoted directly.

## Create / Show / List

Use `create-draft-set` to persist a sidecar without writing canonical events:

```bash
python3 <skill-root>/scripts/decide_me.py create-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-json <tmp>/draft-set.input.json \
  --generated-by skill
```

The command returns:

- `status`
- `draft_set_id`
- `path`
- `project_head_at_generation`
- `is_stale`
- `counts`

Use `show-draft-set` to inspect one sidecar and its runtime staleness:

```bash
python3 <skill-root>/scripts/decide_me.py show-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN
```

Use `list-draft-sets` to list sidecars with summaries:

```bash
python3 <skill-root>/scripts/decide_me.py list-draft-sets \
  --ai-dir <repo-root>/.ai/decide-me
```

## Draft Projection

`project-draft-set` builds `draft-projection.json` and reports deterministic gap diagnostics:

```bash
python3 <skill-root>/scripts/decide_me.py project-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN
```

The projection combines committed runtime state and the sidecar draft set without changing either. It
summarizes canonical objects, draft objects, graph links, stale project-head state, convergence status,
and gap diagnostics such as missing P0/P1 recommendations, insufficient evidence, high-risk bulk
review, dangling references, and conflicts with accepted decisions.

Because `project-draft-set` is a standalone diagnostic command, it may return
`stop_reason=stopped` when the projection has non-blocking diagnostics but no autopilot iteration was
requested. `autopilot-draft` narrows stop reasons to its deterministic iteration outcomes. User-facing
Codex `/goal` reports should not present standalone `stopped` as completion; normalize it to a review
handoff such as `user_review_required` unless an autopilot run explicitly reports `converged`.

Projection convergence is fail-closed: when the current projection contains any blocking gap, the
projection reports the current blocking classification and `status=blocked` even if the saved draft-set
convergence says `converged`.

`autopilot-draft` can create a draft set from a Skill-generated seed JSON or a conservative goal-only
skeleton, run iterative gap detection, persist `draft-projection.json`, and optionally export Markdown:

```bash
python3 <skill-root>/scripts/decide_me.py autopilot-draft \
  --ai-dir <repo-root>/.ai/decide-me \
  --seed-draft-json <tmp>/draft-set.input.json \
  --max-iterations 3
```

It may add supplemental draft decisions, actions, or verifications for structural coverage gaps. It must
not upgrade evidence coverage, resolve conflicts with accepted decisions, relax high/critical risk bulk
rules, or create accepted decisions.

## Review Queue

`review-draft-set` builds `review-queue.json`. `export-draft-set` also builds the review queue, so the
normal readable-export flow does not need to call `review-draft-set` separately.

The review queue sorts draft decisions and classifies them as:

- blocked
- individual review required
- bulk materialize candidate
- already promoted

High or critical risk, medium risk or above, P0/P1 priority, challenged or missing evidence, conflicts,
explicit individual review flags, and blocked draft fields must not enter the bulk candidate list.
`bulk_promotable=true` means "eligible to place into proposal review in bulk"; it never means accepted.

## Readable Exports

`export-draft-set --format markdown` writes:

- `preflight.md`
- `draft-decisions.md`
- `review-queue.md`
- `assumptions-risks.md`

These files are readable review artifacts. They follow the managed Markdown-region discipline and
preserve `## Human Notes` on regeneration, but they are not canonical document models and are not
accepted decisions.

## Promotion

Promotion is the only draft operation that writes canonical events, and it uses existing event types
only. `promote-draft-decision` materializes one draft decision as a normal canonical decision with an
active proposal and question state. Medium, high, and critical draft risk also materializes a canonical
risk scaffold.

Promotion records provenance in `decision.metadata.draft_origin` and in the proposal metadata. It also
appends the sidecar `promotion-log.jsonl`. Promotion does not accept the proposal. Acceptance remains a
separate normal proposal reply, such as `Accept P-draft-...`, and must still pass Safety Gate checks.

## Staleness

`source_context.project_head_at_generation` records the canonical project head used when the draft set
was created. Review and export report staleness as a warning when the current project head differs.

Single draft promotion rejects stale draft sets by default. The Skill must not pass `--allow-stale`
unless the user explicitly asks after seeing the stale warning. When a stale promotion is allowed,
`decision.metadata.draft_origin.stale_promoted` is `true`. Bulk promotion always rejects stale draft
sets.

## Provenance

Draft-derived canonical objects must preserve:

- `draft_set_id`
- `draft_decision_id`
- generation project head
- current project head at promotion
- promotion timestamp
- promotion mode
- stale-promotion flag

The canonical event log remains the source of truth after promotion. The sidecar provenance is for
traceability, not for rebuilding canonical state.

If canonical promotion succeeds but sidecar promotion metadata is missing or stale, use
`reconcile-draft-promotions` to compare canonical `decision.metadata.draft_origin` against the sidecar:

```bash
python3 <skill-root>/scripts/decide_me.py reconcile-draft-promotions \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN
```

The command is report-only by default. Add `--repair` only when sidecar reconciliation is desired; it
rewrites `promotion.promoted_decision_ids` and `promotion-log.jsonl` from canonical provenance without
writing canonical events.

## Safety Constraints

- Draft sets must display `DRAFT / NOT ACCEPTED` in readable exports and user summaries.
- `/goal` and draft export flows must not create accepted decisions.
- Promotion must not bypass active proposal checks, explicit acceptance requirements, or Safety Gate.
- P0/P1, medium/high/critical risk, missing evidence, challenged evidence, conflicts, and individual
  review items require individual review.
- `promote-draft-set --only-bulk-promotable` is limited to low-risk eligible items and requires
  separate sessions through `--session-map-json` when more than one active proposal would be created.

## Example

```bash
python3 <skill-root>/scripts/decide_me.py export-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-20260513-001 \
  --format markdown
```

The expected user-facing summary must include the draft set ID, counts, review summary, export paths,
and this notice:

```text
This is DRAFT / NOT ACCEPTED. No accepted decision was created.
```
