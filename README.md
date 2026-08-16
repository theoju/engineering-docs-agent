# engineering-docs-agent

A Claude Code plugin: nightly docs-PR generator with publish verification and tiered content linting.

## What it does

- Watches a host repo's Git/PRs/Jira for changes since the last successful run.
- Opens a PR against the host's docs site with:
  - **What's New** entry summarizing changes.
  - **Updated/new pages** authored by a `page-author` subagent with voice few-shot.
  - **Gap flags** for non-trivial PRs that have no spec/plan.
- Sends a Slack + email digest.
- After the PR merges, verifies the host's build pipeline succeeded and pages are live.

## Install

1. `claude plugin marketplace add <this-repo>` — register the marketplace from the local path or remote URL.
2. `claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace` — install the plugin.
3. `claude /engineering-docs-agent-setup` — run the setup skill from your host repo's root.

For the comprehensive walkthrough (GitHub App registration, all repo secrets, branch protection, validation, per-language host notes, troubleshooting for every partial-mode failure), see [docs/site-src/setup-guide.md](docs/site-src/setup-guide.md). The same content is published on the docs site at `setup-guide.html`.

## Self-hosting (dogfood)

This repo is configured to run the agent against itself — a reference layout for new host repos:

1. `.engineering-docs-agent/config.yml` — host config (framework, paths, Jira project keys, voice samples, publishing target).
2. `.engineering-docs-agent/state.json` — committed state. `last_successful_run.head_sha` is the source of truth for the next nightly's window. Each merged `docs-agent/YYYY-MM-DD` PR advances it via normal git merge — no separate promote workflow.
3. `.engineering-docs-agent/state.example.json` — seed template for fresh host repos. This dogfood host already has a real `state.json`; the example file is preserved for plugin users installing into a new repo.
4. `.engineering-docs-agent/current_run.json` — gitignored ephemeral run state, written every state-update for diagnostics + test observability. Not part of the docs-agent PR.
5. `docs/site-src/` — agent-editable area and MkDocs source dir; the `agent_editable_paths` glob (`docs/site-src/**`) restricts writes here, and the same tree publishes to GitHub Pages.

Run the agent locally against this host:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

> Publish-verification is configured against a `deploy.yml` GitHub Actions workflow that is not yet committed; the `--no-pr` flag above keeps the bootstrap dry-run only. Wiring up the workflow + end-to-end publish path is tracked separately.

### Nightly authoring run

The main authoring pipeline (`scripts/orchestrator_runner.py` with no subcommand) runs automatically once daily at 07:00 UTC via `.github/workflows/docs-agent-nightly.yml`. The workflow opens or append-commits to a `docs-agent/YYYY-MM-DD` PR; per spec §8, a partial run still opens the PR with `partial: true` in the body so an operational gap is visible, not silent.

The workflow runs its GitHub App-token step under `continue-on-error` and exports the step's outcome as `DOCS_AGENT_APP_TOKEN_STATUS`. When that value is exactly `failure` — an App is configured but its installation token could not be minted, typically because the App was uninstalled or transferred to another account — the orchestrator records a blocking `app_token_unavailable` reason and marks the run partial. Since CCE-140 a partial run is no longer barred from auto-merging outright (a cursor-backed advance merges), so `app_token_unavailable` carries its own explicit veto in `_MERGE_VETO_REASON_PREFIXES`: a PR built on the fallback `GITHUB_TOKEN` never triggers host CI, so its check list would be empty rather than green, and the cursor proves only that the baseline is honest — not that anything validated this PR. The values `skipped` (no App configured), `success`, and unset are all silent. Set nothing when running locally.

Auto-merge eligibility (CCE-140): `merge.policy: auto` (the default when the block is absent), no vetoing partial reason, and either a non-partial run **or** a run whose baseline advance came from the CCE-109 cursor. Fact-checker warnings never gate the merge — they ride the PR body and the notification. A PR deferred on `run.deferral_skip_threshold` consecutive runs (default 3; set `0` to disable) is abandoned on the next run, recorded in `state.json`'s append-only `skipped_prs` array, and named in a partial reason so the notification carries it. A human commit on the docs-agent PR still blocks the merge unconditionally.

