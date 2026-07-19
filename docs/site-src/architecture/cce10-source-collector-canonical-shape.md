---
description: "The schema and field-by-field contract for the source-collector subagent's\
  \ output \u2014 required `prs` and `jira_issues` top-level fields, optional `error`\
  \ and `partial` degradation signals, and why downstream stages depend on validation\
  \ never being skipped."
source_files:
- scripts/orchestrator_runner.py
- tests/agents/test_schema_md_sync.py
- tests/orchestrator/test_dispatch_subagent_env.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: architecture
---

# CCE-10: Source Collector Canonical Shape

The `source-collector` subagent feeds every downstream stage of the nightly pipeline. Its output must always validate against the canonical schema; a malformed response halts PR summarization, page authoring, and gap detection for the entire run.

## Output schema

The required top-level fields are `prs` and `jira_issues`. Two optional fields (`error`, `partial`) signal degraded runs:

```json
{
  "prs": [
    {
      "number": 42,
      "url": "https://github.com/owner/repo/pull/42",
      "title": "feat: add X",
      "body": "...",
      "merge_sha": "a1b2c3d",
      "merged_at": "2026-05-28T10:00:00Z",
      "author": "alice",
      "files": [],
      "labels": [],
      "jira_keys": ["CCE-10"]
    }
  ],
  "jira_issues": [],
  "partial": true,
  "error": "jira_auth_missing"
}
```

The schema is defined in `agents/schemas/source_collector.schema.json` and mirrored verbatim in the `## Output schema (canonical)` block of `agents/source-collector.md`. Both copies are enforced to stay identical by `tests/agents/test_schema_md_sync.py`.

## What CCE-10 fixed: stdout contamination via `CLAUDE_STOP_VERIFY`

Before CCE-10, a global stop-verify shell hook (`~/.claude/hooks/stop-verify.sh:22`) could prepend a `"Verification statement:"` prose preamble to the Claude process's stdout. Because the orchestrator parses subagent output with a bare `json.loads()`, any non-JSON prefix caused the entire dispatch to return `None`, silently treating the run as if the source-collector had failed.

CCE-10 closes this by setting `CLAUDE_STOP_VERIFY=0` in the subprocess environment. The relevant line is `scripts/orchestrator_runner.py`:

```python
run_kwargs["env"] = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}
```

The env dict extends `os.environ` rather than replacing it, so PATH, credentials, and all other ambient variables still reach the child process. `tests/orchestrator/test_dispatch_subagent_env.py` enforces both invariants: `CLAUDE_STOP_VERIFY` must be `"0"`, and `PATH` must match the parent's `os.environ["PATH"]`.

## Defense-in-depth: `_rescue_json_object`

CCE-10 closes the stop-verify pathway, but other contamination patterns exist (CCE-15 documented an `"★ Insight"` preamble injected by an explanatory-output-style plugin). The orchestrator also carries a prose-tolerant fallback at `scripts/orchestrator_runner.py`:

```python
rescued = _rescue_json_object(canonical_text)
```

The rescue scans for the first balanced `{...}` in the output and attempts `json.loads` on that slice. If it succeeds, the contamination event is recorded in `partial_reasons` as `prose_contamination_rescued: source-collector` and the run continues. This is a fallback, not the primary defense; `CLAUDE_STOP_VERIFY=0` remains the preferred prevention.

## Schema–markdown sync enforcement

Every agent's `.md` file must embed its output schema in a `## Output schema (canonical)` fenced JSON block, and that block must be byte-for-byte equivalent to the corresponding `.schema.json` file. The test at `tests/agents/test_schema_md_sync.py` checks all seven agents. If you update `agents/schemas/source_collector.schema.json`, also update the inline block in `agents/source-collector.md`, or the test fails.

## Forbidden output patterns

The `agents/source-collector.md` file enumerates seven forbidden output shapes with concrete bad/good examples. The most frequent violations observed in baseline runs:

- **§5** — emitting `prs: []` without first invoking `gh pr list` (4 of 5 runs in the CCE-12 baseline)
- **§7** — returning PRs whose `merge_sha` is outside `last_sha..head_sha` (3 of 5 runs in the CCE-16 baseline)
- **§6b** — emitting `jira_issues: []` after a failed Jira fetch without `partial: true` + `error: "jira_auth_missing"`

The orchestrator clips out-of-window PRs at `scripts/orchestrator_runner.py` (`_clip_prs_to_window`) as a safety net, but the contract requires the agent to clip first.

## Gotchas & layering rules

`CLAUDE_STOP_VERIFY=0` only suppresses the stop-verify hook. It does not suppress other hooks or plugins. If a new contamination pattern appears, verify first with `DOCS_AGENT_DEBUG_DIR=/tmp/debug` (which writes the raw NDJSON event stream to `<agent>.stream.jsonl`) before adding another rescue path.

The `additionalProperties: false` constraint in the schema is intentional. Do not add fields to the agent's output without updating the schema and its inline mirror in the `.md` file — the validator rejects any extra key, which surfaces as a schema-invalid partial reason rather than a silent data loss.
