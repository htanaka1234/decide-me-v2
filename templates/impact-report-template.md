# Impact Report: {{ root_object_id }}

## Summary

- Change kind: {{ change_kind }}
- Affected objects: {{ affected_count }}
- Highest severity: {{ highest_severity }}
- Affected layers: {{ affected_layers }}

## Affected Objects

| Object | Type | Layer | Status | Severity | Impact | Recommendation |
|---|---|---|---|---|---|---|
{{ affected_objects }}

## Invalidation Candidates

| Candidate | Target | Kind | Severity | Approval | Reason |
|---|---|---|---|---|---|
{{ invalidation_candidates }}

## Paths

| Target | Path |
|---|---|
{{ paths }}

## Notes

This report is read-only. It does not modify runtime state, create invalidation links, or change object status.
