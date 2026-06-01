---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Preventing gitlink contamination from `.docs-agent-plugin/`

The nightly workflow checks out the plugin at `.docs-agent-plugin/` via `actions/checkout`. Without an explicit exclusion, git treats the nested `.git/` directory as a submodule and stages it automatically — mode `160000`, a gitlink entry. Every docs-agent PR ends up carrying a drifting gitlink that points at the plugin's HEAD SHA from that runner, not a real submodule. The gitlink doesn't break the PR, but it dirties every merge with an irrelevant tree entry and confuses anyone reading the diff.

## How the fix works

`scripts/orchestrator_runner.py` now calls `_stage_docs_run_changes(repo_root)` instead of bare `git add .`. That helper passes git's exclude pathspec:

```bash
git add -- . ':!.docs-agent-plugin'
```

The `':!.docs-agent-plugin'` pathspec tells git to stage everything under the working tree *except* the nested checkout directory. The plugin directory never enters the index, so it never enters the PR diff.

The `_stage_docs_run_changes` helper is integration-tested with a real git repo in `tmp_path`. Two tests verify: (1) docs changes are staged, and (2) `.docs-agent-plugin/` is absent from the index after staging.

## Belt-and-suspenders: `.gitignore`

When you onboard a new host with the setup skill (`/engineering-docs-agent-setup`), it writes `.docs-agent-plugin/` into the host's `.gitignore`. This is belt-and-suspenders: git won't track an ignored path at all, so even a bare `git add .` is safe on correctly onboarded hosts.

For hosts onboarded before this fix, add the entry manually:

```bash
echo '.docs-agent-plugin/' >> .gitignore
git add .gitignore
git commit -m "chore: exclude plugin checkout from git tracking (CCE-70)"
```

## Recovering from an existing gitlink

If a previous nightly run already committed a gitlink into your host repo, remove it with:

```bash
git rm --cached .docs-agent-plugin
git commit -m "chore: remove stale gitlink for .docs-agent-plugin"
```

The `git rm --cached` removes the index entry without touching the working tree. Run it on the branch that carries the gitlink, not on `main` directly. After the commit lands, the setup-skill's `.gitignore` entry prevents recurrence.

## Verifying staging behavior

After applying the fix (or after onboarding a new host), confirm the plugin directory stays out of the index on your next run:

```bash
git status
```

`.docs-agent-plugin/` should appear under "Untracked files" (or not at all if `.gitignore` is in place) — not under "Changes to be committed". If you see it listed as a staged submodule, the exclude pathspec or `.gitignore` entry is missing.
