# Domain Packs

Domain packs add declarative domain vocabulary and policy overlays without changing the domain-neutral object/link core.

They are YAML or JSON data, not executable plugins. A pack declares domain-specific decision
types, criteria, evidence requirements, risks, safety rules, document profiles, aliases, and
interview hints. Packs also declare `action_types`, the action taxonomy used when an action is
treated as the executable WorkUnit equivalent. The core runtime still stores
domain-neutral objects and links; pack semantics are attached through metadata such as
`domain_pack_id`, `domain_pack_version`, `domain_pack_digest`, and `domain_decision_type`.

## Built-in packs

The distribution includes seven built-in packs:

- `generic`: fallback policy for unresolved or legacy sessions. It is intentionally weak and does
  not add safety requirements.
- `software`: compatibility pack for software planning, architecture, API/auth, data model, UX,
  deployment, compliance, and verification decisions.
- `research`: research planning pack for research questions, study design, cohorts, endpoints,
  missing data strategy, sensitivity analysis, reproducibility, and publication planning.
- `procurement`: procurement pack for requirements, budget limits, candidate selection,
  evaluation criteria, comparison, vendor risk, contract/security review, final selection, and
  implementation planning.
- `operations`: operations pack for process definition, bottleneck identification, controls,
  escalation, monitoring, and improvement planning.
- `personal_planning`: personal planning pack for career, household, learning, scheduling,
  prioritization, resource allocation, and review planning.
- `writing`: writing pack for audience, purpose, scope, outline, evidence, review, and
  publication planning.

User-defined packs may be placed under `.ai/decide-me/domain-packs/` as `.yaml`, `.yml`, or
`.json`. YAML loading uses the runtime dependency declared in `requirements.txt` (`PyYAML>=6.0`).
They must pass the same strict contract as built-ins. Duplicate pack IDs are rejected.

Existing user-defined packs created before the Action-as-WorkUnit contract update must
add `action_types`. A minimal compatible value is:

```yaml
action_types:
  - research
  - analysis
  - writing
  - communication
  - execution
  - review
  - verification
  - monitoring
  - decision
```

## CLI surface

Use these commands to inspect and apply packs:

```bash
python3 scripts/decide_me.py list-domain-packs --ai-dir .ai/decide-me

python3 scripts/decide_me.py show-domain-pack \
  --ai-dir .ai/decide-me \
  --pack-id research

python3 scripts/decide_me.py create-session \
  --ai-dir .ai/decide-me \
  --context "Plan a retrospective cohort study" \
  --domain-pack research

python3 scripts/decide_me.py list-sessions \
  --ai-dir .ai/decide-me \
  --domain-pack research

python3 scripts/decide_me.py export-document \
  --ai-dir .ai/decide-me \
  --type research-plan \
  --domain-pack research \
  --format markdown \
  --output .ai/decide-me/exports/documents/research-plan.md
```

If `create-session --domain-pack` is omitted, the runtime infers a specialized pack only from
clear aliases or high-signal hints. Ambiguous contexts fall back to `generic`. `generic` is a final
fallback, not a strong inference candidate.

## Contract and validation

`schemas/domain-pack.schema.json` is the external contract. Runtime loading uses the Python
validator and model boundary in `decide_me.domains`; JSON Schema validation remains a development
and test-time contract check rather than a runtime dependency.

Pack validation rejects unknown fields, invalid enum values, duplicate semantic IDs, duplicate
document profiles, multiple defaults for the same document type, unresolved internal references,
and non-declarative payload shapes. `decision_types[].object_type` is restricted to `decision`;
domain-specific evidence, risk, action, and artifact classifications live in their own pack fields
or object metadata. `action_types` is declarative taxonomy only; it does not add a new runtime
object type. Built-in packs share the standard taxonomy (`research`, `analysis`, `writing`,
`communication`, `execution`, `review`, `verification`, `monitoring`, `decision`), and user packs
may add identifier-shaped action types when they need domain-specific execution categories. The
taxonomy is advisory at the core runtime boundary: object and plan validation require
identifier-shaped `action_type` values, but do not require an action's value to appear in the
selected pack's `action_types`.

## Runtime propagation

New sessions store the selected pack metadata in `session_state.classification`. Specialized
interview sessions use the pack policy to seed the first decision and to attach minimal pack
metadata to newly discovered decisions. Pack-aware object metadata is additive: objects remain
valid domain-neutral runtime objects.

Safety Gate evaluation reads decision, evidence, and risk pack metadata when a registry is
provided. Required evidence from `decision_types[].required_evidence` appears in
`domain_requirements`; matching pack safety rules appear in `domain_safety_rules`; both contribute
to the gate digest. Packs may also provide an optional `risk_policy` override for a risk tier's
approval posture and required actions. The Safety Gate reports the effective policy: approval is
clamped so an approval-required gate cannot display `optional`, high-risk approval cannot display
weaker than `explicit_with_rationale`, and `automatic_adoption` is reported as `allowed`,
`requires_approval`, or `blocked`. The effective policy also contributes to the gate digest.
Pack-free and `generic` objects keep the core Safety Gate behavior, where critical risk blocks
automatic adoption even if an approval artifact exists.

For Phase 9, runtime objects and sessions store `domain_pack_id`, `domain_pack_version`, and `domain_pack_digest` together. Runtime validation and pack-aware evaluation compare those stored values with the currently loaded pack and fail fast on version or digest mismatch. Historical pack replay by digest is future work; until then, stale pack metadata is treated as a validation or evaluation error rather than silently reinterpreting past decisions with the current pack.

## Document profiles

Document profiles are selected from the same pack metadata. A document export may specify
`--domain-pack`; otherwise the compiler uses the single pack represented by selected closed
sessions, or the `generic` profile for mixed scopes when the generic pack declares that document
type. If a single selected pack does not define a pack-specific document type and no generic profile
exists for that type, export fails instead of silently rendering an unprofiled document. The emitted
`DocumentModel.metadata` records the pack id, version, digest, and profile id when a profile is
applied. Phase 9 profiles currently control profile metadata and required-section ordering; richer
domain-specific document sections are future builder work.

Document exports are read-only. They do not emit runtime events or approval artifacts. Embedded
Safety Gate diagnostics intentionally use domain-aware evaluation so required evidence and pack
safety rules are visible in exported documents.

## MVP limits

Phase 9 does not include a pack editor, marketplace, pack history store, or rich per-domain
document sections. If a stored digest no longer matches the current pack, update or migrate the
runtime metadata explicitly before continuing. Do not rely on the runtime to silently reinterpret
old sessions with a changed pack.
