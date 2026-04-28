# Domain Neutral Core

Phase 5 replaces projection-specific domain records with a domain-neutral object/link runtime.
Phase 6-1 adds a Decision Stack Graph projection over that runtime.

Core invariants:

- `.ai/decide-me/events/**/*.jsonl` transaction files remain the only runtime source of truth.
- Projections are rebuildable views over the effective event stream.
- Human-readable Markdown, ADRs, plans, reports, and other exports are never canonical state.
- Domain concepts are represented as first-class objects, not embedded fields on decisions.
- Relationships between objects are represented only as links.
- `project_state.graph` is a derived Decision Stack Graph projection over objects and links, not
  canonical state.
- Legacy top-level decision, proposal, and embedded action-list projections are removed in Phase 5.
- Phase 5 is intentionally breaking. Do not add compatibility adapters for legacy projection
  shapes unless a maintainer explicitly starts a separate migration release.

The object graph is meant to support planning and design work beyond decision registers. A project
can contain objectives, constraints, criteria, proposals, risks, actions, verification needs, and
artifacts without forcing every item to be a property of a decision.

Projection contract:

- `project-state.json` contains project metadata, projection state metadata, protocol settings,
  a lightweight `sessions_index`, derived counts, `objects`, `links`, and the Decision Stack
  `graph`.
- Object and link ids must be stable across projection rebuilds for the same effective event
  stream.
- Counts are derived from `objects` and `links`; they are validation aids, not source data.
- Graph nodes and edges are derived from `objects` and `links`; they are validation aids and
  query surfaces, not source data.
- Projection writers must reject invalid events instead of silently adapting legacy state.

Runtime contract:

- Events create, update, supersede, and connect objects.
- A projection rebuild from the same effective event stream must produce the same object graph.
- Rejected transactions remain in the event directory for audit, but their domain events do not
  contribute objects or links to normal projections.
