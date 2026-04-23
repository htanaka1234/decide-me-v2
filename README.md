# decide-me-v2

`decide-me-v2` is a destructive, event-sourced rewrite of the `decide-me` skill runtime.
It keeps the single public `decide-me` entrypoint, one-question-at-a-time interviewing,
parallel session continuity, taxonomy-aware search, and close-summary-to-plan handoff,
while replacing the old shared-register-centric runtime with an append-only event log and
rebuildable projections.

## Status

This repository contains the first v3 implementation skeleton and core runtime:

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

- This repo intentionally breaks compatibility with the legacy YAML runtime.
- The runtime remains under `.ai/decide-me/`; human-readable artifacts are exports, not state.
- Validation checks both event envelopes and projection consistency.
