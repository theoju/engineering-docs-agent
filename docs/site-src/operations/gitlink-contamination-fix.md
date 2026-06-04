---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Gitlink Contamination Fix (CCE-70)

Every nightly docs-agent run on an onboarded host was staging a gitlink entry for `.docs-agent-plugin/` into the resulting docs-agent PR. The gitlink (git object mode `160000`) pointed at the plugin's HEAD SHA and drifted on each nightly, polluting the PR diff with a spurious submodule reference that had nothing to do with docs content.

## Root cause

`actions/checkout@v5` checks the plugin out into `.docs-agent-plugin/` inside the host workspace. Git sees the nested `.git/` directory and treats the path as a submodule. The orchestrator's bare `git add .` call in `scripts/orchestrator_runner.py` then staged the gitlink automatically alongside the real docs changes.

CCE-67's content-validator fix made the contamination newly visible by producing the first otherwise-clean docs-agent PR. The gitlink had always been staged; it just wasn't the only anomaly before. First confirmed in `theoju/advanced-data-import-system` PR #394 (merged commit `8c00014`). CCE-70 tracks this as a plugin-wide host-contamination bug.

## What changed (PR #88)

The orchestrator now calls a dedicated `_stage_docs_run_changes(repo_root)` helper instead of bare `git add .`. The helper excludes the plugin checkout using git's pathspec exclude syntax:

```bash
git add . -- ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'
```

Git's pathspec engine processes these exclusions before any index update, so the gitlink never enters the staging area regardless of what else is staged.

The setup skill (`skills/engineering-docs-agent-setup/SKILL.md`) also instructs new host onboardings to add `.docs-agent-plugin/` to the host's `.gitignore`. The exclude pathspec is the primary fix; the `.gitignore` entry is a belt-and-suspenders guard that also protects against a human `git add .` picking up the directory.

Two regression tests in `tests/orchestrator/test_gitlink_exclusion.py` run against a real local git repo (not mocked) and verify:

1. The helper correctly stages docs files.
2. The helper never stages `.docs-agent-plugin/`, even when the directory is present.

## Cleanup for already-contaminated hosts

If a host repo already has the gitlink cached (confirmed for `theoju/advanced-data-import-system` via commit `8c00014`), remove it before the next nightly run:

```bash
git rm --cached .docs-agent-plugin
git commit -m "fix: remove gitlink contamination from docs-agent staging (CCE-70)"
```

Open this as a separate PR against the host's default branch. PR #88 prevents future contamination but does not retroactively clean existing history.

## Post-merge verification

After this fix lands, re-trigger `docs-agent-nightly` on CCSA and ADIS:

```bash
gh workflow run docs-agent-nightly.yml -f reason="CCE-70 gitlink contamination fix verification"
gh run watch
```

Confirm that no `.docs-agent-plugin` entry appears in the resulting docs-agent PR diff. If you still see it, either the host's `.gitignore` is missing the exclusion or a previously staged gitlink is still cached and needs the `git rm --cached` step above.
