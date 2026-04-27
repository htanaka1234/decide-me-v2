# Examples

## Plain OK Accepted

```text
Accepted: D-012
Accepted answer: Use email magic links for the MVP.
Decision: D-018
Proposal: P-0008
Question: Should audit trails live in the product database or a separate event sink?
Recommendation: Start with the product database.
Why: Lower operational burden for the current milestone.
If not: Separate retention, monitoring, and replay paths become in scope now.
```

## Object And Link Events

```json
{"event_type":"object_recorded","payload":{"object":{"id":"D-auth","type":"decision","title":"Auth mode","body":"Choose the MVP sign-in approach.","status":"accepted","created_at":"2026-04-23T10:15:00Z","updated_at":null,"source_event_ids":["E-001"],"metadata":{"priority":"P0","frontier":"now","domain":"technical"}}}}
{"event_type":"object_recorded","payload":{"object":{"id":"A-auth","type":"action","title":"Implement MVP magic-link sign-in","body":"Wire the existing magic-link path into the MVP onboarding flow.","status":"active","created_at":"2026-04-23T10:16:00Z","updated_at":null,"source_event_ids":["E-002"],"metadata":{"decision_id":"D-auth","implementation_ready":true}}}}
{"event_type":"object_linked","payload":{"link":{"id":"L-A-auth-addresses-D-auth","source_object_id":"A-auth","relation":"addresses","target_object_id":"D-auth","rationale":"The action implements the accepted auth decision.","created_at":"2026-04-23T10:16:00Z","source_event_ids":["E-003"]}}}
```

## Stale Proposal

```text
The active proposal for session S-... is stale because the project head changed.
Use `Accept P-0007` if you want to accept that recommendation explicitly.
```

## Closed Session

```json
{
  "work_item": {
    "title": "MVP auth",
    "statement": "Choose the MVP sign-in approach.",
    "objective_object_id": "O-project-objective"
  },
  "readiness": "conditional",
  "object_ids": {
    "decisions": ["D-auth", "D-hosting-region"],
    "blockers": ["D-hosting-region"],
    "risks": [],
    "actions": ["A-auth"],
    "evidence": ["E-auth-docs"],
    "verifications": [],
    "revisit_triggers": []
  },
  "link_ids": ["L-E-auth-docs-supports-D-auth", "L-A-auth-addresses-D-auth"],
  "generated_at": "2026-04-23T10:20:00Z"
}
```

## Plan Shape

```json
{
  "status": "action-plan",
  "action_plan": {
    "readiness": "conditional",
    "goals": ["MVP auth"],
    "workstreams": [],
    "actions": [{"id": "A-auth", "name": "Implement MVP magic-link sign-in"}],
    "implementation_ready_actions": [{"id": "A-auth", "name": "Implement MVP magic-link sign-in"}],
    "blockers": [{"id": "D-hosting-region", "title": "Compliance hosting region"}],
    "risks": [],
    "evidence": [{"id": "E-auth-docs", "ref": "docs/auth.md"}],
    "source_object_ids": ["D-auth", "A-auth", "E-auth-docs"],
    "source_link_ids": ["L-E-auth-docs-supports-D-auth", "L-A-auth-addresses-D-auth"]
  }
}
```

## Structured ADR Export

```bash
python3 scripts/decide_me.py export-structured-adr \
  --ai-dir .ai/decide-me \
  --decision-id D-012
```

## Decision Register Export

```bash
python3 scripts/decide_me.py export-decision-register \
  --ai-dir .ai/decide-me \
  --format yaml
```

## GitHub Issue Template Export

```bash
python3 scripts/decide_me.py export-github-templates \
  --ai-dir .ai/decide-me \
  --output-dir .github/ISSUE_TEMPLATE
```

## GitHub Issue Draft Export

```bash
python3 scripts/decide_me.py export-github-issues \
  --ai-dir .ai/decide-me \
  --session-id S-20260423-101500-a1 \
  --output-dir .ai/decide-me/exports/github
```

## arc42 Architecture Export

```bash
python3 scripts/decide_me.py export-architecture-doc \
  --ai-dir .ai/decide-me \
  --format arc42 \
  --output docs/architecture/arc42.md
```

## Traceability Matrix Export

```bash
python3 scripts/decide_me.py export-traceability \
  --ai-dir .ai/decide-me \
  --format csv \
  --output docs/traceability/traceability.csv
```

```bash
python3 scripts/decide_me.py export-traceability \
  --ai-dir .ai/decide-me \
  --format markdown \
  --output docs/traceability/traceability.md
```

## Verification Gap Export

```bash
python3 scripts/decide_me.py export-verification-gaps \
  --ai-dir .ai/decide-me \
  --output docs/traceability/verification-gaps.md
```

## Agent Instruction Export

```bash
python3 scripts/decide_me.py export-agent-instructions \
  --ai-dir .ai/decide-me \
  --target agents-md
```

```bash
python3 scripts/decide_me.py export-agent-instructions \
  --ai-dir .ai/decide-me \
  --target cursor \
  --output .cursor/rules/decide-me-decisions.mdc
```
