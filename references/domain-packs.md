# Domain Packs

Domain packs add declarative domain vocabulary and policy overlays without changing the domain-neutral object/link core.

For Phase 9, runtime objects and sessions store `domain_pack_id`, `domain_pack_version`, and `domain_pack_digest` together. Runtime validation and pack-aware evaluation compare those stored values with the currently loaded pack and fail fast on version or digest mismatch. Historical pack replay by digest is future work; until then, stale pack metadata is treated as a validation or evaluation error rather than silently reinterpreting past decisions with the current pack.
