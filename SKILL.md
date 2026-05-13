---
name: decide-me
description: Interview the user about a plan or design in a structured, low-friction way until shared understanding is sufficient for the current milestone, preserve continuity across sequential and parallel sessions, maintain a taxonomy-aware object/link runtime, and generate object-native plans for follow-through.
---

Help me reach shared understanding on this project with minimal user fatigue.

Use this skill as the only public entrypoint. Keep the startup surface lean and load the
bundled references only when they are needed for the current turn.

Startup checklist:

1. Load the derived projections and `.ai/decide-me/runtime-index.json` when they exist. Use full
   event-log replay only for `validate-state`, `validate-state --full`, conflict detection,
   `compact-runtime`, or `rebuild-projections`.
2. Resolve the bundled CLI path from this Skill package; do not assume the target repository
   contains `scripts/decide_me.py`. If the runtime is missing, bootstrap it with
   `python3 <skill-root>/scripts/decide_me.py bootstrap --ai-dir <repo-root>/.ai/decide-me ...`,
   or tell the user to run the equivalent command. For session advancement and replies, pass
   `--repo-root <repo-root>` when the Skill package is not located at the target repository root.
   Use `--ai-dir <repo-root>/.ai/decide-me` for every CLI command that operates on the target
   runtime; do not rely on `.ai/decide-me` relative to the current working directory.
3. Validate event and projection consistency before trusting the current state.
   If validation reports an unresolved same-session merge conflict, run
   `python3 <skill-root>/scripts/decide_me.py detect-merge-conflicts --ai-dir <repo-root>/.ai/decide-me`
   and ask the user which candidate transaction to keep from the selected option's
   `surviving_tx_ids` before resolving it.
   If plan generation reports semantic conflicts across related sessions, inspect
   `show-session-graph` and use `detect-session-conflicts --include-related` before asking the
   user which session's scoped answer should win.
4. When the user starts with `/goal`, run the goal-autopilot-drafting flow instead of the normal
   one-question interview. Treat `/goal` as Skill orchestration: generate a structured draft-set
   input, pass it to `autopilot-draft --seed-draft-json` when deterministic gap iteration is useful,
   or use `create-draft-set`, `project-draft-set`, and `export-draft-set` explicitly when needed.
   Present the draft projection plus review queue. Do not create accepted decisions and do not call
   promotion commands from `/goal`.
5. Create a session when the user starts a new decision thread; resume an existing one only when
   the user explicitly asks or the runtime already identifies the current session.
6. Before asking a question, scan the codebase, docs, tests, existing sessions, and prior
   object/link close summaries for evidence that already resolves the decision.
7. Ask exactly one question at a time, and always include `Decision:`, `Proposal:`,
   `Question:`, `Recommendation:`, `Why:`, and `If not:`.
8. Treat plain `OK` as acceptance only when the same session still has a valid active proposal.
   If the proposal is stale or ambiguous, require `Accept P-...`.
9. When closing a session, generate a schema-shaped close summary whose runtime payload is
   `close_summary.object_ids` and `close_summary.link_ids`; do not ask a new question in the same
   response.

Read only the reference file needed for the turn:

- [references/protocol-overview.md](references/protocol-overview.md)
- [references/interview-engine.md](references/interview-engine.md)
- [references/session-lifecycle.md](references/session-lifecycle.md)
- [references/search-and-taxonomy.md](references/search-and-taxonomy.md)
- [references/domain-neutral-core.md](references/domain-neutral-core.md)
- [references/object-model.md](references/object-model.md)
- [references/link-relations.md](references/link-relations.md)
- [references/decision-stack-graph.md](references/decision-stack-graph.md)
- [references/impact-analysis.md](references/impact-analysis.md)
- [references/invalidation-candidates.md](references/invalidation-candidates.md)
- [references/event-and-projection-model.md](references/event-and-projection-model.md)
- [references/plan-generation.md](references/plan-generation.md)
- [references/output-contract.md](references/output-contract.md)
- [references/document-compiler.md](references/document-compiler.md)
- [references/draft-decision-sets.md](references/draft-decision-sets.md)
- [references/goal-autopilot-drafting.md](references/goal-autopilot-drafting.md)
- [references/domain-packs.md](references/domain-packs.md)
- [references/evidence-source-store.md](references/evidence-source-store.md)
- [references/examples.md](references/examples.md)

