# Object Model

Phase 5 objects use one common envelope:

- `id`: stable object id.
- `type`: one of the domain-neutral object types.
- `title`: short human-readable label, or `null` when the object is only meaningful through body
  and links.
- `body`: concise object content, or `null` when title is sufficient.
- `status`: type-specific lifecycle value.
- `created_at`: timestamp from the event that first created the object.
- `updated_at`: timestamp from the latest event that changed the object, or `null`.
- `source_event_ids`: effective event ids that justify the current projected object state.
- `metadata`: type-specific structured data that is not a relationship to another object.

Defined object types:

- `objective`: desired project or milestone outcome.
- `constraint`: hard boundary that limits acceptable plans or solutions.
- `criterion`: evaluation standard used to compare options or verify readiness.
- `option`: candidate path, answer, design, or implementation choice.
- `proposal`: current or historical recommendation made by the interview engine.
- `decision`: recorded acceptance, rejection, deferral, or unresolved choice point.
- `assumption`: belief taken as true until evidence or a revisit trigger challenges it.
- `evidence`: code, docs, tests, user statements, prior sessions, or external facts.
- `risk`: possible negative outcome that may need mitigation or acceptance.
- `action`: implementation, investigation, or coordination work item.
- `verification`: test, check, review, acceptance criterion, or other proof activity.
- `revisit_trigger`: condition that makes an object worth re-opening.
- `artifact`: generated or referenced output such as a plan, ADR, report, file, or issue.

Object boundary rules:

- A proposal is its own object. A decision may accept or reject a proposal through a link.
- An option is its own object. A proposal may recommend an option through a link.
- A risk is its own object. It is not a decision kind or a decision attribute.
- Evidence is its own object. It supports or challenges other objects through links.
- An action is its own object. It is not an action slice embedded in a close summary.
- A revisit trigger is its own object. It revisits another object through a link.
- Relationships such as dependency, support, challenge, recommendation, acceptance, verification,
  supersession, and blocking are never duplicated as top-level object fields.

`metadata` is reserved for intrinsic structured details such as priority, frontier, confidence,
source path, exported file path, or tool-specific identifiers. If a value points at another object,
model it as a link instead of metadata.

