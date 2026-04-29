# Project Instructions

## Project Purpose

- This repository maintains the `decide-me` Codex Skill.
- The Skill turns ambiguous project work into decision-complete action plans by interviewing
  the user one decision at a time, inspecting available evidence before asking, recording
  domain objects and links, and generating close summaries or plans when the current milestone is
  clear.
- The core product values are low user fatigue, explicit recommendations, stateful continuity
  across sessions, taxonomy-aware reuse of prior decisions, and deterministic runtime behavior.
- There is intentionally no separate `plan.md` project specification. Do not recreate one as a
  source of truth; keep durable project guidance in this file, `README.md`, `SKILL.md`, and the
  files under `references/`.

## Development Policy

- This project is still in early development. Keeping the codebase clean is higher priority than
  preserving backward compatibility for older runtime state or intermediate APIs.
- Prefer direct schema, event, and projection contract changes over compatibility layers when the
  new model is simpler. Remove temporary migration commands and legacy paths unless a maintainer
  explicitly requires them for a release.
- When a contract changes, update runtime code, schemas, docs, and tests together so invalid old
  state fails clearly instead of being silently adapted.

## Source Of Truth

- `SKILL.md` is the public Skill entrypoint and should remain lean.
- `references/*.md` contains the detailed protocol, lifecycle, search, event, planning, output,
  and example guidance loaded by the Skill only when relevant.
- `schemas/*.json` defines the runtime contracts for events, projections, close summaries,
  plans, and indexes.
- `templates/*.md` defines human-readable export shapes.
- `decide_me/` contains the Python runtime implementation.
- `scripts/decide_me.py` is the deterministic CLI used by the Skill, tests, and maintainers.
- `scripts/build_artifact.py` is the only supported way to rebuild the installable artifact.
- `README.md` is the human-facing overview and maintainer quickstart.

## Runtime Model

- Runtime state lives under `.ai/decide-me/` when the Skill is used in a target project.
- `.ai/decide-me/events/**/*.jsonl` transaction files are the runtime source of truth.
- `project-state.json` is the derived objects/links projection and must be rebuildable from
  events.
- `taxonomy-state.json`, `runtime-index.json`, `session-graph-cache.json`, and `sessions/*.json`
  are derived projections or caches and must be rebuildable from events.
- Human-readable files under `.ai/decide-me/exports/` are exports, not runtime state.
- `write.lock` protects runtime writes.
- Rejected transaction files remain on disk for audit; rejection and suppression are represented
  by control events rather than deletion.
- Legacy `.ai/decide-me/event-log.jsonl` runtimes are not migrated automatically by this version.

## Domain-neutral Core Invariants

- Runtime domain state is represented as objects and links. Do not reintroduce top-level
  decision-centric projections or compatibility projections in `project-state.json`.
- Close summaries are object/link reference sets. Their public contract is
  `close_summary.object_ids` plus `close_summary.link_ids`.
- Plan output uses `action_plan.actions` and `action_plan.implementation_ready_actions`.
- ADR, GitHub issue, arc42, traceability, verification gap, agent instruction, and
  software-oriented decision-register files are derived exports only.
- Do not add backward compatibility layers for old runtime state unless a maintainer explicitly
  starts a separate migration release.

## Skill Behavior Invariants

- Before asking the user, inspect the codebase, docs, tests, existing sessions, and prior close
  summaries for evidence that already resolves the decision.
- Ask exactly one question at a time.
- User-facing decision prompts must include `Decision:`, `Proposal:`, `Question:`,
  `Recommendation:`, `Why:`, and `If not:`.
- Plain `OK` accepts only the current valid active proposal in the same session. Use explicit
  `Accept P-...` when there is any ambiguity or staleness.
- Closing a session generates a schema-shaped object/link close summary and must not ask a new
  question in the same response.
- Plan generation should consume closed sessions and surface unresolved conflicts rather than
  silently choosing between incompatible accepted decisions.

## CLI And Maintainer Commands

- Use Python 3.11 or newer. The runtime has no third-party Python dependency requirement.
- Run the full test suite with `PYTHONPATH=. python3 -m unittest discover -v`.
- Use `python3 scripts/decide_me.py --help` for the command reference.
- Common runtime commands include `bootstrap`, `create-session`, `list-sessions`,
  `show-session`, `resume-session`, `advance-session`, `handle-reply`, `close-session`,
  `generate-plan`, `validate-state`, `rebuild-projections`, `compact-runtime`,
  `detect-merge-conflicts`, `resolve-merge-conflict`, `link-session`,
  `detect-session-conflicts`, `resolve-session-conflict`, and
  `resolve-decision-supersession`, plus derived export commands such as
  `export-agent-instructions`.
- Do not patch generated runtime projections by hand during development. Fix the source events,
  runtime code, schemas, or projection logic, then rebuild or validate through the CLI.

## Repository Layout

- `agents/openai.yaml`: Codex Skill metadata.
- `decide_me/`: runtime modules for events, projections, lifecycle, interview flow, taxonomy,
  search, conflict handling, planning, exports, and validation.
- `references/`: detailed Skill operating references.
- `schemas/`: JSON Schema contracts.
- `scripts/`: CLI and artifact builder.
- `templates/`: plan and ADR export templates.
- `tests/unit/`: focused unit coverage.
- `tests/integration/`: end-to-end runtime flow coverage.
- `.ai/`: local decide-me runtime data used while developing this repository; track only event
  logs and markdown exports according to `.gitignore`.
- `dist/`: generated installable artifact output.

## Distribution Artifact

- Rebuild the distribution artifact with `python3 scripts/build_artifact.py` after any project
  update that changes the Skill, runtime code, references, schemas, templates, bundled agent
  metadata, packaging metadata, or packaging rules.
- When rebuilding the distribution artifact, also write a companion diff file under `dist/`
  for the source changes being packaged. For branch-based work, prefer
  `git diff origin/main...HEAD --output=dist/<topic>.diff`; for uncommitted local work,
  generate the equivalent staged or working-tree diff and state the base used.
- Treat files under `dist/` as generated output. Do not edit them by hand; update source files
  and rebuild the artifact instead.
- The distribution artifact must contain only the installable Skill package rooted at
  `decide-me/`.
- Include only files and directories selected by `scripts/build_artifact.py`: `SKILL.md`,
  `agents/openai.yaml`, `scripts/decide_me.py`, `templates/`, `decide_me/`, `references/`, and
  `schemas/`.
- Exclude development-only files such as `AGENTS.md`, `README.md`, `tests/`, `.git*`, `.ai/`,
  `.codex`, caches, and previous build output.
