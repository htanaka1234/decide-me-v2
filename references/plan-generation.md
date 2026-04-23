# Plan Generation

Only closed sessions can feed the planner.

The planner returns one of two shapes:

- `Conflicts:` when accepted decisions or workstream scopes disagree
- `Action Plan:` when sessions can be merged into a coherent plan

Minimum conflict checks:

- same decision ID with different accepted answers
- mutually exclusive workstream scopes
- same action-slice name with different responsibilities

If unresolved `P0` decisions with `frontier=now` remain, the planner must return a conditional
plan instead of claiming the work is ready.
