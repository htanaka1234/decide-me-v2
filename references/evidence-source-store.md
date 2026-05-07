# Evidence Source Store

Phase 12 adds a source/evidence store for authoritative documents such as laws, regulations,
academic rules, policy manuals, and institutional procedures.

The rule is deliberately conservative: do not convert full source documents into decision events
or bulk-copy source text into `project-state.json`. Source text lives under
`.ai/decide-me/sources/`; the object/link runtime records only compact audit events and normal
evidence objects/links that cite source units.

## Runtime Layout

Source-store files:

- `.ai/decide-me/sources/registry.yaml`
- `.ai/decide-me/sources/documents/<source_id>/metadata.yaml`
- `.ai/decide-me/sources/documents/<source_id>/original.<ext>`
- `.ai/decide-me/sources/documents/<source_id>/text.txt`
- `.ai/decide-me/sources/documents/<source_id>/units.jsonl`
- `.ai/decide-me/index/source_units.sqlite`

The source registry, document metadata, units, and SQLite search index are rebuildable side-store
files. The transaction event log remains the runtime audit trail.

## Source And Unit Contracts

`SourceDocument` metadata captures title, authority, document type, source URI, version label,
effective dates, retrieval time, content hash, format, canonical flag, and relative snapshot paths.

`NormativeUnit` records a citation-sized unit with:

- snapshot-local immutable `id`
- `source_document_id`
- structural `path`
- human `citation`
- cross-version `canonical_locator` / lineage key such as
  `academic_regulation:医学部教務規則:第12条:2`
- exact and normalized unit text
- unit content hash
- anchors such as page or XPath when known
- effective dates

IDs and locators:

- source document: `SRC-<12hex sha256(document_type,title,version_label,content_hash)>`
- source unit: `NU-<source_id>-<path_slug>-<8hex content_hash>`
- linked evidence object: `O-evidence-<source_unit_id>`
- `source_unit.id` is immutable within a source snapshot. Use `canonical_locator` to compare the
  same article or paragraph across source versions.

## Commands

Import a source snapshot:

```bash
python3 scripts/decide_me.py import-source \
  --ai-dir .ai/decide-me \
  --type academic_regulation \
  --title "医学部教務規則" \
  --file ./rules.xml \
  --effective-from 2026-04-01
```

When importing a known replacement version, add `--previous-source-id SRC-...` so update impact can
include links that still point at the previous snapshot.

Decompose into citation units:

```bash
python3 scripts/decide_me.py decompose-source \
  --ai-dir .ai/decide-me \
  --source-id SRC-... \
  --strategy auto
```

Search and link evidence:

```bash
python3 scripts/decide_me.py search-evidence \
  --ai-dir .ai/decide-me \
  --query "履修登録 締切"

python3 scripts/decide_me.py link-evidence \
  --ai-dir .ai/decide-me \
  --session-id S-... \
  --decision-id D-... \
  --source-unit-id NU-... \
  --relevance supports \
  --quote "学生は指定期間内に履修登録を行う。" \
  --interpretation-note "履修登録期限を制約として扱う"
```

Inspection and derived maintenance:

- `list-sources`
- `show-source --source-id SRC-...`
- `show-source-unit --source-unit-id NU-...`
- `show-source-impact --source-id SRC-... [--include-previous-version-links]`
- `rebuild-evidence-index`
- `validate-sources`

## Event Contract

Source audit event payloads store IDs, hashes, timestamps, methods, counts, and quality flags.
They must not store full source text.

SYSTEM-scoped source events:

- `source_document_imported`
- `normative_units_extracted`
- `source_version_updated`

Session-scoped evidence audit event:

- `evidence_linked_to_object`

Linking a source unit records normal object/link events as well:

- an `evidence` object with `metadata.source = "source-store"`
- a relation link such as `supports`, `challenges`, `verifies`, or `constrains`

The evidence object represents the source unit itself and may carry `source_document_id`,
`source_unit_id`, `source_unit_hash`, `citation`, `effective_from`, and `effective_to`.
Per-decision usage belongs on the link metadata: `quote`, `interpretation_note`, `relevance`,
`linked_at`, and the same source-unit IDs/hashes needed for audit. The CLI validates that any
provided quote appears in the source unit text after whitespace and Unicode normalization.

Source import and decomposition run under the runtime write lock. Source-store file updates are
written only after the corresponding event payloads validate, and they are rolled back if the audit
transaction cannot be persisted.

## Decomposition Scope

Phase 12 supports XML, HTML, Markdown, and text-first workflows.

- `egov-law-xml` uses Python stdlib XML parsing for article, paragraph, item, subitem, and appendix
  table style units.
  Parent XML units currently include descendant text; `normative_units_extracted.quality_flags`
  includes `parent_units_include_descendant_text` so consumers know that article-level hits may be
  broader than the citation-grade child unit.
- `japanese-regulation-text` handles common Japanese rule headings such as `第1章`, `第1条`, line
  paragraph numbers, `一`, `イ`, and `別表第1`.
- HTML is converted to text with stdlib parsing before text decomposition.
- PDF import stores the immutable snapshot only. PDF decomposition and OCR are explicitly
  unsupported in the Phase 12 MVP.

Japanese law support should prefer official e-Gov law XML and article XML where available:

- https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/
- https://laws.e-gov.go.jp/docs/law-data-basic/419a603-xml-schema-for-japanese-law/
- https://laws.e-gov.go.jp/docs/law-data-basic/8ebd8bc-law-structure-and-xml/

## Safety Boundary

This phase creates citation-grade evidence, not legal or institutional interpretation.

Do not automatically promote source units into hard constraints, invalidate decisions, create
revisit triggers, or apply source changes to decisions. Use `show-source-impact` to inspect direct
affected objects and downstream affected decisions. When a new source version is imported, pass
`--previous-source-id` to make the lineage explicit; then use
`show-source-impact --include-previous-version-links` on the new source to find decisions still
linked to the previous version.
