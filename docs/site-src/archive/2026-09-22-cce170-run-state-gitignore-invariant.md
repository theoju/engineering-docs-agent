---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/265
synthesized_into: []
doc_kind: decision
---

# CCE-170: the per-run state gitignore invariant was host-local, not universal

`state_io.save_current_run` writes a sibling file next to `state.json` —
`.engineering-docs-agent/current_run.json`, per-run scratch that is rewritten
on every dispatch and is deliberately NOT part of the merge-as-promotion path
(only `state.json` is meant to be committed). Its docstring used to assert
flatly that this sibling "is gitignored (see .gitignore)". That was true —
but only in the engineering-docs-agent repo's own `.gitignore`. Nothing made
it true on a host repo that adopts the plugin.

## The defect

This repo ships as a generic plugin that scaffolds docs onto arbitrary host
repositories — the `CLAUDE.md` "Generic plugin" mandate is explicit that
`scripts/`-level conventions in this repo are examples, never assumptions
baked into capability code. The gitignore docstring broke that mandate
quietly: it described behavior of the agent repo as if it were a property of
the sibling file itself.

`orchestrator_runner._stage_docs_run_changes` stages with `git add -A .`. On
a host whose `.gitignore` never learned about the sibling, every nightly run
committed ephemeral per-run state into the docs PR. This was not a
hypothetical — it was measured on host `theoju/claude-code-self-assessment`:
`git check-ignore` exited 1, the path was tracked, and 26 commits had already
touched it by the time CCE-170 was filed.

This is the same failure family as the CCE-70/CCE-75 gitlink and pathspec
contamination bugs: a host-vs-agent-repo distinction that mattered was
reasoned about carefully in one place (`_stage_docs_run_changes`'s own
docstring, for `.docs-agent-plugin/`) and never applied to this one.

## The fix covers both halves of the handoff

**Documentation half.** `save_current_run`'s docstring now says outright that
the "gitignored" claim held only in the agent repo, is false on a host by
default, and names the mechanism that closes the gap for newly-onboarded
hosts (below) — plus the retroactive case it does *not* cover.

**Behavioral half.** `site_structure.ensure_run_state_gitignored` runs during
`apply_scaffold` and makes the invariant actually true at onboarding time,
for hosts scaffolded from that point forward.

## `ensure_run_state_gitignored` asks git, not a string compare

The function is idempotent and never raises. It first asks
`git check-ignore -q --no-index` whether the entry would already be excluded
— the pattern question, not the index question — so a host that already
ignores the whole `.engineering-docs-agent/` directory gets no redundant
second line. Only if that check misses does it append a commented block to
the host's `.gitignore` (creating one if none exists), rather than rewriting
the file outright: the host's `.gitignore` stays the host's file.

It returns one of five statuses: `already-ignored`, `added`, `created`,
`added-but-inert-path-is-tracked`, or `unwritable`. `apply_scaffold` surfaces
the result as `run_state_gitignore` in the JSON it returns.

**The tracked case is not success.** `.gitignore` has no effect on a path git
already tracks. On a host that has been running the agent before this fix —
exactly the measured `claude-code-self-assessment` state — the sibling is
committed and `git add -A .` keeps staging it regardless of the new
`.gitignore` line, until someone runs `git rm --cached
.engineering-docs-agent/current_run.json` once. Reporting a plain `added` in
that case would be a quiet lie, so the function reports
`added-but-inert-path-is-tracked` instead, naming the manual step that
remains.

A non-git directory degrades to the same `created`/`added` path rather than
raising — `git`'s own "not a repository" exit code (128) and "no git on
PATH" collapse onto the same branch, matching the plugin's generic-first
degrade-gracefully mandate.

## Traps

- **The invariant is per-host, not per-repo-class.** If you touch
  `save_current_run` or `ensure_run_state_gitignored` again, remember the
  claim they encode is scoped to "hosts onboarded after this change." An
  already-onboarded host with a tracked sibling needs the manual
  `git rm --cached` step; nothing in this fix performs that for them
  automatically, and nothing should — that would be exactly the kind of
  filesystem mutation this repo's other archived incidents (CCE-141, CCE-181)
  warn against doing implicitly.
- **Test the git-repo-scoped claim against the agent repo's own
  `.gitignore`, not just fixture hosts.**
  `tests/site/test_gitignore_run_state.py::test_the_agent_repo_gitignores_its_own_run_state`
  pins the half of the old docstring that was actually true, so a future
  edit can't silently regress it while "fixing" the host half.
- **`apply_scaffold` always reports the gitignore outcome now**, even when
  every other planned file was already present and skipped —
  `test_apply_scaffold_reports_the_gitignore_outcome` covers that the key is
  present regardless of which of the three non-error statuses it resolves
  to.

## Reference

CCE-170 (2026-09-22), closed by PR #265. Test coverage:
`tests/site/test_gitignore_run_state.py`. Implementation:
`scripts/site_structure.py:ensure_run_state_gitignored`,
wired into `scripts/site_structure.py:apply_scaffold`. Docstring fix:
`scripts/state_io.py:save_current_run`.
