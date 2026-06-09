---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/108
synthesized_into: []
---

# docs-agent-nightly: on/off controls and manual trigger

The nightly authoring run is driven by `.github/workflows/docs-agent-nightly.yml`. It fires `scripts/orchestrator_runner.py`, opens or append-commits to a `docs-agent/YYYY-MM-DDTHH` branch, and creates a PR against `main`.

## Schedule

The workflow runs daily at **07:07 UTC** (off-minute to avoid GitHub's `:00` scheduling pileup). The cron entry is:

```yaml
schedule:
  - cron: "7 7 * * *"
```

A partial run still opens the PR — it sets `partial: true` in the body so an operational gap is visible rather than silent. The workflow itself exits green in the partial case so the next nightly fire isn't suppressed by a red status.

## Firing manually

Use `workflow_dispatch` to trigger a run outside the schedule:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` field is free-text. It surfaces in the run summary alongside the post-run `state.json` snapshot — useful when diagnosing a specific gap or testing a config change.

You can also fire from the GitHub Actions UI: **Actions → docs-agent-nightly → Run workflow**.

## Pausing the schedule

If stale-PR accumulation recurs, pause the cron by commenting out the `schedule:` block in `docs-agent-nightly.yml` and leaving `workflow_dispatch:` intact. PR #108 is the precedent — it paused the cron on 2026-06-04 after six unmerged PRs accumulated from the same May-29-to-HEAD window.

Re-enable the schedule only after the durable fixes are in place. When PR #108 paused it, the re-enable gates were:

- **D1** — PR-body enrichment: review window, lens file counts, top-N pages, and `partial_reasons` inline so operators can evaluate a PR in under 60 seconds.
- **D2** — Auto-close-stale: "freshest-only" policy that closes prior open `docs-agent/*` PRs unless a human has edited them.
- **D3** — Merge-gate decision: auto-merge fully-green non-partial runs, or operator-promotion runbook for the rest.

D1 and D2 shipped in PRs #112 and #113 (CCE-89). D3 remains open as a separate ticket. The cron was re-enabled after D1 + D2 landed.

## Merge cadence invariant

Each nightly run opens a **fresh branch** (`docs-agent/YYYY-MM-DDTHH`). It never appends commits to a prior docs-agent PR. `state.json.last_successful_run` advances only when a docs-agent PR merges to `main`.

If the operator does not merge within ~24h, the next nightly opens a competing snapshot of the same window — not an incremental delta on top of the unmerged one.

Do not rebase a stale docs-agent PR. Each is a fresh branch with no rebase target. Close stale PRs (D2 automates this) and merge the freshest one, or wait for the next nightly.

## Concurrency

The workflow uses:

```yaml
concurrency:
  group: docs-agent-nightly
  cancel-in-progress: false
```

Concurrent manual fires queue rather than race on the same branch. Let the first run finish before triggering another.

## Required secrets and variables

| Name | Kind | Purpose |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Secret | Claude CLI auth (`sk-ant-oat…` format) |
| `DOCS_AGENT_APP_PRIVATE_KEY` | Secret | GitHub App private key for the `docs-agent-bot` App |
| `DOCS_AGENT_APP_CLIENT_ID` | Variable | GitHub App Client ID (not the numeric App ID) |
| `JIRA_API_TOKEN` | Secret | Jira basic-auth for source-collector enrichment (optional) |
| `JIRA_EMAIL` | Variable | Jira account email paired with the API token (optional) |

If `JIRA_API_TOKEN` or `JIRA_EMAIL` is absent, the source-collector skips Jira enrichment and continues — no run failure, just `source_collector_error: jira_auth_missing` in the partial reasons.

## Diagnostics

Set `DOCS_AGENT_DEBUG_DIR` before invoking the runner locally to capture per-dispatch forensics:

```bash
DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug python3 scripts/orchestrator_runner.py --repo-root .
```

In CI, the workflow uploads the forensics directory as a GitHub Actions artifact (`docs-agent-subagent-forensics-<run_id>-<attempt>`) retained for 14 days. Download it from the run's **Summary** page when diagnosing a partial or failed run.

The **Run summary** step appends the post-run `state.json` snapshot to the GitHub Actions step summary. The **Print partial-run reasons** step echoes `state.json.current_run.partial_reasons` to stdout so they appear in `gh run view --log` even when the summary block is collapsed.

## Related

- Decision record: [docs-agent cadence invariant and stale-PR sweep (2026-06-05)](../archive/2026-06-05-docs-agent-cadence-invariant.md)
- Stale PR archives: `.engineering-docs-agent/stale-prs-archive/pr-{85,86,90,92,94,95}.json`
- CCE-89: D1 PR-body enrichment, D2 auto-close-stale, D3 merge-gate decision
