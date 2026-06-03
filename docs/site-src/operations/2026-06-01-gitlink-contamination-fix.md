---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Gitlink Contamination Fix (2026-06-01)

## What happened

GitHub Actions checks out the plugin at `.docs-agent-plugin/` using `actions/checkout@v5`. Because that directory was not excluded from git staging, git treated it as a nested repository and staged it as a gitlink (mode `160000`). Every nightly docs-update PR produced by the orchestrator silently added a submodule entry to the host repo's index.

This broke host repo integrity without any visible error. The root cause is that a bare `git add .` has no knowledge of the plugin checkout, and `160000` mode entries pass through without warning unless you explicitly inspect the index.

The issue was discovered during CCE-67 and is related to the plugin-vendoring pattern tracked in CCE-57 and CCE-58.

## The fix

PR #88 extracts a `_stage_docs_run_changes` helper in the orchestrator. Instead of a bare `git add .`, the helper now calls:

```bash
git add -- . ':!.docs-agent-plugin'
```

The negative pathspec `:!.docs-agent-plugin` tells git to stage everything except the plugin checkout directory. This is a surgical exclusion: no other staging behavior changes.

The new tests live in `tests/orchestrator/test_gitlink_exclusion.py` and cover the exclusion directly — staging a tree that contains a nested repo directory and asserting the gitlink entry is absent from the index.

## Onboarding recommendation

Add `.docs-agent-plugin/` to the host repo's `.gitignore` as a belt-and-suspenders measure. The negative pathspec in `_stage_docs_run_changes` is the primary guard, but a `.gitignore` entry prevents other tools and manual `git add` invocations from picking up the directory accidentally.

```
# .gitignore
.docs-agent-plugin/
```

If you're installing the plugin into a new host, the updated onboarding instructions include this entry. If you're running an existing install, add it manually — no other changes are required.
