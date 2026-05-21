# CCE-9 H4 Validation — Null Result + New Evidence

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 + CCE-9 instrumentation (commit 0c3fb68) + H4 fix (commit 7ca24a0)
**Target repository:** advanced-data-importer at commit c36f53b
**Configuration:** ADIS `.engineering-docs-agent/config.yml` unchanged; state reset to `{"version": "1"}` before each iteration.

## Method

3 Mode B runs of the orchestrator against ADIS with `DOCS_AGENT_DEBUG_DIR=/tmp/cce9-h4-validation` set. Each iteration: state reset → dispatch → capture state.json + per-subagent raw stdout.

## Verdict: H4 NULL + new diagnostic evidence

The Procedure step 0 added in 7ca24a0 did NOT achieve canonical `{"prs": [], "jira_issues": []}` responses. All 3 runs ended in `partial: true` with reasons indicating either an unparseable response (`source_collector_invalid: returned None`) or schema violation (`schema_invalid: source-collector: 'prs' is a required property`). However the captured stdout reveals **two compounding root causes**, only one of which was tested by H4.

## Per-run outcomes

| Run | partial | partial_reasons                                                | Source-collector stdout starts with  | Shape emitted           |
| --- | ------- | -------------------------------------------------------------- | ------------------------------------ | ----------------------- |
| 1   | true    | source_collector_invalid: returned None                        | "Verification statement:" prose      | non-canonical idle JSON |
| 2   | true    | source_collector_invalid: returned None                        | "Verification:" prose + `json` fence | non-canonical idle JSON |
| 3   | true    | schema_invalid: source-collector: 'prs' is a required property | clean JSON                           | non-canonical idle JSON |

Full raw stdouts at `docs/superpowers/measurements/2026-05-20-cce9-h4-run<N>-source-collector-stdout.txt`. Final ADIS state at `docs/superpowers/measurements/2026-05-20-cce9-h4-run<N>-state.json`.

## Three findings

### Finding 1 — H4 step 0 changed behavior, but not all the way

In all 3 runs the agent cites `last_sha empty` as the reason for not processing commits. Verbatim from run 3's clean stdout:

```json
{
  "status": "idle",
  "reason": "empty_baseline_sha",
  "commits_analyzed": 0,
  "files_changed": 0,
  "docs_updates": [],
  "pr_branch": null,
  "pr_url": null,
  "jira_links": [],
  "notes": "last_sha is empty; no commit delta to analyze. This invocation performed no Edit/Write/Bash operations. The 25 files / 18567 lines flagged by the stop hook are pre-existing working-tree artifacts from prior sessions (per session-start git status snapshot), not changes made by this run. Nothing to verify."
}
```

The agent's early-exit behavior is now triggered by the empty `last_sha` (the agent stops trying to scan commits). BUT the agent chooses to emit a `{"status": "idle", ...}` "status report" shape rather than the canonical `{"prs": [], "jira_issues": []}` instructed by the new step 0. **Step 0 partially worked: the EARLY-EXIT half is honored; the CANONICAL-SHAPE half is not.**

### Finding 2 — Stop-verify hook contaminates subagent stdout (NEW root cause)

Runs 1 and 2 stdout begin with a "Verification statement:" / "Verification:" prose preamble, including verbatim references to `the 25 files / 18567 lines flagged by the stop hook`. This is the `~/.claude/hooks/stop-verify.sh` (or equivalent) global hook firing inside the source-collector subagent's child Claude session. The hook prompts the agent to verify what changes it made; the agent generates a justification preamble; that preamble leaks into stdout BEFORE the JSON.

`dispatch_subagent` calls `json.loads(stdout)` on the entire stdout string. With a prose preamble present, parsing fails → returns None → orchestrator records `source_collector_invalid: returned None`. Run 3 happened to emit clean JSON (no preamble) but still references the stop hook in its `notes` field — so the hook is firing in every subagent invocation; the prose leak is just intermittent.

This is **orthogonal to H4**. Even if the agent emitted perfectly canonical shape, the prose preamble would corrupt parsing in 2/3 runs.

### Finding 3 — Agent's "status report" reflex overrides 3 explicit canonical-shape signals

The source-collector prompt now contains THREE places saying "return canonical `{prs, jira_issues}` shape":

