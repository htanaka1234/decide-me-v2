# Project Instructions

## Distribution Artifact

- After any project update that changes the Skill, runtime code, references, schemas,
  templates, packaging metadata, or packaging rules, rebuild the distribution artifact with
  `python3 scripts/build_artifact.py`.
- Treat files under `dist/` as generated output. Do not edit them by hand; update source files
  and rebuild the artifact instead.
- The distribution artifact must contain only the installable Skill package rooted at
  `decide-me/`. Exclude development-only files such as `README.md`, `plan.md`, `tests/`,
  `.git*`, `.ai/`, `.codex`, caches, and previous build output.
