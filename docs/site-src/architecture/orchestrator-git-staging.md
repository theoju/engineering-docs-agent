---
description: "The orchestrator runner commits exactly two things at the end of each docs-run: the contents of docs_dir and state.json."
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/97
synthesized_into: []
---

# Orchestrator git staging convention

The orchestrator runner commits exactly two things at the end of each docs-run: the contents of `docs_dir` and `state.json`. Nothing else enters the nightly docs-agent PR.

## The rule

The staging step in `scripts/orchestrator_runner.py` uses an explicit pathspec:

```bash
git add <docs_dir> state.json
```

It does **not** use `git add -A`.

## Why not `git add -A`

`git add -A` stages every untracked and modified file in the working tree. During a docs-run the working tree accumulates files that must not land in the PR: `__pycache__` directories written by Python imports, editor tempfiles, intermediate agent scratch files, and any other side-effects of running subagents.

The fix introduced in PR #97 scopes the staging command to the two intentional output paths. Everything else in the tree is ignored at commit time regardless of how the run accumulates it.

## What the pathspec covers

| Path | Why it's staged |
|---|---|
| `<docs_dir>` | All authored and updated doc pages written by `page-author` and related subagents. Configured as `docs.docs_dir` in the host's `.engineering-docs-agent/config.yml`. |
| `state.json` | The runner advances `last_successful_run.head_sha` and writes a run-summary block. Without staging this file, the next nightly would re-process the same window. |

`<docs_dir>` is a variable, not a literal path. The runner reads it from the loaded host config at startup (`scripts/orchestrator_runner.py`) and substitutes it into the git command. This keeps the staging step generic across host repos.

## Test coverage

`test_stage_uses_pathspec_not_add_all` in the unit suite asserts that the staging call receives the explicit pathspec and that `git add -A` is never invoked. If you change the staging logic, that test is the authoritative check — not a filesystem diff.

## History

PR #94 (CCE-66 Phase 3) introduced `git add -A` as a convenience. It worked for the happy path but staged stray files whenever the Python process or a subagent left behind untracked content. PR #97 replaced it with the pathspec form and added the unit test. The broader convention — "only `docs_dir` and `state.json` belong in the nightly commit" — now has a named page so future changes have a clear reference to update against.
