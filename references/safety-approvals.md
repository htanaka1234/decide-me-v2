# Safety Approvals

Phase 7 records approvals as normal domain objects and links. It does not add a top-level approval
projection to `project-state.json`.

## Commands

Record approval for a gate that currently needs approval:

```bash
python3 scripts/decide_me.py approve-safety-gate \
  --ai-dir .ai/decide-me \
  --session-id S-001 \
  --object-id D-001 \
  --approved-by user \
  --reason "Reviewed rollback plan and accepted remaining risk."
```

Inspect approvals:

```bash
python3 scripts/decide_me.py show-safety-approvals --ai-dir .ai/decide-me --object-id D-001
```

`show-safety-approvals` is read-only. `approve-safety-gate` requires an existing mutable session and
writes normal object/link events in that session. The approved target does not need to be bound to
the approval session, which keeps plan action approvals possible after plan generation.

## Approval Artifact

Approval uses an `artifact` object with:

- `metadata.artifact_type: safety_gate_approval`
- `metadata.target_object_id`
- `metadata.gate_digest`
- `metadata.approval_threshold`
- `metadata.approved_by`
- `metadata.approved_at`
- `metadata.reason`
- `metadata.expires_at`

The artifact addresses the approved object with a normal `addresses` link. Matching approval
requires the target id, gate digest, non-expired approval metadata, and the `addresses` link.

Blocked gates cannot be satisfied by approval. This is especially important for `critical` risk:
an external-review approval artifact can be recorded for audit, but automatic adoption remains
blocked until the decision is split, deferred, rejected, or reworked. Gates that need approval
become `passed` only when a matching current approval artifact exists. If evidence, assumptions,
risks, safety-relevant links, or the effective risk policy change, the gate digest changes and the
old approval no longer satisfies the gate.

Re-approving the same target and gate digest reuses the deterministic artifact id. If the prior
artifact is expired, inactive, or missing its `addresses` link, the command refreshes that artifact
with normal update/status/link events instead of creating a second approval object.
