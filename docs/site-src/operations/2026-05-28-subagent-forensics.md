---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/55
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
doc_kind: architecture
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

The 90-minute job timeout has headroom for this (it was 60 when this was written; CCE-140 raised it). The spec explicitly accepts the cost for a once-daily cron: the diagnostic value outweighs a fixed per-run overhead. Note that since CCE-152 the job timeout is no longer the binding ceiling on a run — the GitHub App installation token's 1h TTL is, and this overhead is spent inside it. See [Orchestrator](../architecture/orchestrator.md).

If the latency becomes a concern at higher subagent counts, the most targeted fix is scoping `DOCS_AGENT_DEBUG_DIR` to failure-only paths rather than unconditional capture. That is deferred until SP-1 produces CI evidence to scope it against.

## Diagnosing a stalled baseline

If you're pulling forensic artifacts because `last_successful_run` in `state.json` hasn't moved across several nightlies, check the run's `partial_reasons` for a repeating `time_budget_exceeded: authored i/N page batches ...` entry before you go digging through `stream.jsonl`. That message is emitted by the authoring loop in `scripts/orchestrator_runner.py:run`, and where it's allowed to fire changed under CCE-152.

Before CCE-152, the soft-deadline check in that loop cut at whatever page batch it landed on when the clock passed `deadline`, with an `i > 0` escape hatch that only guaranteed the very first batch ran unconditionally — it said nothing about finishing a PR's whole page group. A PR whose fan-out exceeded one run's budget got its page group split at the same point on every subsequent run: the same leading pages got re-authored, `advance_cursor_list` broke at index 0 every time, and the baseline never moved. This is exactly what happened on the ADIS host — PR #646 restructured `CLAUDE.md` into roughly six pages against a 1–5 page-per-run budget, and four consecutive nightlies (2026-08-13 through 2026-08-15) each re-authored the same leading pages and ended in `no_advance_no_cursor`, freezing the baseline for 20.6 days even though admission itself never truncated.

Since CCE-152, the cut is scoped to a PR boundary: the loop only truncates when the batch it's about to author belongs to a different PR than the previous batch (`_owner != _prev_owner` in `run`), or once the run has crossed `authoring_hard_deadline` — a second, harder ceiling computed by `resolve_authoring_hard_cap`. That ceiling exists because "always finish the current PR" is unbounded on its own: a PR fanning out to twenty pages could hold a run open past the GitHub App installation token's one-hour TTL and fail it outright, so the hard cap trades a bounded overrun (`run.authoring_hard_cap_seconds`, or `budget * 1.15` by default) against that TTL and cuts wherever the loop stands once it's exceeded.

When you're reading the digest or `partial_reasons` for this, the cut reason now names the PR the truncation landed inside, and the run also carries `authoring_hard_cap_squeezed` or `authoring_hard_cap_clamped` (both `info_only`) when the hard cap couldn't add any overrun on top of the soft budget — worth checking before you assume a fresh stall is the same PR-boundary bug this fixed. In forensic capture, `meta.json`'s `duration_ms` per page-author dispatch is the fastest way to confirm whether a given PR's page group is actually finishing inside the hard cap or getting cut again.

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
