---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Workflow Template — Generic Host Setup

The `templates/workflow-run.yml` file is the GitHub Actions workflow you drop into any host repo to run the nightly docs-agent pipeline. Before PR #83, the template contained a P1 defect that silently broke every non-dogfood host: the orchestrator was invoked at the host root (`python scripts/orchestrator_runner.py`), which only works when the plugin lives co-located with the host — the dogfood case only.

This page explains the defect, the fix, and how to wire the template correctly in a new host.

## The defect

The original `run` step assumed `scripts/` was present at the workspace root:

```yaml
- name: Run orchestrator
  run: python scripts/orchestrator_runner.py --repo-root .
```

On the dogfood host (this repo), `scripts/` is at the root. On any other host, it is not. The step fails immediately at import with `ModuleNotFoundError` or `FileNotFoundError`, and the job exits without a docs PR or a useful error message.

The same issue applied to `pip install -r scripts/requirements.txt` — the host has no such file.

## The fix

PR #83 adds an explicit checkout step that vendors the plugin into `.docs-agent-plugin/` in the runner workspace, then updates the `run` step to reference that path.

The fixed workflow adds this step before `Install plugin deps`:

```yaml
- name: Check out engineering-docs-agent plugin
  # CCE-57: the host repo is not the plugin. Vendor the plugin's
  # scripts/ directory into the runner workspace at .docs-agent-plugin
  # so the orchestrator step can invoke it. `ref: main` until the plugin
  # cuts a versioned release; pin a tag/SHA here when one exists.
  uses: actions/checkout@v5
  with:
    repository: theoju/engineering-docs-agent
    ref: main
    path: .docs-agent-plugin
```

And the orchestrator step becomes:

```yaml
- name: Run orchestrator
  run: |
    python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

The full corrected workflow is in `templates/workflow-run.yml`. Copy it to `.github/workflows/docs-agent-run.yml` in your host repo.

## Installing the workflow

1. Copy `templates/workflow-run.yml` from the plugin repo into your host repo at `.github/workflows/docs-agent-run.yml`.
2. Commit and push the file on a feature branch.
3. Set the required secrets in your host repo — see [Setup Guide](../setup-guide.md) Part 2 for the full secrets list.
4. Trigger a manual run to confirm the checkout and orchestrator steps succeed before relying on the nightly schedule.

To trigger manually:

```bash
gh workflow run docs-agent-run.yml -f reason="smoke test"
gh run watch
```

## Pinning the plugin version

The vendored step uses `ref: main` by default. This is intentional during early onboarding — you always get the latest fixes without re-copying the workflow file. Once the plugin cuts a versioned release, replace `ref: main` with a tag or SHA:

```yaml
ref: v1.0.0   # or a full commit SHA for maximum reproducibility
```

Pin the version in the same commit you promote the host to production.

## Concurrency and permissions

The template enforces `concurrency.group: docs-agent-${{ github.ref }}` so parallel triggers queue rather than race on the same `docs-agent/YYYY-MM-DD` branch. It also sets `contents: write` and `pull-requests: write` at the job level — your host repo's branch protection must allow the GitHub App installation token to push to non-`main` branches. See [Setup Guide](../setup-guide.md) §2.3 for App install steps.

## Related pages

- [JS/TS Host Support](../architecture/js-ts-host-support.md) — toolchain detection added in the same PR.
- [Preflight Host CLI](preflight-host.md) — run `scripts/preflight_host.py` to validate discovery output and the rendered workflow before touching the host repo.
- [Setup Guide](../setup-guide.md) — comprehensive per-host onboarding walkthrough.
