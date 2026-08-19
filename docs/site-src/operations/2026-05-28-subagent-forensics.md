---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/55
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
---

# Subagent Forensic Capture in CI

When a nightly run fails and the runner tears down, there is nothing left to examine. PR #55 fixes that by enabling `DOCS_AGENT_DEBUG_DIR` in `.github/workflows/docs-agent-nightly.yml` and uploading the resulting per-subagent files as a GitHub Actions artifact.

## What the forensic mode captures

Setting `DOCS_AGENT_DEBUG_DIR` to any directory flips the Claude CLI dispatch to `--output-format stream-json --verbose`. For each subagent invocation the orchestrator writes five files into a subdirectory named after the agent:

| File | Contents |
|---|---|
| `prompt.txt` | The full rendered prompt sent to the subagent |
| `stdout.txt` | Raw standard output from the Claude CLI process |
| `stderr.txt` | Raw standard error |
| `stream.jsonl` | One JSON object per streamed event |
| `meta.json` | Dispatch metadata: agent name, model, exit code, wall-time |

These files are what you inspect when a subagent returns `None` and you need to know why.

## How the nightly workflow wires it up

The workflow sets `DOCS_AGENT_DEBUG_DIR` as an environment variable scoped to the orchestrator step. An `actions/upload-artifact@v4` step runs after it with `if: always()` so the artifact upload proceeds even when the orchestrator step exits non-zero. Retention is 14 days.

On a successful run you get the forensic bundle as confirmation. On a failure it is the primary evidence — the files survive runner teardown and are accessible from the Actions run summary.

## Latency cost

Enabling `DOCS_AGENT_DEBUG_DIR` is not free. The switch to `stream-json` mode adds 3–6 seconds per subagent invocation, with outliers reaching ~74 seconds. A pipeline with 6–8 subagents accumulates several minutes of overhead.

The 90-minute job timeout has headroom for this (it was 60 when this was written; CCE-140 raised it). The spec explicitly accepts the cost for a once-daily cron: the diagnostic value outweighs a fixed per-run overhead. Note that since CCE-152 the job timeout is no longer the binding ceiling on a run — the GitHub App installation token's 1-hour TTL (`GITHUB_APP_TOKEN_TTL_SECONDS`, 3600s) is, and this overhead is spent inside it. See [Orchestrator](../architecture/orchestrator.md).

CCE-152 also changed how a run behaves once it runs long enough to hit that TTL pressure. The authoring loop now completes a PR's batches oldest-first and checks the soft deadline only at PR boundaries, so a run that overruns finishes the PR it is mid-way through instead of splitting it across nights. `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds how far past the soft `run.time_budget_seconds` budget that PR-boundary finish is allowed to run, computed as the token TTL minus the merge-check poll (`merge.checks_timeout_seconds`, 900s by default on an auto-merge host) minus a fixed `AUTHORING_TTL_SAFETY_SECONDS` tail reserve (285s) — 3600 − 900 − 285 = 2415s.

That ceiling interacts with the forensic-capture overhead this page measures: at the default 2700s budget, 2415s already sits below the budget itself, so the resolver reports the SQUEEZED outcome — the hard cap holds at the budget with zero overrun, and this page's per-subagent latency tax comes entirely out of a fixed window with no PR-boundary cushion. A 2100s-budget host instead gets the NORMAL outcome: the cap resolves to `int(2100 * 1.15) = 2415`s, which lands exactly on the ceiling, so a run with `DOCS_AGENT_DEBUG_DIR` set retains its full 315s of overrun to finish a PR's page batches. The other two outcomes — CLAMPED (an explicit `run.authoring_hard_cap_seconds` or the computed ratio resolves above the ceiling and is narrowed down to it) and REJECTED (an explicit override at or below the budget, refused as a config error) — are both pinned by `tests/orchestrator/test_authoring_hard_cap_bounds.py`. All four outcomes are info-only or config-validation concerns; only REJECTED aborts the run before authoring starts, and CLAMPED/SQUEEZED never flip a run `partial`.

If the latency becomes a concern at higher subagent counts, the most targeted fix is scoping `DOCS_AGENT_DEBUG_DIR` to failure-only paths rather than unconditional capture. That is deferred until SP-1 produces CI evidence to scope it against.

## Scope and deferred work

This change is SP-1 of issue #321. It adds CI visibility without touching any Python source. Subsequent sub-projects — rescue hardening, forced `StructuredOutput`, and integration testing — are explicitly deferred until SP-1 produces the evidence needed to scope them.

Acceptance criteria 4–6 (post-merge smoke-test confirming the artifact appears and contains source-collector file sets) remain open. Run the workflow via `workflow_dispatch` after merging to close them:

```bash
gh workflow run docs-agent-nightly.yml -f reason="forensics smoke-test"
gh run watch
```

Then open the run summary, download the artifact, and confirm the source-collector subdirectory contains all five files listed above.

## Local reproduction

You can reproduce the same capture locally before CI confirms it:

```bash
export DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
ls /tmp/cce-debug/
```

Each subagent that ran will have its own subdirectory. The debug directory is gitignored and not committed.