Bundled assets:

- deterministic CLI: `python3 <skill-root>/scripts/decide_me.py ...`
- JSON contracts: `schemas/*.json`
- export templates: `templates/`
- runtime requirements: `requirements.txt` (`PyYAML` is required for declarative Domain Pack YAML)

User-facing commands:

- `List sessions`
- `Show session S-...`
- `Resume session S-...`
- `Close session S-...`
- `Generate plan from sessions S-..., S-...`
- `Detect merge conflicts`
- `Resolve merge conflict by keeping tx T-... and rejecting tx T-...`
- `Link session S-child to parent S-parent`
- `Show session graph`
- `Detect session conflicts`
- `Resolve session conflict by choosing session S-...`
- `Resolve decision supersession by choosing decision D-... over D-...`
- `Show impact for object O-...`
- `Show invalidation candidates for object O-...`
- `Show decision stack around object O-...`
- `Classify session S-...`
- `List domain packs`
- `Show domain pack research`
- `Advance session S-...`
- `Handle reply for session S-...`
- `Export impact report for object O-...`
- `/goal`
- `Create draft decision set from goal`
- `List draft sets`
- `Show draft set DS-...`
- `Project draft set DS-...`
- `Autopilot draft from seed JSON or goal`
- `Review draft set DS-...`
- `Export draft set DS-...`
- `Promote draft decision DD-... from draft set DS-...`
- `Promote low-risk bulk draft candidates from draft set DS-...`
- `Export GitHub issue templates`
- `Export GitHub issue drafts from sessions S-..., S-...`
- `Export agent instructions for AGENTS.md, Cursor, Claude, or Codex`
- `Export architecture doc as arc42`
- `Export traceability matrix as CSV or Markdown`
- `Export verification gaps`
- `Export document as Markdown, JSON, or CSV`
- `Export document with domain pack research`
- `Import source document`
- `Decompose source document`
- `Search evidence`
- `Link evidence to decision`
- `List sources`
- `Show source`
- `Show source unit`
- `Show source impact`
- `Rebuild evidence index`
- `Validate sources`

Runtime invariants:

- `.ai/decide-me/events/**/*.jsonl` transaction files are the source of truth.
- `.ai/decide-me/sources/` stores immutable source snapshots, document metadata, and citation
  units. Source-store files are side-store data; the event log records imports, decomposition,
  version updates, and evidence links without storing full source text. Import/decomposition writes
  are protected by the runtime write lock and rolled back if the matching audit transaction cannot
  be persisted.
- `project-state.json` is the derived object/link projection. It contains project metadata,
  projection metadata, protocol settings, session index data, counts, `objects`, `links`, and the
  derived Decision Stack Graph.
- Close summaries store reference sets in `close_summary.object_ids` and
  `close_summary.link_ids`. Human-readable close text is display output only.
- Plan output uses `action_plan.actions` and `action_plan.implementation_ready_actions`; action
  objects are the executable WorkUnit equivalent.
- Legacy `.ai/decide-me/event-log.jsonl` runtimes are not migrated automatically; rebootstrap
  or recreate them from exports produced by the previous runtime before using this version.
- `transaction_rejected` events record user-selected transaction rejection; rejected transaction
  files remain on disk for audit and are ignored only in the effective projection stream.
- The runtime accepts only the domain-neutral event whitelist:
  `project_initialized`, `session_created`, `session_resumed`, `session_closed`,
  `close_summary_generated`, `plan_generated`, `taxonomy_extended`,
  `source_document_imported`, `normative_units_extracted`, `source_version_updated`,
  `evidence_linked_to_object`,
  `transaction_rejected`, `object_recorded`, `object_updated`,
  `object_status_changed`, `object_linked`, `object_unlinked`,
  `session_question_asked`, and `session_answer_recorded`.
