---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/195
synthesized_into: []
---

# The nightly workflow

Every onboarded host runs `docs-agent-nightly` — rendered from `templates/workflow-run.yml` at scaffold time into `.github/workflows/docs-agent-nightly.yml` — on a schedule, plus two extra triggers. `scripts/scaffold_workflow.py` rewrites the cron minute per host so 100 onboarded repos don't all fire at the same instant; the template default is a `7 7 * * *` off-minute cron, and setup picks a deterministic minute in `[5, 55]` for each new host.

You get three ways to fire it:

- **`schedule`** — the nightly run itself.
- **`workflow_dispatch`** — a manual fire, with an optional `reason` input that shows up in the run summary.
- **`pull_request` (closed, `main`)** — template-only, paired with a job-level guard (`!startsWith(github.head_ref, 'docs-agent/')`) so a merged docs-agent PR doesn't re-trigger itself.

The job runs under a `docs-agent-nightly` concurrency group with `cancel-in-progress: false`, so a manual fire queues behind an in-flight nightly rather than racing it on the same `docs-agent/YYYY-MM-DD` branch.

## Step order and what each one is for

1. **Generate GitHub App installation token** (`id: app-token`) — mints a short-lived installation token when `vars.DOCS_AGENT_APP_CLIENT_ID` is set. See [App-token failures](#app-token-failures-degrade-the-run-they-dont-kill-it) below.
2. **Checkout host repo** — full history (`fetch-depth: 0`, needed so `state.json`'s window math can see every merge), authenticated with `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`.
3. **Check out engineering-docs-agent plugin** — vendors the plugin's `scripts/` into `.docs-agent-plugin` at a pinned release tag, so the orchestrator step below can invoke it.
4. **Set up Python**, **Install runtime dependencies** (`pyyaml`, `jsonschema`), **Install claude CLI**.
5. **Assert OAuth token** — three cheap layered checks against `CLAUDE_CODE_OAUTH_TOKEN` (unset, wrong prefix, suspiciously short) before any subagent dispatch is attempted. Skip it on Enterprise/Bedrock/Vertex hosts with `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT: 'true'`.
6. **Configure git identity** — the runner commits directly, so this has to happen before the orchestrator step.
7. **Run docs-agent** (`id: docs-agent`) — invokes `scripts/orchestrator_runner.py --repo-root .`, the pipeline described in the architecture docs. `GH_TOKEN` here uses the same `steps.app-token.outputs.token || secrets.GITHUB_TOKEN` fallback as checkout; `DOCS_AGENT_APP_TOKEN_STATUS` carries the App-token step's `outcome` (see below).
8. **Upload subagent forensics** — persists per-dispatch prompt/stdout/stderr/stream/meta artifacts (`if: always()`), so a run that died before any subagent dispatched still uploads a (possibly empty) artifact rather than erroring the step.
9. **Run summary** — writes trigger, HEAD SHA, and the post-run `state.json` into the job summary.
10. **Print partial-run reasons** — echoes `current_run.partial_reasons[]` to stdout so they're visible in `gh run view --log` even when the summary block is collapsed.

## App-token failures degrade the run — they don't kill it

The App-token step (step 1) is where the workflow used to be fragile. `actions/create-github-app-token` has two distinct non-success outcomes, and they mean opposite things:

- **`skipped`** — `vars.DOCS_AGENT_APP_CLIENT_ID` is unset. The host never configured a GitHub App. This is the normal, silent, supported bare-host path; the run falls back to `secrets.GITHUB_TOKEN`.
- **`failure`** — an App *is* configured, but the token couldn't be minted (the App was uninstalled, transferred to another account, or its key was revoked). This also falls back to `secrets.GITHUB_TOKEN`, but the host is broken, not bare.

Before CCE-127, only the `skipped` case was actually handled. The step lacked `continue-on-error: true`, so a `failure` outcome aborted the job outright — the checkout, orchestrator, and every downstream step were skipped, and the run just died. Worse, the `|| secrets.GITHUB_TOKEN` fallback that was supposed to cover this case was unreachable: GitHub only evaluates a step-output `||` expression when the referenced step was *skipped*, never when it *failed*. A failed step aborts the job before the expression is reached at all. That gap caused 15 consecutive nightly failures on the plugin's own dogfood host (2026-07-24 → 2026-08-07) after the App was transferred to another GitHub org during an unrelated migration, deleting its installation on this repo.

The fix has two parts, both in `templates/workflow-run.yml` (kept in lockstep with the dogfood workflow, audited for intentional divergences in `tests/templates/test_workflow_run_parity.py`):

- The App-token step now runs under `continue-on-error: true`, which is what makes the job survive a `failure` outcome at all and makes the `||` fallback on the checkout and `GH_TOKEN` steps actually reachable on the failure path.
- The step's `outcome` — not `conclusion` — is exported into the orchestrator step's environment as `DOCS_AGENT_APP_TOKEN_STATUS`. This distinction matters: `continue-on-error` rewrites `conclusion` to `success` so the job can proceed, but `outcome` retains the true `failure`. Exporting `conclusion` instead would silently report a healthy mint for a run that had none.

`scripts/orchestrator_runner.py:run` reads that variable right after `state["current_run"]` is initialized and before the auto-merge decision, and records a blocking reason only for the literal string `"failure"`:

```python
if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
    _record_dispatch_reasons(
        state,
        [
            "app_token_unavailable: GitHub App installation token could not "
            "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
            "fire on this PR. Verify the App is installed on this repo."
        ],
        ok=False,
    )
```

`"skipped"`, `"success"`, and unset all stay silent — the bare-host path is unaffected. `ok=False` routes the reason through the same blocking `_record_dispatch_reasons` path as a failed source-collector or page-author dispatch, which sets `current_run.partial` to `true`. No new gate logic was needed for this: `_maybe_auto_merge` (`scripts/orchestrator_runner.py:_maybe_auto_merge`) already skips with `partial_run` whenever `partial` is true. That interlock is the entire point — a PR built on `secrets.GITHUB_TOKEN` can't trigger the host's own `on: push` CI, so it would register zero checks; without the `partial` flag, the auto-merge gate would read "zero checks failed" as "nothing failed" and merge unvalidated docs.

If your run shows `app_token_unavailable` in its partial-reasons digest, the fix is operational, not code: confirm the App is still installed on the repo (a **404** on the App's `/installation` lookup means the JWT authenticated fine but the installation is gone — reinstall; a **401** means the App or its private key is actually bad — rotate), then re-fire with `workflow_dispatch`.

## Forensics and debugging a failed run

Set `DOCS_AGENT_DEBUG_DIR` (the workflow does, pointed at `${{ runner.temp }}/docs-agent-debug`) to capture per-subagent-dispatch forensics: prompt, extracted stdout, raw stderr, the full NDJSON stream, and a `meta.json` tool-use summary, one set of files per dispatch. The **Upload subagent forensics** step persists this directory as a run artifact for 14 days regardless of whether the run succeeded, so a nightly that failed partway through still leaves a trail of what each subagent was asked and what it returned.

For a quick read without downloading the artifact, `current_run.partial_reasons` in `state.json` is echoed directly to the job log by the **Print partial-run reasons** step — check there first before pulling forensics.
