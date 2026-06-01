---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# CCE-70: Gitlink Contamination Fix

Every nightly docs-agent PR was committing `.docs-agent-plugin/` as a git submodule gitlink (mode `160000`) into the host repo. This page explains the root cause, the plugin-side fix shipped in PR #88, and the one-time remediation steps required on already-affected hosts.

## Root cause

GitHub Actions checks out the plugin at `.docs-agent-plugin/` using `actions/checkout@v5`. Because that directory contained its own `.git` metadata, git treated it as a nested repository. The orchestrator's staging step called bare `git add .`, which caused git to record `.docs-agent-plugin` as a submodule gitlink rather than skipping it. The gitlink then appeared in every nightly docs-agent PR and drifted on every subsequent run.

ADIS#394 was a confirmed instance. CCE-70 tracked this as a blocking plugin bug first surfaced during CCE-67 investigation.

## Plugin-side fix (PR #88)

**Targeted staging helper.** The orchestrator now calls `_stage_docs_run_changes(repo_root)` instead of bare `git add .`. The helper passes git's exclude pathspec syntax to explicitly skip the plugin directory:

```bash
git add . ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'
```

This is the primary defense. No new runtime dependencies — the pathspec is a git built-in.

**Setup-time `.gitignore` entry.** The `engineering-docs-agent-setup` skill now writes `.docs-agent-plugin/` into the host repo's `.gitignore` during onboarding. This is belt-and-suspenders: it protects against any `git add .` run outside the orchestrator helper (e.g., a developer staging changes manually).

**Regression test.** A test covering the exclusion behavior was added. It verifies that `_stage_docs_run_changes` does not stage `.docs-agent-plugin` even when the directory is present and dirty.

## Host remediation (required for already-onboarded repos)

The plugin fix prevents new gitlinks from being staged. It does **not** remove gitlinks that were already committed. You need to clean those up manually.

### Check whether your repo is affected

```bash
git ls-files --stage | grep 160000
```

If you see a line referencing `.docs-agent-plugin`, your repo has the stale gitlink.

### Remove the gitlink

```bash
git rm --cached .docs-agent-plugin
git commit -m "fix: remove stale .docs-agent-plugin gitlink (CCE-70)"
git push
```

Run this on a feature branch and open a normal PR — do not commit directly to `main`.

### Verify `.gitignore` is updated

After running setup again (or manually), confirm `.docs-agent-plugin/` appears in your root `.gitignore`:

```bash
grep 'docs-agent-plugin' .gitignore
```

If the entry is missing, add it:

```
.docs-agent-plugin/
```

## Audit scope

Hosts onboarded via CCE-57 and CCE-58 are likely affected. Run the `git ls-files --stage` check above on each. The confirmed affected repo is `theoju/advanced-data-import-system`; its remediation PR is tracked separately and is not blocked by this merge.

Hosts onboarded after PR #88 merges will have the `.gitignore` entry written automatically by setup and will not be affected.
