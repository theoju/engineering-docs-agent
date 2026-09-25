---
title: Run-state .gitignore at onboarding
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/265
synthesized_into: []
---

# Run-state .gitignore at onboarding

Every dispatch writes a per-run scratch file next to `state.json`:
`.engineering-docs-agent/current_run.json`. It's rewritten on every run and
is never part of the merge-as-promotion path — only `state.json` is meant to
land in your docs PR. Setup now makes sure your host repo ignores it from the
start.

## What changed

`scripts/site_structure.py` gained `ensure_run_state_gitignored`, and
`apply_scaffold` calls it as its last step, so every host scaffolded by
`/engineering-docs-agent:engineering-docs-agent-setup` gets a `.gitignore`
entry for `.engineering-docs-agent/current_run.json` automatically.

Before this, the engineering-docs-agent plugin repo's own `.gitignore` listed
the sibling, but that ignore rule doesn't travel with the plugin — a host
repo doesn't inherit the agent repo's `.gitignore`. Because
`orchestrator_runner._stage_docs_run_changes` stages with `git add -A .`,
an un-ignored host committed the ephemeral scratch file into its docs PR on
every run. This was caught on `theoju/claude-code-self-assessment`: the file
was tracked, un-ignored, and 26 commits deep by the time it was noticed.

`scripts/state_io.py`'s `save_current_run` docstring made the same mistake in
prose — it flatly asserted the sibling "is gitignored," which was only ever
true for this repo's own tree. The docstring is corrected to describe the
host/agent split explicitly.

## How `ensure_run_state_gitignored` behaves

The function is idempotent and never raises. It asks git, not a string
compare, whether the entry is already covered — so a host whose `.gitignore`
already ignores the whole `.engineering-docs-agent/` directory gets no
redundant second line. It returns one of five statuses:

- `already-ignored` — nothing to do.
- `added` — appended to an existing `.gitignore`.
- `created` — wrote a new `.gitignore` containing just this entry.
- `added-but-inert-path-is-tracked` — the entry was added, but the path is
  already tracked by git, so the ignore rule has no effect until you run
  `git rm --cached .engineering-docs-agent/current_run.json` once.
- `unwritable` — the `.gitignore` write failed (permissions, read-only FS);
  scaffolding still completes.

That `added-but-inert-path-is-tracked` status matters: `.gitignore` doesn't
retroactively untrack a path. If your host has been running the agent
already and the scratch file is committed, adding the ignore rule alone
won't stop it from being staged — you still need the one-time
`git rm --cached`. `apply_scaffold`'s return dict surfaces the status under
`run_state_gitignore`, so the setup skill's JSON output tells you when that
manual step remains.

## What this doesn't fix

This closes the gap for hosts scaffolded from now on, and it's a no-op
correction if your host already ignores the sibling or its parent directory.
It does not clean up a host repo where the file is already tracked — that
still requires the manual `git rm --cached` step described above.
