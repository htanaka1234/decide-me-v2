# Goal Autopilot Drafting

`/goal` is a Skill-only decision preflight flow. It expands a user goal into a structured
DraftDecisionSet sidecar, exports readable review files, and returns a review summary. It does not
create accepted decisions.

## Purpose

Use `/goal` when the user wants the decision space expanded before accepting individual decisions. The
flow is optimized for early visibility, low user fatigue, and safe handoff into normal proposal review.

The result is a single-pass draft set. It reflects the goal, available runtime evidence, search budget,
and risk threshold used for the turn. It does not prove convergence and must not claim that no
undiscovered issues remain.

## Non-goals

PR-4 does not add a Python generator, new schema, external API integration, automatic file edits, or an
`autopilot-draft` CLI. An `autopilot-draft` CLI does not exist in this version, so the Skill must not
document or invoke it as an available command.

`/goal` must not call promotion commands. It creates a draft set and readable exports only. Promotion is
a later explicit user handoff.

## User Command

The Skill starts this flow when the user input begins with `/goal`, or when the user clearly asks to
create a draft decision set, preflight a goal, or expand a goal into draft decisions instead of running
the normal one-question interview.

Example:

```text
/goal
goal: Add goal-based draft decision sets to decide-me.
constraints:
- do not mutate canonical runtime
- readable export must be reviewed by humans
- accepted decisions must not be created automatically
mode: autopilot-draft
```

If the user omits `mode`, treat it as `autopilot-draft`. If the user writes `accept`, `auto-accept`,
`execute`, or similar terms, keep the flow in draft mode and do not create accepted decisions or
external side effects.

## Input Normalization

Normalize free-form input into these fields:

| Input | Normalized field | Default |
| --- | --- | --- |
| `goal`, `title`, or purpose text | `goal.title` | Required |
| `desired_outcome` or outcome text | `goal.desired_outcome` | Summary of the title |
| `constraints` | `goal.constraints[]` | Include "do not create accepted decisions" |
| `mode` | `mode` | `autopilot-draft` |
| `domain_pack` | `source_context.domain_pack_id` | `generic` or current session pack |
| target sessions | `source_context.included_session_ids[]` | `[]` |
| target objects | `source_context.included_object_ids[]` | `[]` |
| `max_draft_decisions` | Skill exploration budget | `20` |
| `risk_threshold` | Skill risk classification threshold | `medium` |

`create-draft-set` can fill top-level runtime fields, but the Skill payload must include a complete
`goal` object with `id`, `title`, `desired_outcome`, and `constraints`.

## Skill Orchestration Flow

1. Resolve `<repo-root>` and `<skill-root>`.
2. Use `<repo-root>/.ai/decide-me` as the target runtime directory.
3. Run `validate-state --cached`.
4. If validation passes, inspect available `project-state.json`, `runtime-index.json`, sessions, prior
   close summaries, source evidence, and Decision Stack Graph context relevant to the goal.
5. Normalize the goal input.
6. Generate draft decisions across Decision Stack layers.
7. Generate loose draft assumptions, risks, actions, and verifications when they clarify review.
8. Write a temporary `draft-set.input.json`.
9. Run `create-draft-set --generated-by skill`.
10. Run `export-draft-set --format markdown`.
11. Present the draft set ID, counts, review summary, export paths, and `DRAFT / NOT ACCEPTED` notice.

Required validation command:

```bash
python3 <skill-root>/scripts/decide_me.py validate-state \
  --ai-dir <repo-root>/.ai/decide-me \
  --cached
```

Required create command:

```bash
python3 <skill-root>/scripts/decide_me.py create-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-json <tmp>/draft-set.input.json \
  --generated-by skill
```

Required export command:

```bash
python3 <skill-root>/scripts/decide_me.py export-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN \
  --format markdown
```

`review-draft-set` is optional for `/goal` because `export-draft-set` also writes `review-queue.json`.

## Draft Generation Heuristics

Generate questions by Decision Stack layer:

| Layer | Question focus |
| --- | --- |
| `purpose` | What success means and what is intentionally out of scope |
| `principle` | Human decision, sidecar separation, event-log invariants |
| `constraint` | Source of truth, projections, Safety Gate, schema, artifact constraints |
| `strategy` | Skill orchestration versus deterministic runtime responsibility |
| `design` | JSON shape, CLI calls, review/export/promotion handoff |
| `execution` | File update order, tests, distribution artifact checks |
| `verification` | Schema validation, CLI round trips, reference presence |
| `review` | Review queue, bulk restrictions, stale handling |

Default budget:

| Priority | Limit |
| --- | ---: |
| P0 | 3 |
| P1 | 5 |
| P2 | 10 |
| P3 | 5 |

Keep the first draft set readable. Prefer fewer high-signal draft decisions over excessive
fragmentation.

Create loose annotations when they help review:

- `draft_assumptions`: unverified premises behind a recommendation
- `draft_risks`: ways the draft could be misread or over-applied
- `draft_actions`: PR work needed to make the proposal concrete
- `draft_verifications`: checks that prove the documentation or handoff works

## Draft Set Input Contract

The Skill may pass this minimal top-level shape to `create-draft-set`; normalization fills the remaining
top-level sidecar fields.

