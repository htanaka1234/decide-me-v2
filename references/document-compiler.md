# Document Compiler

Phase 8 adds a generic read-only document compiler. It turns the runtime event/projection state
into a semantic `DocumentModel`, then renders that model to local derived files.

Pipeline:

```text
events + projections + closed sessions + registers + diagnostics
  -> DocumentContext
  -> DocumentModel
  -> renderer
  -> derived export
```

Human-readable documents are never runtime source of truth. The event log and rebuildable
projections remain canonical.

## Commands

```bash
python3 scripts/decide_me.py export-document \
  --ai-dir .ai/decide-me \
  --type decision-brief \
  --format markdown \
  --output .ai/decide-me/exports/documents/decision-brief.md
```

Supported document types:

- `decision-brief`
- `action-plan`
- `risk-register`
- `review-memo`
- `research-plan`
- `comparison-table`

Supported formats:

- `markdown`
- `json`
- `csv` for `risk-register` and `comparison-table`

`--format json` writes the `DocumentModel` directly. `--now` fixes the generated timestamp and
diagnostic as-of time for deterministic tests and snapshots.

`--domain-pack <id>` applies the selected pack's document profile when that pack declares the
requested document type. If omitted, the compiler uses the single domain pack represented by the
selected closed sessions. If that pack does not define the document type, the compiler uses the
generic profile only when the generic pack declares that document type. Mixed-pack scopes use the
generic profile when available. Pack-specific documents without an applicable profile fail and
require an explicit compatible `--domain-pack`.

## Contract

All document models use `schemas/document-model.schema.json`.

Required top-level fields:

- `schema_version`
- `document_id`
- `document_type`
- `audience`
- `generated_at`
- `project_head`
- `source`
- `title`
- `sections`
- `warnings`
- `metadata`

When a domain pack profile is applied, `metadata` includes `domain_pack_id`,
`domain_pack_version`, `domain_pack_digest`, and `document_profile_id`. The compiler uses the
profile's `required_sections` to prioritize section order and fails clearly if a required section
is not produced by the selected document builder. Phase 9 profiles currently provide metadata and
required-section ordering; richer pack-specific sections and columns are added in the document
builders separately.

Document exports also evaluate embedded Safety Gate diagnostics with the domain registry loaded, so
domain pack required evidence and safety rules are reflected in document diagnostics when source
objects carry pack metadata.

`source` records `session_ids`, `object_ids`, `link_ids`, and `diagnostic_types` so every document
can be traced back to the object/link runtime. Sections also carry `source_object_ids` and
`source_link_ids`.

Blocks are intentionally small:

- `text`
- `list`
- `table`
- `callout`
- `object_refs`

## Read-only Boundary

The compiler may read:

- `project-state.json`
- `taxonomy-state.json`
- `sessions/*.json`
- `events/**/*.jsonl`
- derived read-only register, safety gate, and stale diagnostic functions

It must not emit runtime events, update projections, create approval artifacts, call external APIs,
or call `generate_plan()`. Action plan documents use `assemble_action_plan()` after unresolved
conflict checks.

## Managed Markdown Regions

Markdown exports default to a generated marker block:

```markdown
<!-- decide-me:generated:start document_type=decision-brief project_head=... -->
generated content
<!-- decide-me:generated:end -->

## Human Notes
```

Re-export replaces only the generated block and preserves text outside it. Existing unmarked
Markdown files require `--force`. Marker document type mismatches fail. Project head mismatches are
reported as warnings but do not block explicit export.