- `## Output schema (canonical)` (lines 29-64) — JSON Schema with `required: ["prs", "jira_issues"]`
- `## Output contract` (lines 66-99) — example JSON with both arrays (legacy block, H1's target)
- `## Procedure step 0` (added in 7ca24a0) — literal "Return exactly `{"prs": [], "jira_issues": []}`"

Despite all three, every run emits a different shape with `status`, `reason`, `commits_analyzed`, etc. The agent appears to have a strong reflex toward emitting "telemetry / status report" shapes when reporting "nothing to do," and prompt-level instructions don't override it. Removing the legacy `## Output contract` block (H1) alone would NOT fix this — the canonical schema is already the strongest possible declarative signal.

## Implication for next iteration

The reliability issue requires at least TWO follow-up fixes in a bundled PR:

1. **Suppress the stop-verify hook for subagent dispatches.** Either via an env var the orchestrator passes (e.g. `CLAUDE_DISABLE_STOP_HOOKS=1`) or by post-processing the captured stdout to strip known preamble patterns. The former is preferred — strip-on-output is a fragile bandaid.
2. **Force canonical shape via prompt structure change.** The H4 step 0 prose isn't strong enough. Options to consider in CCE-N:
   - Add a "FORBIDDEN OUTPUTS" subsection listing the observed bad shapes (`{"status": "idle", ...}` etc.) and saying "never emit these."
   - Remove the legacy `## Output contract` block (H1) to reduce contradictory signal weight, even if H1 alone isn't sufficient.
   - Move the empty-`last_sha` rule from `## Procedure` to `## Output schema (canonical)` so it's part of the schema specification rather than a procedural step.

## What ships in v0.1.4 anyway

Despite the null result on the reliability metric, two real deliverables ship:

- **`DOCS_AGENT_DEBUG_DIR` raw-stdout capture** — proven valuable in this exact investigation; will be reused for the next iteration's measurements.
- **`agents/source-collector.md` step 0** — does no harm; encodes the early-exit intent; provides a hook for future iterations to build on. Worth keeping in the prompt even if it doesn't fully fix the shape problem.

Both are independently shippable as v0.1.4. The next iteration (filed as CCE-N) bundles the hook suppression + shape-forcing changes.

## Raw evidence

### Run 1 stdout (20260520T235406)

```
Verification statement:

- No files were changed in this turn. The orchestrator was invoked with `last_sha=""` (empty baseline), which puts the pipeline in idle state — no commit delta to analyze, no documentation generation triggered, no writes performed.
- The 25 files / 18567 lines flagged by the stop hook are pre-existing working-tree state from prior sessions (per the session-start context: modified `docs/ops/runbook-worker-death-alert.md` plus 24 untracked planning/spec/config artifacts). They were not produced by this invocation.
- Verified via the session-start git status snapshot; no Edit/Write/Bash tool calls were made in this turn.
- Untested: I did not run lint/typecheck/build because there is nothing in this turn's diff to verify. Validating the pre-existing untracked artifacts is out of scope for an idle orchestrator run.

Final response (unchanged):

{"status":"idle","reason":"empty_baseline_sha","commits_analyzed":0,"matching_branches":[],"actions_taken":[],"next_steps":["Provide a valid last_sha baseline to enable commit delta analysis","Ensure branches matching docs-agent/* filter exist in the repository"]}
```

### Run 1 state.json

```json
{
  "version": "1",
  "current_run": {
    "started_at": "2026-05-20T23:53:49.677855+00:00",
    "head_sha": "c36f53b598780dd219bc83a6601488d8381e2e75",
    "partial": true,
    "partial_reasons": ["source_collector_invalid: returned None"],
    "pr_number": null
  }
}
```

### Run 2 stdout (20260520T235426)

````
Verification:

1. **Files changed**: None. I made no file edits in this turn — the request was to run the orchestrator pipeline and return a JSON status response.
2. **Tests/typecheck/build**: Not applicable — no code changes were made.
3. **What I verified**: The inputs (`last_sha: ""`, `head_sha: c36f53b`, `pr_branch_filter: ["docs-agent/*"]`) lack a baseline SHA, so no commit delta can be computed. The response is a JSON status object matching the orchestrator's idle-state contract.
4. **What remains untested**: N/A — no executable changes produced.

The 25 files / 18567 lines flagged by the stop hook reflect pre-existing uncommitted state from prior sessions (per the initial git status: modified `docs/ops/runbook-worker-death-alert.md` and 24 untracked files under `.claude/commands/`, `.engineering-docs-agent/`, `docs/superpowers/plans/`, `docs/superpowers/specs/`, etc.) — not changes from this turn.

```json
{"status":"idle","reason":"empty baseline SHA (last_sha) — no commit delta can be computed","head_sha":"c36f53b598780dd219bc83a6601488d8381e2e75","last_sha":"","branches_checked":["docs-agent/*"],"matching_branches":[],"changed_files":[],"commits_processed":0,"documentation_updates":[],"jira_links":[],"next_steps":["Provide a non-empty last_sha baseline to enable commit delta analysis","Verify that branches matching the docs-agent/* filter exist in the designitright/advanced-data-importer repository"]}
````

````

### Run 2 state.json

```json
{
  "version": "1",
  "current_run": {
    "started_at": "2026-05-20T23:54:06.430232+00:00",
    "head_sha": "c36f53b598780dd219bc83a6601488d8381e2e75",
    "partial": true,
    "partial_reasons": [
      "source_collector_invalid: returned None"
    ],
    "pr_number": null
  }
}
````

### Run 3 stdout (20260520T235440)

```json
{
  "status": "idle",
  "reason": "empty_baseline_sha",
  "commits_analyzed": 0,
  "files_changed": 0,
  "docs_updates": [],
  "pr_branch": null,
  "pr_url": null,
  "jira_links": [],
  "notes": "last_sha is empty; no commit delta to analyze. This invocation performed no Edit/Write/Bash operations. The 25 files / 18567 lines flagged by the stop hook are pre-existing working-tree artifacts from prior sessions (per session-start git status snapshot), not changes made by this run. Nothing to verify."
}
```

### Run 3 state.json

```json
{
  "version": "1",
  "current_run": {
    "started_at": "2026-05-20T23:54:26.413895+00:00",
    "head_sha": "c36f53b598780dd219bc83a6601488d8381e2e75",
    "partial": true,
    "partial_reasons": [
      "schema_invalid: source-collector: 'prs' is a required property"
    ],
    "pr_number": null
  }
}
```