```json
{
  "goal": {
    "id": "G-20260513-001",
    "title": "Add /goal-based draft decision sets",
    "desired_outcome": "Expose a safe preflight flow that humans can review before promotion.",
    "constraints": [
      "Do not mutate canonical runtime during drafting",
      "Do not create accepted decisions",
      "Generate readable DRAFT / NOT ACCEPTED exports"
    ]
  },
  "draft_decisions": [
    {
      "id": "DD-001",
      "status": "recommended",
      "layer": "constraint",
      "priority": "P0",
      "frontier": "now",
      "kind": "choice",
      "question": "Should /goal be documented as Skill orchestration rather than a new CLI?",
      "recommendation": "Document /goal as Skill orchestration over create-draft-set and export-draft-set.",
      "rationale": "The runtime already has draft sidecars, readable export, and promotion; this PR fixes the safe operating contract.",
      "alternatives": [
        {
          "option": "Add a new generator CLI now.",
          "reason_not_recommended": "That would expand PR-4 beyond documentation and mix generation behavior with the safety contract."
        }
      ],
      "risk_tier": "medium",
      "reversibility": "reversible",
      "evidence_coverage": {
        "status": "partial",
        "supporting_object_ids": [],
        "source_unit_ids": [],
        "missing": [
          "Documentation regression test results"
        ]
      },
      "human_review": {
        "required": true,
        "mode": "individual",
        "bulk_promotable": false,
        "reason": "Public Skill command behavior affects the safety boundary."
      },
      "promotion_recipe": {
        "canonical_object_type": "decision",
        "canonical_initial_status": "unresolved",
        "proposal_required": true,
        "acceptance_mode_allowed": [
          "explicit"
        ],
        "blocked_for_bulk_acceptance": true
      }
    }
  ],
  "convergence": {
    "status": "budget_exhausted",
    "iterations": 1,
    "stop_reason": "mvp_single_pass",
    "note": "Single-pass /goal draft. It does not prove convergence."
  }
}
```

Each draft decision must include a non-empty recommendation, rationale, and at least one meaningful
alternative in Skill-generated payloads. Promotion-oriented decisions should use
`canonical_initial_status: "unresolved"` and `proposal_required: true`.

## Review Mode Rules

Use individual review when any of these are true:

- P0 or P1 priority
- medium, high, or critical risk
- evidence status is `none`, `challenged`, or `unknown`
- conflict is present
- alternatives are weak or incomplete
- the draft changes the public Skill safety contract

Use bulk review only when the draft is low risk, reversible, P2/P3, supported by partial or sufficient
evidence, conflict-free, and safe to place into proposal review without individual triage.

`bulk_promotable=true` never means accepted. It only means "eligible for
`promote-draft-set --only-bulk-promotable`."

## Review/export Contract

After `export-draft-set`, report at least:

```text
Draft set: DS-YYYYMMDD-NNN
Status: created/exported
Counts: draft_decisions=N, draft_assumptions=N, draft_risks=N, draft_actions=N, draft_verifications=N
Review summary: blocked=N, individual=N, bulk candidates=N
Exports:
- preflight.md
- draft-decisions.md
- review-queue.md
- assumptions-risks.md
Next recommended step: review P0/P1 individual items before promotion.

This is DRAFT / NOT ACCEPTED. No accepted decision was created.
```

Use concrete paths in the final response when available.

## Promotion Handoff

Promote only after an explicit user instruction names the draft set and draft decision, or explicitly
asks for low-risk bulk candidates.

Individual promotion:

```bash
python3 <skill-root>/scripts/decide_me.py promote-draft-decision \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN \
  --draft-decision-id DD-001 \
  --session-id S-...
```

Bulk promotion:

```bash
python3 <skill-root>/scripts/decide_me.py promote-draft-set \
  --ai-dir <repo-root>/.ai/decide-me \
  --draft-set-id DS-YYYYMMDD-NNN \
  --session-map-json <tmp>/session-map.json \
  --only-bulk-promotable
```

Bulk promotion is only for low-risk eligible drafts. High or critical risk, medium risk, P0/P1,
missing evidence, challenged evidence, conflicts, individual review, and stale draft sets must not be
bulk promoted.

Promotion creates canonical proposal review state, not acceptance. Draft-origin proposals commonly use
`acceptance_mode_allowed: ["explicit"]`, so plain `OK` is rejected when explicit acceptance is required.
Safety Gate approval remains mandatory when the normal gate requires it.

## Error Handling

| Situation | Skill behavior |
| --- | --- |
| `validate-state --cached` fails | Run `validate-state --full`, report the failing runtime state, and stop drafting |
| runtime is missing | Guide bootstrap, or propose bootstrap when the user provided enough initial context |
| draft JSON validation fails | Fix the generated JSON and retry once; do not expose a long raw schema error as the main user response |
| draft set ID collision | Let the CLI auto-number IDs; avoid explicit IDs in normal `/goal` use |
| unmarked Markdown exists at export path | Do not pass `--force` automatically; explain that existing human files are protected |
| stale project head | Report as an export warning; reject promotion unless the user explicitly allows stale single promotion |
| high or critical bulk request | Refuse bulk promotion and ask for individual review |

## Examples

Successful response shape:

```markdown
Draft set: `DS-20260513-001`
Status: `created/exported`
Counts: draft_decisions=12, draft_assumptions=2, draft_risks=3, draft_actions=4, draft_verifications=3
Review summary: blocked=1, individual=8, bulk candidates=3

Exports:
- `.ai/decide-me/draft-sets/DS-20260513-001/exports/preflight.md`
- `.ai/decide-me/draft-sets/DS-20260513-001/exports/draft-decisions.md`
- `.ai/decide-me/draft-sets/DS-20260513-001/exports/review-queue.md`
- `.ai/decide-me/draft-sets/DS-20260513-001/exports/assumptions-risks.md`

This is `DRAFT / NOT ACCEPTED`. No accepted decision was created.
Next recommended step: review the P0/P1 individual items before promotion.
```
