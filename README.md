# decide-me-v2

`decide-me-v2` is an event-sourced decision runtime for structured interviewing,
parallel session continuity, taxonomy-aware search, and close-summary-to-plan handoff.
It uses a source-of-truth event log and rebuildable projections as the runtime model.

## Status

This repository contains the v2 implementation skeleton and core runtime:

- skill authoring entrypoint in `SKILL.md`
- protocol and architecture references in `references/`
- JSON schema contracts in `schemas/`
- markdown export templates in `templates/`
- runtime and CLI implementation in `decide_me/` and `scripts/`
- unit and integration tests in `tests/`

## Runtime layout

The runtime lives under `.ai/decide-me/`:

```text
.ai/decide-me/
├── event-log.jsonl
├── project-state.json
├── taxonomy-state.json
├── sessions/
│   └── S-*.json
├── exports/
│   ├── adr/
│   └── plans/
└── write.lock
```

`event-log.jsonl` is the source of truth. The JSON projections are derived state and can be
rebuilt from the event log.

## Prerequisites

- Python 3.11 or newer
- No third-party Python dependencies are required for the included test suite

## Quick start

Bootstrap a runtime:

```bash
python3 scripts/decide_me.py bootstrap \
  --ai-dir .ai/decide-me \
  --project-name "Example Project" \
  --objective "Turn discovery into an implementation-ready action plan" \
  --current-milestone "MVP planning"
```

Create and inspect sessions:

```bash
python3 scripts/decide_me.py create-session --ai-dir .ai/decide-me --context "MVP scope"
python3 scripts/decide_me.py list-sessions --ai-dir .ai/decide-me
python3 scripts/decide_me.py show-session --ai-dir .ai/decide-me --session-id S-...
```

Classify a session and search with filters:

```bash
python3 scripts/decide_me.py classify-session \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --domain technical \
  --abstraction-level architecture \
  --candidate-term "auth" \
  --candidate-term "magic links" \
  --source-ref latest_summary

python3 scripts/decide_me.py list-sessions \
  --ai-dir .ai/decide-me \
  --domain technical \
  --abstraction-level architecture \
  --tag auth
```

Validate and rebuild projections:

```bash
python3 scripts/decide_me.py validate-state --ai-dir .ai/decide-me
python3 scripts/decide_me.py rebuild-projections --ai-dir .ai/decide-me
```

Close sessions and generate a plan:

```bash
python3 scripts/decide_me.py close-session --ai-dir .ai/decide-me --session-id S-...
python3 scripts/decide_me.py generate-plan \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --session-id S-...

python3 scripts/decide_me.py invalidate-decision \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --decision-id D-... \
  --invalidated-by D-... \
  --reason "Superseded by the later decision."
```

Advance an interview turn:

```bash
python3 scripts/decide_me.py advance-session \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --repo-root .

python3 scripts/decide_me.py handle-reply \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --reply "OK" \
  --repo-root .

python3 scripts/decide_me.py handle-reply \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --reply "Use 90 days because enterprise customers will expect it." \
  --repo-root .
```

## Project structure

- `SKILL.md`: public skill entrypoint
- `references/`: protocol, lifecycle, taxonomy, event model, plan generation, examples
- `schemas/`: JSON schema contracts for events and projections
- `templates/`: ADR and action-plan markdown templates
- `decide_me/`: runtime implementation
- `scripts/decide_me.py`: single subcommand CLI
- `tests/`: unit and integration coverage

## Notes

- The runtime lives under `.ai/decide-me/`; human-readable artifacts are exports, not state.
- Validation checks both event envelopes and projection consistency.
- `list-sessions` and `show-session` may lazily backfill closed-session compatibility tags and
  persist those additions as events.
- `advance-session` resolves evidence conservatively. It only auto-resolves decisions when a
  recommendation is already recorded and matching evidence is found.
- `advance-session` is session-scoped. A new empty session does not claim open decisions from
  other sessions; discover a decision in that session or resume the owning session.
- `handle-reply` supports command-style replies and free-form answers against the active proposal.
- Free-form replies can also capture additional constraints on the accepted decision and discover
  follow-up decisions in the same session.
- Discovered follow-up decisions infer `domain`, `kind`, `priority`, `resolvable_by`,
  `reversibility`, and a source-aware question from the reply clause.
- Newly discovered `codebase` / `docs` / `tests` decisions are scanned for evidence immediately
  after `handle-reply`, so they can self-resolve before the next question is issued.
- Close summaries now emit richer `candidate_action_slices`, and generated plans surface
  evidence-backed implementation-ready slices separately from the broader action list.
- Decisions can be invalidated explicitly by later accepted decisions. Invalidated decisions remain
  in `event-log.jsonl` but are hidden from normal session, interview, close-summary, plan, and ADR
  output.