**Time budget, and why the merge is exempt from it.** `run.time_budget_seconds` bounds the _authoring_ work — the expensive, interruptible part. It does not bound the merge epilogue when the advance is cursor-backed, because the only run that can BE cursor-backed is a time-truncated one, which is past its deadline by construction: enforcing the run budget there would refuse every run auto-merge exists for, silently. The epilogue stays bounded by `merge.checks_grace_seconds` / `merge.checks_timeout_seconds` measured from the merge attempt, so **a run that earns a merge may overrun `time_budget_seconds` by up to `checks_timeout_seconds` (default 900s) while it waits out host CI.** Size the workflow's own job timeout for `time_budget_seconds + checks_timeout_seconds` — the scaffolded template moved from 60 to 90 minutes for exactly this reason, since the 2700s default budget alone already reached the old ceiling. Lower `merge.checks_timeout_seconds` if you would rather forfeit a merge than let the nightly run long.

**The job timeout is not the real ceiling** — the GitHub App installation token is. It is minted mid-job and expires 1h later, and no `timeout-minutes` extends it, so the whole run must clear **one hour from the mint step**, not from job start.

Budget for `authoring + checks_timeout_seconds + tail`, and note that **authoring is not `time_budget_seconds`** — since CCE-152 the authoring loop may run to `run.authoring_hard_cap_seconds`, defaulting to `time_budget_seconds * 1.15`, in order to finish the PR group it is in the middle of (a cut mid-group leaves that PR owing a page and blocks the baseline advance). At the documented 2100s budget that is 2415 + 900 = 3315s, leaving ~285s of the hour for the tail (the in-flight page batch, site generators, the push, the PR create). Both hosts in this repo's orbit set `run.time_budget_seconds: 2100` against a 900s check timeout for that reason.

Part of that sizing is now **enforced structurally**, not just documented: `resolve_authoring_hard_cap` clamps the hard cap down to `GITHUB_APP_TOKEN_TTL_SECONDS - checks_timeout_seconds - 285s` (the poll term is dropped for a `merge.policy: manual` host, which never runs it), so no host can configure an authoring overrun that outlives its own token **measured from the moment the orchestrator starts**. Note what that does and does not cover: the enforced terms are the ones `run()` can see — its own budget, its own overrun, the poll it will run, and the tail reserve — all counted from the `clock()` call at `run()` entry. The workflow mints the token in the job's FIRST step, several minutes of checkout and install earlier, and nothing in the process can measure that gap. **Sizing it is yours**: subtract your job's setup time from the hour before you spend the rest, and keep `time_budget_seconds + checks_timeout_seconds + 285` under what is left. Three consequences worth knowing before you tune either knob:

- **An explicit `run.authoring_hard_cap_seconds` at or below `time_budget_seconds` is rejected at startup** with exit 2 and a logged reason. It is not clamped up. A cap equal to the budget collapses the hard deadline onto the soft one, which restores the arbitrary mid-group cut the cap exists to prevent — silently, in the exact place you were trying to prevent it. **That comparison uses the _resolved_ budget, so `--time-budget-seconds` can trip it against a config file nobody edited**: on a host configured `2100` / `2415`, a hand re-run with `--time-budget-seconds 3000` raises the budget above the config's fixed cap and exits 2 before any work, on a config that is perfectly valid for the nightly. There is no CLI override for the cap, so a hand re-run above the configured cap means editing `run.authoring_hard_cap_seconds` too — or overriding the budget downward rather than up.
- **If the TTL ceiling lands at or below your budget, there is no overrun left to grant.** The run does not abort; the cap is held at the budget and an advisory `authoring_hard_cap_squeezed` reason names the squeeze in the digest. Authoring can then be cut mid-PR-group again and such a run earns no baseline advance — the pre-CCE-152 behaviour, never worse, never silent. **The stock `DEFAULT_TIME_BUDGET_SECONDS` (2700) is in this state**: 2700 + 900 is the entire hour with nothing left for the tail. Lower `run.time_budget_seconds` (2100 is the tested value) or `merge.checks_timeout_seconds` to get the overrun back.

