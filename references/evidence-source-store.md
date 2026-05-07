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

- stable `id`
- `source_document_id`
- structural `path`
- human `citation`
- exact and normalized unit text
- unit content hash
- anchors such as page or XPath when known
- effective dates

Stable IDs:

- source document: `SRC-<12hex sha256(document_type,title,version_label,content_hash)>`
- source unit: `NU-<source_id>-<path_slug>-<8hex content_hash>`
- linked evidence object: `O-evidence-<source_unit_id>`

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
  --relevance supports
```

Inspection and derived maintenance:

- `list-sources`
- `show-source --source-id SRC-...`
- `show-source-unit --source-unit-id NU-...`
- `show-source-impact --source-id SRC-...`
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

The evidence metadata may carry `source_document_id`, `source_unit_id`, `source_unit_hash`,
`citation`, `quote`, `interpretation_note`, `effective_from`, and `effective_to`.

## Decomposition Scope

Phase 12 supports XML, HTML, Markdown, and text-first workflows.

- `egov-law-xml` uses Python stdlib XML parsing for article, paragraph, item, subitem, and appendix
  table style units.
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

Do not automatically promote source units into hard constraints, invalidate decisions, or apply
source changes to decisions. Use `show-source-impact` to inspect linked decisions and then run the
normal decide-me interview, safety gate, approval, or invalidation workflow when human review is
needed.
