# SP-1: docs-agent-nightly subagent forensics in CI

**Ticket:** CCE-41
**Status:** Draft (awaiting user review)
**Decomposed from:** #321 ("Fix source-collector returning None")

## Problem

Every recent `docs-agent-nightly` run that finished produced the same opaque failure: the docs-agent PR body shows `WARNING — Partial run — source_collector_invalid: returned None`, but the workflow logs contain zero detail about what the subagent actually emitted. Without that detail every "fix" is a guess.

Evidence:

- PR #54 body: `WARNING — Partial run — source_collector_invalid: returned None`
- Workflow run `26604860009` log: 19s author step, no subagent stdout/stderr visible
- Local reproduction on 2026-05-28 against the same window (`2208cd5..36d3743`) with `DOCS_AGENT_DEBUG_DIR` set showed the source-collector emitting a §3 prose preamble before its valid JSON; the runner's `_rescue_json_object` recovered locally but apparently fails on whatever shape the CI environment produces

The orchestrator already implements a forensic capture mode that writes per-subagent files (`prompt.txt` / `stdout.txt` / `stderr.txt` / `stream.jsonl` / `meta.json`) when the `DOCS_AGENT_DEBUG_DIR` env var is set. This was built in CCE-9 + CCE-12 and is referenced at `scripts/orchestrator_runner.py:357-372`. It has never been enabled in the CI workflow.

## Goal

Every `docs-agent-nightly` run — scheduled or manual — emits subagent forensics and persists them as a downloadable workflow artifact, so every CI failure is self-diagnosing.

## Non-goals (deferred sub-projects)

- **SP-2: Rescue hardening.** Strengthening `_rescue_json_object` for the shapes observed via SP-1. Cannot be specified without SP-1's evidence first.
- **SP-3: Forced StructuredOutput.** Migrating subagents to use Claude Code's structured-output tool-call mechanism so the model literally cannot emit prose. This is the architectural fix; SP-1 unblocks the data to scope it.
- **SP-4: Subagent integration test.** A pytest harness that exercises the real subagent dispatch with mocked tool calls and asserts schema compliance.
- **Surfacing partial_reasons to the workflow log directly.** Mostly subsumed: once `meta.json` lands in the artifact, every dispatch's outcome is recoverable.
- **Sensitive-content scrubbing of agent stdout.** Out of scope for a private dogfood repo. Revisit if/when the plugin runs against public hosts.

## Architecture

Three small components, all confined to `.github/workflows/docs-agent-nightly.yml`. No Python changes — the orchestrator is already wired to write forensics when the env var is set.

1. **Env var on the runner step.** Set `DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug` in the existing "Run nightly authoring" step. The runner already switches `claude` to `--output-format stream-json --verbose` and writes per-dispatch files to this directory when the env var is non-empty.

2. **Upload step with `if: always()`.** A new step after the runner uses `actions/upload-artifact@v4` with retention 14 days. The `if: always()` clause runs the upload even when the runner step exits 1 — which is the failure case we most want forensics for.

3. **No-files-found tolerance.** Set `if-no-files-found: warn` so a runner step that fails before any dispatch (config invalid, state corrupted) doesn't break the workflow on a missing directory.

## Workflow YAML diff (the entire change)

```yaml
- name: Run nightly authoring
  env:
    DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug
  run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"

- name: Upload subagent forensics
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: docs-agent-subagent-forensics-${{ github.run_id }}
    path: ${{ runner.temp }}/docs-agent-debug/
    retention-days: 14
    if-no-files-found: warn
```

Two added blocks, ~12 lines net.

## Data flow + retention

```
cron fires
  → runner sets DOCS_AGENT_DEBUG_DIR
    → each dispatch_subagent call writes 5 files per subagent invocation:
        <ts>-<agent>.prompt.txt    (the framed input)
        <ts>-<agent>.stdout.txt    (canonical extracted text)
        <ts>-<agent>.stderr.txt    (claude's stderr)
        <ts>-<agent>.stream.jsonl  (full NDJSON tool-call stream)
        <ts>-<agent>.meta.json     (returncode + argv + tool_use summary)
  → runner exits (success OR failure)
  → upload-artifact tars the directory and ships it to GitHub
  → 14-day retention; downloadable from the run's Summary page
```

Storage estimate per run: ~30-50 KB per subagent × 6-8 subagents = 0.2-0.4 MB. At 1 cron/day × 14 days = under 6 MB at any moment. Within GitHub's free-tier 500 MB allowance.

## Failure modes

| Mode                                      | Behavior                                   | Mitigation                                                               |
| ----------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------ |
| Runner step fails before any dispatch     | Debug dir is empty                         | `if-no-files-found: warn` — upload step warns, doesn't fail the workflow |
| Upload step itself fails (rare; network)  | Workflow continues; warning logged         | No retry. Failure visible in run summary                                 |
| Concurrent runs to the same artifact name | Each run has unique `github.run_id` suffix | No collision possible                                                    |
| Artifact too large                        | (Not expected at our scale)                | If exceeded, switch to gzip-on-upload or trim per-subagent footprint     |

## Testing

- **Pre-merge:** YAML lint via `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs-agent-nightly.yml'))"`. The existing runner unit tests already cover the `DOCS_AGENT_DEBUG_DIR` write path (verify via `grep -rn "DOCS_AGENT_DEBUG_DIR" tests/`).
- **Post-merge smoke-test:** Fire the workflow via `workflow_dispatch` against `main`. Confirm the run summary shows a `docs-agent-subagent-forensics-<run_id>` artifact. Download it. Confirm `<ts>-source-collector.stdout.txt` contains the agent's actual output (whatever shape it is). Use this as the input to scoping SP-2.

## Acceptance criteria

1. `.github/workflows/docs-agent-nightly.yml` updated with the two-block diff above.
2. YAML parse succeeds.
3. `pytest` suite still green (no Python changes, but full suite run for safety).
4. Post-merge `workflow_dispatch` fire produces a downloadable artifact named `docs-agent-subagent-forensics-<run_id>`.
5. Artifact contains at least one `<ts>-source-collector.*` file set (5 files for that dispatch).
6. Runner step's success/failure outcome is unchanged (the `DOCS_AGENT_DEBUG_DIR` path is purely additive).

## Risks

- **Per-run latency cost.** The comment at `scripts/orchestrator_runner.py:365-372` documents stream-json mode at 3-6s for Cat-A (zero tool-call) runs, up to ~74s for outliers. Acceptable for a 1/day cron.
- **Artifact content sensitivity.** Forensics contain agent stdout, which includes PR titles/bodies and Jira summaries. This repo is private; no scrubbing required for this scope. Re-evaluate before any public host of the plugin runs with telemetry on.
- **Stochastic non-reproduction.** The whole reason SP-1 exists is that the agent's output shape varies between runs. The first artifact we capture might happen to be the recoverable shape. SP-1 ships even if that happens — the corpus accumulates over days/weeks and will catch the unrecoverable shape eventually.

## Decomposition note

This spec is intentionally narrow: it instruments CI without changing any behavior. The fix to source-collector's prose-preamble emission lives in SP-2 (rescue hardening) or SP-3 (forced StructuredOutput). The investigation that decomposed #321 into SP-1/SP-2/SP-3/SP-4 lives in this session's brainstorm transcript; the local reproduction that revealed the root cause is the empirical basis for splitting along these boundaries.
