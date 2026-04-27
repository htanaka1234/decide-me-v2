# Examples

## Plain OK accepted

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

## Stale proposal

```text
The active proposal for session S-... is stale because the project head changed.
Use `Accept P-0007` if you want to accept that recommendation explicitly.
```

## Closed session

```text
Closed: S-20260423-101500-a1
Readiness: conditional
Accepted decisions:
- D-001: Adopt email magic links for the MVP.
Unresolved blockers:
- D-004: Compliance hosting region is still undecided.
```

## Structured ADR export

```bash
python3 scripts/decide_me.py export-structured-adr \
  --ai-dir .ai/decide-me \
  --decision-id D-012
```

## Decision register export

```bash
python3 scripts/decide_me.py export-decision-register \
  --ai-dir .ai/decide-me \
  --format yaml
```

## GitHub issue template export

```bash
python3 scripts/decide_me.py export-github-templates \
  --ai-dir .ai/decide-me \
  --output-dir .github/ISSUE_TEMPLATE
```

## GitHub issue draft export

```bash
python3 scripts/decide_me.py export-github-issues \
  --ai-dir .ai/decide-me \
  --session-id S-20260423-101500-a1 \
  --output-dir .ai/decide-me/exports/github
```

## arc42 architecture export

```bash
python3 scripts/decide_me.py export-architecture-doc \
  --ai-dir .ai/decide-me \
  --format arc42 \
  --output docs/architecture/arc42.md
```

## Traceability matrix export

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

## Verification gap export

```bash
python3 scripts/decide_me.py export-verification-gaps \
  --ai-dir .ai/decide-me \
  --output docs/traceability/verification-gaps.md
```

## Agent instruction export

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
