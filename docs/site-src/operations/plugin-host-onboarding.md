---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Plugin Host Onboarding

This page covers what you need to do to onboard a non-dogfood repository as a host for the engineering-docs-agent plugin. It addresses the workflow template fix that previously blocked all non-dogfood hosts, explains the preflight tool, and walks through the onboarding sequence.

## Who this is for

You are an operator bringing a new host repo under the agent. The host is not this plugin's own repo (the dogfood host). It may be a Python, JS, or TypeScript project.

## The workflow template fix

Before PR #83, `templates/workflow-run.yml` assumed the plugin's code lived at the host repo root. That assumption is only true for the dogfood host. On every other host, the orchestrator runner was unreachable and the nightly workflow failed immediately.

The fix adds a sibling `actions/checkout` step that checks out the plugin into `.docs-agent-plugin/` inside the host's workspace. The runner then resolves all plugin scripts relative to that path. If you installed the workflow template before this fix, re-copy it from `templates/workflow-run.yml` and update your workflow file.

```yaml
# In your host repo's .github/workflows/docs-agent-nightly.yml:
- uses: actions/checkout@v4
  with:
    repository: theoju/engineering-docs-agent
    path: .docs-agent-plugin
```

The orchestrator runner reference in your workflow must point into `.docs-agent-plugin/`:

```yaml
- run: python3 .docs-agent-plugin/scripts/orchestrator_runner.py
```

## Preflight check before writing any config

Run `preflight_host.py` from your host repo root before touching `.engineering-docs-agent/config.yml`. It is read-only — it writes nothing.

```bash
python3 .docs-agent-plugin/scripts/preflight_host.py --repo-root .
```

The preflight tool:

1. Runs `setup_discover.discover()` against your repo root.
2. Prints a discovery summary (toolchain, detected docs framework, source paths).
3. Proposes a `config.yml` block you can paste directly.
4. Outputs a secrets checklist with the exact names expected by the workflow template.
5. Emits actionable warnings for anything that would cause a partial run (missing Jira creds, no docs dir, unresolved source paths).

Fix every warning before proceeding. Partial runs are visible in `state.json` and Slack, but a run that can't find your docs directory will produce no output.

## Toolchain detection

The discovery output now includes a `toolchain` block:

```json
{
  "toolchain": {
    "node": "20.x",
    "bun": null,
    "deno": null,
    "package_manager": "npm",
    "docusaurus_dep": "3.2.1"
  }
}
```

Any field the detector cannot resolve is `null`. The setup skill and preflight tool both read this block to decide which build commands to propose and whether to add a `docusaurus`-specific publish step. You do not need to set these values manually — they are inferred from `package.json`, lock files, and runtime version probes.

## Onboarding sequence

1. Install the plugin and register the marketplace (see `README.md`).
2. Copy `templates/workflow-run.yml` to `.github/workflows/docs-agent-nightly.yml` in your host repo.
3. Run `preflight_host.py` and resolve all warnings.
4. Paste the proposed config block into `.engineering-docs-agent/config.yml`. Adjust `docs_dir`, `lens_paths`, and `agent_editable_paths` to match your repo layout.
5. Set the required secrets in your host repo's GitHub settings (the preflight checklist lists the exact names).
6. Seed `.engineering-docs-agent/state.json` from `.engineering-docs-agent/state.example.json`.
7. Trigger the workflow manually with `gh workflow run docs-agent-nightly.yml -f reason="bootstrap"` and inspect the run summary.

A green first run writes a `docs-agent/YYYY-MM-DD` PR against your repo. Review it, merge it, and the agent advances `last_successful_run.head_sha` automatically on the next nightly.

## Secrets checklist

The preflight tool prints this list, but here is the canonical set for reference:

| Secret name | Purpose |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Authenticates the `claude` CLI for all subagent dispatches |
| `DOCS_AGENT_GITHUB_APP_ID` | GitHub App ID for PR creation and status reads |
| `DOCS_AGENT_GITHUB_APP_PRIVATE_KEY` | Corresponding private key (PEM, base64-encoded) |
| `JIRA_EMAIL` | Optional — enables Jira issue enrichment |
| `JIRA_API_TOKEN` | Optional — paired with `JIRA_EMAIL` |

Jira secrets are optional. Without them, the orchestrator runs in partial mode with `error: "jira_auth_missing"` recorded in `state.json`.

## Common failure modes

**Workflow can't find orchestrator script.** You are using the pre-fix template. Re-copy `templates/workflow-run.yml` and add the plugin checkout step described above.

**Preflight reports `docs_dir not found`.** Your `config.yml` points at a path that doesn't exist yet. Create the directory or correct the path before running the nightly.

**First run produces no pages.** Check `state.json` for `partial_reasons`. A missing `agent_editable_paths` glob is the most common cause — every `lens_paths` entry must be covered by at least one editable glob (the config loader enforces this at boot).

**JS/TS host: build step fails after PR merge.** Confirm the `toolchain.package_manager` field in the preflight output matches your actual lock file. If detection is wrong, override it in `config.yml` under `site.build_command`.
