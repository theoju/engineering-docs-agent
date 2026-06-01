---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Host Onboarding

Operational reference for bringing a new host repo into the `engineering-docs-agent` nightly pipeline. For the full end-to-end install walkthrough — GitHub App registration, repo secrets, branch protection — see [setup-guide.md](../setup-guide.md). This page covers the operational requirements that must hold on the host side after initial setup.

## `.gitignore` requirements

Add `.docs-agent-plugin/` to your host repo's `.gitignore` before the first nightly run:

```
# engineering-docs-agent plugin checkout — never stage as a submodule
.docs-agent-plugin/
```

The nightly CI checks out the plugin into `.docs-agent-plugin/` during each run. Git treats a nested directory that contains its own `.git` as a submodule unless that path is explicitly excluded. Without the `.gitignore` entry, `git add` picks it up as a gitlink (mode `160000`) and the generated docs PR ends up with a spurious submodule reference — every host, every run.

The setup skill (`/engineering-docs-agent:engineering-docs-agent-setup`) writes this entry automatically. If you bootstrapped your host before PR #88 landed, add the line manually and commit it.

## How the orchestrator stages changes

The orchestrator's staging step (`scripts/orchestrator_runner.py`) calls `_stage_docs_run_changes(repo_root)` to build the commit for the docs-agent PR. The helper passes an explicit exclude pathspec to git:

```bash
git add -- . ':!.docs-agent-plugin'
```

This means the plugin checkout is excluded from staging at the git level, independent of `.gitignore`. The two defenses are belt-and-suspenders: the `.gitignore` prevents the directory from appearing in `git status` at all; the pathspec exclude blocks it even if git somehow treats it as tracked.

Before PR #88, the orchestrator used a bare `git add .` at `scripts/orchestrator_runner.py:1767`. That swept the plugin directory in as a gitlink whenever the host hadn't excluded it. CCE-70 tracked the regression, which surfaced during onboarding of CCSA (CCE-57) and ADIS (CCE-58).

## Verifying a clean nightly run

After the first nightly run, check that the generated docs PR contains only docs changes:

```bash
gh pr diff <docs-agent/YYYY-MM-DD PR number> --name-only
```

The output should list only files under your `docs.agent_editable_paths` globs (e.g., `docs/site-src/**`). If you see `.docs-agent-plugin` in the diff, the exclude pathspec did not apply — confirm your plugin version is at or after PR #88 and that your CI checks out the plugin correctly.

You can also confirm the staging behavior locally:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
git diff --cached --name-only
```

With `--no-pr`, the orchestrator stages the commit but does not push or open a PR. Inspect the index with `git diff --cached --name-only` and confirm `.docs-agent-plugin/` does not appear.

## Onboarding checklist

Run through this list for each new host repo before enabling the nightly workflow:

- [ ] `.docs-agent-plugin/` is in `.gitignore` and committed.
- [ ] `CLAUDE_CODE_OAUTH_TOKEN` repo secret is set to a `sk-ant-oat…` token.
- [ ] `GH_APP_TOKEN` (or equivalent) secret is set for the GitHub App installation.
- [ ] `docs.agent_editable_paths` in `.engineering-docs-agent/config.yml` covers all lens paths (the config loader validates this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`).
- [ ] `.engineering-docs-agent/state.json` exists with a valid `last_successful_run.head_sha`.
- [ ] The nightly workflow (`.github/workflows/docs-agent-nightly.yml`) is committed and enabled in GitHub Actions.
- [ ] Branch protection on `main` allows the GitHub App installation token to push (but not bypass required reviews).

See [setup-guide.md](../setup-guide.md) §Part 7 for the full copy-paste checklist that covers GitHub App registration and per-language notes.
