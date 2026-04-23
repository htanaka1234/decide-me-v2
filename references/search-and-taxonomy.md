# Search And Taxonomy

Taxonomy state is additive and shared across sessions.

Required axes:

- `domain`
- `abstraction_level`

Each node stores:

- `id`
- `axis`
- `label`
- `aliases`
- `parent_id`
- `replaced_by`
- `status`
- `created_at`
- `updated_at`

Search semantics:

- query matches labels, aliases, session summaries, and search terms
- tag filters expand by descendant closure
- replaced nodes remain searchable through the replacement chain
- closed sessions keep assigned tags frozen and may add compatibility tags lazily
- deterministic classification may extend the taxonomy and update a session index in the same write
