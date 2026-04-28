# Stale Detection Diagnostics

Step 4 adds structured read-only diagnostics for stale Phase 7 inputs. These diagnostics read
`project-state.json` and return JSON; they do not persist diagnostic state, change object status,
write events, apply invalidation candidates, or create approval objects. `project-state.json` and
its `schema_version` are unchanged.

## Commands

Inspect expired assumptions:

```bash
python3 scripts/decide_me.py show-stale-assumptions \
  --ai-dir .ai/decide-me \
  --now 2026-04-28T12:00:00Z
```

Inspect stale evidence:

```bash
python3 scripts/decide_me.py show-stale-evidence \
  --ai-dir .ai/decide-me \
  --now 2026-04-28T12:00:00Z
```

Inspect actions with no verification evidence:

```bash
python3 scripts/decide_me.py show-verification-gaps \
  --ai-dir .ai/decide-me \
  --now 2026-04-28T12:00:00Z
```

Inspect due revisit triggers:

```bash
python3 scripts/decide_me.py show-revisit-due \
  --ai-dir .ai/decide-me \
  --now 2026-04-28T12:00:00Z
```

`--now` is optional. When omitted, the runtime uses the current UTC timestamp. Tests and automated
consumers should pass `--now` for deterministic output.

## Output Contract

All stale diagnostics use `schemas/stale-diagnostics.schema.json`:

- `schema_version`: stale diagnostics schema version.
- `diagnostic_type`: `stale_assumptions`, `stale_evidence`, `verification_gaps`, or
  `revisit_due`.
- `project_head`: copied from `project_state.state.project_head`.
- `generated_at`: copied from `project_state.state.updated_at` for reproducible read-only output.
- `as_of`: the timestamp used for comparisons.
- `summary`: type-specific counts.
- `items`: deterministic diagnostic rows sorted by `object_id`.

## Rules

Stale assumptions:

- Live `assumption` objects are reported when `metadata.expires_at < as_of`.
- `expires_at: null` is not stale.
- Items include `invalidates_if_false`, related object ids, and related link ids.

Stale evidence:

- Live `evidence` objects are reported when `metadata.valid_until < as_of`.
- Live `evidence` objects are also reported when `metadata.freshness == "stale"`.
- `valid_until: null` is not stale unless freshness is explicitly `stale`.
- Items include affected object ids, affected decision ids, and related link ids for outgoing
  `supports`, `verifies`, and `challenges` links.
- `affected_decision_ids` includes indirect live decisions reached through verification,
  assumption, and proposal paths. `affected_decision_paths` records the representative node/link
  path used for each affected decision.

Verification gaps:

- Live `action` objects are reported when no live incoming `verification` or `evidence` object is
  linked with `verifies` or `supports`.
- Completed actions have `gap_severity: high`.
- Other live actions have `gap_severity: medium`.

Due revisit triggers:

- Live `revisit_trigger` objects are reported when `metadata.due_at < as_of`.
- `due_at: null` is not due.
- Items include `target_object_ids` and outgoing `revisits` link ids.

## Boundary

`show-verification-gaps` returns structured JSON from the runtime projection. The existing
`export-verification-gaps` command remains a derived Markdown export and writes under the requested
export path. Stale diagnostics do not alter Step 3 safety gate status computation; later phases may
consume these JSON diagnostics as gate inputs.
