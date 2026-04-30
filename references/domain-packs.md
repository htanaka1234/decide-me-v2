# Domain Packs

Domain packs add declarative domain vocabulary and policy overlays without changing the domain-neutral object/link core.

For Phase 9, runtime objects and sessions store `domain_pack_id`, `domain_pack_version`, and `domain_pack_digest` together. Runtime validation and pack-aware evaluation compare those stored values with the currently loaded pack and fail fast on version or digest mismatch. Historical pack replay by digest is future work; until then, stale pack metadata is treated as a validation or evaluation error rather than silently reinterpreting past decisions with the current pack.

Document profiles are selected from the same pack metadata. A document export may specify
`--domain-pack`; otherwise the compiler uses the single pack represented by selected closed
sessions, or the `generic` profile for mixed scopes when the generic pack declares that document
type. If a single selected pack does not define a pack-specific document type and no generic profile
exists for that type, export fails instead of silently rendering an unprofiled document. The emitted
`DocumentModel.metadata` records the pack id, version, digest, and profile id when a profile is
applied. Phase 9 profiles currently control profile metadata and required-section ordering; richer
domain-specific document sections are future builder work.