Getting the overall sizing wrong has two shapes, and the second is the dangerous one: a token expiry mid-poll degrades honestly (`auto_merge_skipped: checks_query_failed`, branch pushed, nothing lost, notification still sent), but a **job** timeout mid-poll kills the process before the notifier dispatch at the end of `run()` — no digest, no partial reasons, no alarm. That is the one outcome strictly worse than forfeiting the merge, so keep the job timeout the slacker of the two bounds.

To fire it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` input is a free-text label surfaced in the run summary alongside the post-run `state.json` snapshot. Auth is via the `CLAUDE_CODE_OAUTH_TOKEN` repo secret (same secret as `release.yml`). One run at a time per repo — concurrent invocations queue rather than race on the same docs-agent branch.

### Install from local clone

If you're working from a checkout of this repo (e.g., to test changes before publishing), register the local marketplace and install the plugin:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

That makes the eight agents resolvable without `--plugin-dir` workarounds. The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

### Lens paths and editable paths

The agent reads from **lens paths** and writes to **editable paths**. They overlap, but they are different:

- `docs.lens_paths` defines _where docs live for each lens_ (e.g., `core: docs/site-src/`). The voice-load, gap-detection, and PR-summarization stages read from these paths.
- `docs.agent_editable_paths` defines _where the agent may write_. The orchestrator's runtime filter rejects any proposed page outside these globs.

**Invariant:** every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. A lens with no matching editable glob means the agent reads docs it can never update — usually a mistake.

The editable glob may be **narrower** than the lens path — e.g., a lens `core: docs/` paired with editable `docs/generated/**` is valid: the agent reads everything under `docs/` but only writes to the `generated/` sub-path. The validator accepts this because the editable glob's anchor (`docs/generated/`) starts with the lens path (`docs/`). The compatibility rule is bidirectional: glob anchor and lens path must share a path branch. This repo's dogfood config keeps the two co-located: lens `docs/site-src/` with editable `docs/site-src/**`.

### Jira enrichment (optional)

If your host config sets `sources.jira.enabled: true` and you want the
source-collector subagent to fetch linked issue summaries, set two env
vars in the shell that invokes the orchestrator:

```bash
export JIRA_EMAIL="your.email@example.com"
export JIRA_API_TOKEN="…"  # token from https://id.atlassian.com/manage-profile/security/api-tokens
```

`JIRA_API_TOKEN` is an Atlassian Cloud API token (NOT your password). The
token is sent over TLS via HTTP basic-auth to the Jira REST API.
`dispatch_subagent` already passes the full parent environment into the
subprocess, so any inherited `JIRA_*` vars reach the agent without
additional plumbing.

Without these env vars, the orchestrator continues to run; `jira_issues`
in the source-collector output will be `[]` and the run is marked
`partial: true` with `error: "jira_auth_missing"` so the operational gap
is visible in `.engineering-docs-agent/state.json` partial_reasons and in
Slack/email notifications. See `agents/source-collector.md` Step 5 +
Forbidden outputs §6 for the agent-side contract.

## Live integration tests

The default `pytest` run is fully mocked — no network, no LLM, no cost. A separate `@pytest.mark.live` gate covers the real-LLM dispatch path:

```bash
pytest -m live -v
```

These tests invoke the real `claude` CLI and cost roughly **$1-3 per full pass** (each test ~$0.10-$0.50). They require the `claude` CLI installed and authenticated (OAuth or `ANTHROPIC_API_KEY`), network access, and API quota. Live tests are skipped by default (a `conftest.py` hook); opt in with `-m live`. CI runs them only on tag pushes (`.github/workflows/release.yml`), never per-PR.

What's covered: one `dispatch_subagent` call per payload shape (notifier with a digest, pr-summarizer with PR metadata). The dispatch path is the system-under-test — the kinds of wiring bugs CCE-2 and CCE-3 fixed are exactly what these catch.

## Architecture

See the [design spec](docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md).

## Lint rules

Standalone scripts in `scripts/lint/`. Hosts can run them in their own CI on human-authored PRs:

```
python scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml --paths docs/**/*.md --json
```

## License

MIT.
