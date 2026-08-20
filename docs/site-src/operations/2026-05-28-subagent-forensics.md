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

Neither the workflow's `timeout-minutes: 90` (it was 60 when this was written; CCE-140 raised it) nor a stock host's `time_budget_seconds` (2700s) is the ceiling this overhead actually has to fit inside. Since CCE-152, the binding bound is the GitHub App installation token's `GITHUB_APP_TOKEN_TTL_SECONDS` (1h) minus the merge poll minus a fixed post-run tail — computed by `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`), not asserted from the job timeout. A stock 2700s-budget host is squeezed flat against that ceiling: it earns zero authoring overrun, so forensic-mode overhead spent during authoring competes directly with the page batches CCE-152 exists to protect, not with idle headroom under a 90-minute job kill. The spec explicitly accepts the cost for a once-daily cron: the diagnostic value outweighs a fixed per-run overhead. See [Orchestrator](../architecture/orchestrator.md) for the full arithmetic.

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