- `object_updated` may patch only `title`, `body`, and `metadata`; status changes must use
  `object_status_changed` with `from_status`, `to_status`, `reason`, and `changed_at`.
- `session_answer_recorded.payload.answer` is an object with `summary`, `answered_at`, and
  `answered_via`.
- Deleted decision/proposal/session-graph compatibility event names are invalid; do not emit
  migration, backfill, or compatibility events.
- `project-state.json`, `taxonomy-state.json`, and `sessions/*.json` are rebuildable projections
  and the normal hot-path read cache.
- `runtime-index.json` checkpoints projection freshness; refresh it with `compact-runtime` only
  after it verifies projections against the event log, or regenerate it with `rebuild-projections`.
- Decision Stack Graph impact analysis, invalidation candidate generation, bounded stack graph
  views, and impact report exports are read-only diagnostics. They must not emit events or change
  object status. Materialized invalidation candidates may be applied only through the explicit
  `apply-invalidation-candidate --approve` workflow, which must regenerate the candidate and pass
  Safety Gate checks before writing events. High severity candidates require a safety approval
  artifact, created with `approve-safety-gate --candidate-apply-approval` when the target gate does
  not otherwise require approval; critical severity candidates require external review or remain
  blocked.
- Human-readable plan, generic document, impact report, ADR, structured ADR, decision register,
  GitHub issue draft, agent instruction, arc42 architecture, traceability matrix, and verification gap files are derived
  exports, not runtime state. Software-oriented exports are allowed, but they must be derived from
  the domain-neutral object/link core.
- `/goal` is a Skill-only orchestration flow. It may create a sidecar draft set, run deterministic
  `autopilot-draft` gap iteration, and write readable exports, but it must not emit canonical events.
  Canonical events are written only by explicit promotion commands.
- `.ai/decide-me/draft-sets/DS-.../draft-set.json` is a draft sidecar, not canonical event-log
  state. `project-draft-set` may write only `draft-projection.json`; `review-draft-set` may write
  only the derived `.ai/decide-me/draft-sets/DS-.../review-queue.json`; `export-draft-set` may write
  that JSON and the four Markdown draft exports under `exports/`. These outputs must state
  `DRAFT / NOT ACCEPTED`, must not create accepted decisions or proposals, and must not update events,
  `project-state.json`, `taxonomy-state.json`, or `sessions/*.json`.
- `promote-draft-decision` is the only draft-set command that materializes canonical runtime
  objects. It must create a normal `decision` plus active `proposal` and `session_question_asked`
  using existing event types, preserve `decision.metadata.draft_origin`, create a canonical risk
  scaffold for `medium`/`high`/`critical` draft risk, append the sidecar `promotion-log.jsonl`, and
  leave acceptance to the normal proposal acceptance and safety gate flow. It must not create an
  accepted decision directly.
- Source evidence uses normal `evidence` objects with `metadata.source = "source-store"` and
  object links such as `supports`, `challenges`, `verifies`, or `constrains`. The evidence object
  represents the source unit; per-decision quote and interpretation note live on link metadata and
  are surfaced by evidence registers and decision briefs. Runtime validation checks that source-store
  links and `evidence_linked_to_object` audit payloads exist together in the same transaction and
  agree on concrete link metadata. Replacement imports mark the previous source as non-canonical
  with `superseded_by`; default evidence search excludes those superseded snapshots unless the user
  passes `--include-superseded` or a specific `--source-id`. Source updates and orphaned linked units
  are read-only impact diagnostics until a human applies the normal revisit, approval, or
  invalidation workflow.
- Domain packs are declarative policy overlays. Session and object pack metadata must keep
  `domain_pack_id`, `domain_pack_version`, and `domain_pack_digest` together; stale digest or
  version mismatches fail validation or pack-aware evaluation instead of silently falling back.
  YAML pack loading uses the bundled runtime dependency declaration in `requirements.txt`.
- Free-form answers apply only to the current active proposal in the current session.
