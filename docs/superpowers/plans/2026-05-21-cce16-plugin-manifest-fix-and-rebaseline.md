# CCE-16 Plugin Manifest Fix + Real Re-Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `.claude-plugin/plugin.json` `author`-field schema violation that has been silently blocking all 7 subagents from loading since 2026-05-19 (commit `628a7262`), then execute a true 5-run Mode B baseline against the real `source-collector` agent to supersede the synthetic CCE-12/CCE-14/CCE-15 baselines (which all measured default Claude Code, not the agent).

**Architecture:** Three composable tasks, each independently shippable: (1) TDD the manifest fix with a `jsonschema`-driven unit test that enforces correct manifest shape going forward; (2) re-run the standardized 5-run Mode B measurement procedure with the agent actually loaded; (3) write a corrected baseline doc and prepend supersession notices to CCE-12, CCE-14, and CCE-15 baseline docs so the audit trail stays honest. The fix itself is a one-character change (string → object); the value is the verification harness and the corrected measurement record.

**Tech Stack:** Python stdlib + `jsonschema>=4.0` (already a project dependency, used by `tests/schemas/test_state_schema.py`). `pytest` for unit tests. The Claude Code CLI (`claude --plugin-dir ...`) for live Mode B dispatches. No new runtime dependencies.

---

## Preamble — branch setup

Run before Task 1. Working tree currently has `.claude-plugin/plugin.json` modified locally (a manual verification edit applied during root-cause investigation); the manifest fix is **not** committed. The plan reverts that change in Task 1 Step 0 so TDD can show a true failing test first.

```bash
git checkout -b fix/CCE-16-plugin-manifest-author
git status --short
# Expected:  M .claude-plugin/plugin.json
```

If the working tree shows additional unrelated modifications, stop and surface them to the user before proceeding.

---

## Task 1: TDD the manifest schema fix

**Files:**

- Create: `templates/plugin_manifest.schema.json`
- Create: `tests/schemas/test_plugin_manifest_schema.py`
- Modify: `.claude-plugin/plugin.json` (line 5: `author` field)

### Why a schema file + unit test

The Claude CLI's plugin loader uses an internal Zod schema. We can't import that. Instead we encode our own minimal JSON-Schema draft-07 of the manifest we know works (verified against `claude-mem` and other working plugins) and validate our actual manifest against it. The test catches:

- `author` as a string (current bug — exactly what's failing)
- Missing required fields (`name`, `version`, `description`, `author`, `license`)
- Wrong types on any field

Future manifest edits run this test in CI and fail loud if shape regresses. The schema lives under `templates/` next to `state.schema.json` (the existing convention).

- [ ] **Step 0: Reset the working tree**

```bash
git checkout -- .claude-plugin/plugin.json
git status --short
# Expected: (empty — no modified files)
```

- [ ] **Step 1: Write the schema file**

Create `templates/plugin_manifest.schema.json` with this exact content:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Claude Code plugin manifest (engineering-docs-agent local minimum)",
  "type": "object",
  "required": ["name", "version", "description", "author"],
  "additionalProperties": true,
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+"
    },
    "description": {
      "type": "string",
      "minLength": 1
    },
    "author": {
      "type": "object",
      "required": ["name"],
      "additionalProperties": true,
      "properties": {
        "name": { "type": "string", "minLength": 1 },
        "email": { "type": "string" },
        "url": { "type": "string" }
      }
    },
    "license": {
      "type": "string"
    }
  }
}
```

Note: `additionalProperties: true` at the top level (intentional — the Claude CLI allows extra fields like `homepage`, `keywords`, `repository`, `skills`, `mcpServers`, `interface`). We're enforcing the minimum shape we depend on, not the full upstream schema.

- [ ] **Step 2: Write the failing test**

Create `tests/schemas/test_plugin_manifest_schema.py`:

```python
"""CCE-16: enforce .claude-plugin/plugin.json matches the Claude Code
plugin-loader's required manifest shape. The actual schema lives in the
Claude CLI's Zod validator; ours is a local minimum that catches the
class of bug that silently broke all subagent loading for two days
(CCE-12 through CCE-15 baselines all measured default Claude Code
instead of the real agents because the manifest's `author` field was
a string, not an object)."""

from __future__ import annotations
import json
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA = json.loads(
    (REPO_ROOT / "templates" / "plugin_manifest.schema.json").read_text()
)
MANIFEST = json.loads(
    (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text()
)


def test_actual_manifest_matches_schema():
    """The live plugin.json must validate. Catches the CCE-16
    'author as string' regression and any analogous shape break."""
    validate(MANIFEST, SCHEMA)


def test_author_string_is_rejected():
    """Regression guard: the exact bug shape that broke us for two
    days (author as a bare string) must fail validation."""
    broken = {**MANIFEST, "author": "Theo Jungeblut"}
    with pytest.raises(ValidationError, match="author"):
        validate(broken, SCHEMA)


def test_author_object_without_name_is_rejected():
    """Author must have at least a name property — the CLI validator
    requires it."""
    broken = {**MANIFEST, "author": {"email": "x@y.z"}}
    with pytest.raises(ValidationError, match="name"):
        validate(broken, SCHEMA)


def test_missing_required_field_rejected():
    """Required fields: name, version, description, author."""
    for missing in ("name", "version", "description", "author"):
        broken = {k: v for k, v in MANIFEST.items() if k != missing}
        with pytest.raises(ValidationError):
            validate(broken, SCHEMA)


def test_extra_top_level_field_allowed():
    """additionalProperties:true at the root — homepage, repository,
    keywords, etc. should not cause rejection."""
    extended = {**MANIFEST, "homepage": "https://example.com"}
    validate(extended, SCHEMA)
```

- [ ] **Step 3: Run test to verify FAIL on `test_actual_manifest_matches_schema`**

```bash
.venv/bin/pytest tests/schemas/test_plugin_manifest_schema.py -v
```

Expected output: `test_actual_manifest_matches_schema` FAILS with a `ValidationError` mentioning `author` (because the manifest currently has `"author": "Theo Jungeblut"` — a string). The four other tests should PASS.

If `test_actual_manifest_matches_schema` passes here, the working tree is contaminated — return to Step 0 and reset.

- [ ] **Step 4: Apply the manifest fix**

Edit `.claude-plugin/plugin.json` line 5. Change:

```json
  "author": "Theo Jungeblut",
```

To:

```json
  "author": { "name": "Theo Jungeblut" },
```

Final manifest should be:

```json
{
  "name": "engineering-docs-agent",
  "version": "0.1.1",
  "description": "Nightly docs-PR generator: summarizes engineering changes, updates host docs site, runs lint, opens a PR.",
  "author": { "name": "Theo Jungeblut" },
  "license": "MIT"
}
```

- [ ] **Step 5: Run test to verify PASS**

```bash
.venv/bin/pytest tests/schemas/test_plugin_manifest_schema.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full test suite excluding known flakies**

```bash
.venv/bin/pytest --ignore=tests/orchestrator/test_state_carry_forward.py -q
```

Expected: `188 passed` (187 from CCE-15 + 5 new − 4 that were already passing analogues = adjust accordingly; the goal is **no new failures**, and the count strictly increases by 5 over the CCE-15 baseline).

- [ ] **Step 7: Smoke-verify the dispatch loads the agent**

```bash
SMOKE_DIR=$(mktemp -d)
claude --setting-sources project,local \
  -p 'Reply with only the JSON object {"prs":[],"jira_issues":[]}. Do not call any tools.' \
  --agent source-collector \
  --plugin-dir "$(pwd)" \
  --allowedTools "Bash Read Write Edit WebFetch" \
  --output-format stream-json --verbose \
  > "$SMOKE_DIR/init.jsonl" 2>"$SMOKE_DIR/stderr.txt"
head -1 "$SMOKE_DIR/init.jsonl" | python3 -c "
import sys, json
e = json.loads(sys.stdin.read())
agents = e.get('agents', [])
errors = e.get('plugin_errors')
assert 'engineering-docs-agent:source-collector' in agents, f'source-collector missing from {agents}'
assert not errors, f'plugin_errors present: {errors}'
print('SMOKE PASS: agent loaded, no plugin errors')
"
```

Expected stdout: `SMOKE PASS: agent loaded, no plugin errors`.

If the assertion fires, the manifest fix is incomplete — investigate `init.jsonl` and `stderr.txt` before continuing.

- [ ] **Step 8: Commit Task 1**

```bash
git add templates/plugin_manifest.schema.json tests/schemas/test_plugin_manifest_schema.py .claude-plugin/plugin.json
git commit -m "$(cat <<'EOF'
fix(CCE-16): plugin manifest — author must be object, not string

The Claude CLI's plugin loader uses a Zod schema that requires
`author` to be an object with a `name` property. Our manifest set it
to a bare string, so the loader rejected the plugin silently at every
dispatch. All CCE-12, CCE-14, and CCE-15 baseline measurements
captured default Claude Code responding to an injected user prompt,
not the actual subagents. This rewrites those retrospectives — see
the upcoming docs/superpowers/measurements/2026-05-21-cce16-*.

Adds templates/plugin_manifest.schema.json + a regression test that
validates the live manifest against the schema on every test run.
Catches this exact failure mode plus the broader class of "missing
required field" / "wrong type on field" manifest regressions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 5-run Mode B re-baseline measurement

**Files:**

- Create: 25 forensic artifacts under `docs/superpowers/measurements/2026-05-21-cce16-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` for N = 1..5

### Why re-measure

Every CCE-12/CCE-14/CCE-15 baseline measured **default Claude Code with an injected prompt** because the source-collector agent never loaded. Now that the manifest is fixed, this is the first valid measurement of the actual source-collector prompt's behavior in production. The window is identical to CCE-12/CCE-14/CCE-15 (`a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on this repo) so deltas are directly comparable.

The 5-run procedure replicates the measurement scaffolding CCE-15 Task 5 used: invoke `dispatch_subagent` directly with `DOCS_AGENT_DEBUG_DIR` set, capture all five artifact files per run, do not run downstream subagents.

- [ ] **Step 1: Prepare the measurement script**

Run this exact Python snippet as a one-shot. It does not need to be committed — it's a measurement harness, not production code. Save to `/tmp/cce16_measure.py`:

```python
#!/usr/bin/env python3
"""CCE-16 5-run Mode B re-baseline. Mirrors CCE-15 Task 5
procedure: dispatch source-collector with the identical inputs used
in CCE-12/14/15 baselines, capture forensic artifacts, leave the rest
of the orchestrator alone."""

import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/theo/Projects/engineering-docs-agent")
sys.path.insert(0, str(REPO_ROOT / "scripts"))
os.chdir(REPO_ROOT)

import orchestrator_runner as runner

OUT_DIR = REPO_ROOT / "docs" / "superpowers" / "measurements"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INPUTS = {
    "last_sha": "a2a9dba273bf5ef82ef6d450d3eb44ee27e04681",
    "head_sha": "b2cd07af5cdcf0482515fc757a6ee6def3af278d",
    "repo": {"owner": "theoju", "name": "engineering-docs-agent"},
    "pr_branch_filter": ["docs-agent/*"],
}

for i in range(1, 6):
    print(f"=== run {i} starting ===")
    tmp_debug = Path(f"/tmp/cce16-run{i}")
    if tmp_debug.exists():
        shutil.rmtree(tmp_debug)
    tmp_debug.mkdir(parents=True)
    os.environ["DOCS_AGENT_DEBUG_DIR"] = str(tmp_debug)

    reasons: list[str] = []
    t0 = time.time()
    try:
        result = runner.dispatch_subagent(
            "source-collector",
            INPUTS,
            dry_run_dir=None,
            cwd=REPO_ROOT,
            out_reasons=reasons,
        )
    except Exception as exc:
        result = None
        reasons.append(f"exception:{type(exc).__name__}:{exc}")
    elapsed = time.time() - t0

    artifacts = sorted(tmp_debug.iterdir())
    print(f"run {i} done in {elapsed:.1f}s — result type: {type(result).__name__}")
    print(f"  reasons: {reasons}")
    print(f"  artifacts: {[p.name for p in artifacts]}")

    for src in artifacts:
        ext = src.name.split(".", 1)[1]
        dest = OUT_DIR / f"2026-05-21-cce16-run{i}-source-collector.{ext}"
        shutil.copy(src, dest)
        print(f"  copied -> {dest.name}")
    print()

print("done")
```

- [ ] **Step 2: Run the 5 measurement runs**

```bash
.venv/bin/python /tmp/cce16_measure.py 2>&1 | tee /tmp/cce16-measure.log
```

Expected per-run output shape:

```
=== run N starting ===
run N done in ~15-45s — result type: dict (or NoneType if rescued/failed)
  reasons: [...]
  artifacts: ['<ts>-source-collector.meta.json', '...stdout.txt', '...stream.jsonl', '...stderr.txt', '...prompt.txt']
  copied -> 2026-05-21-cce16-run1-source-collector.meta.json
  ...
```

Do **not** halt the run on failures; the measurement captures the actual behavior including failures. Continue all 5 runs even if some return None.

- [ ] **Step 3: Verify artifact counts**

```bash
ls docs/superpowers/measurements/2026-05-21-cce16-run*-source-collector.* | wc -l
# Expected: 25 (5 runs × 5 file types)
ls docs/superpowers/measurements/2026-05-21-cce16-run*-source-collector.stream.jsonl | wc -l
# Expected: 5
```

If counts are wrong, inspect `/tmp/cce16-measure.log` for the failing run, re-run that single run by setting the loop bound to just that index, and re-copy.

- [ ] **Step 4: Sanity-check that the agent loaded in every run**

```bash
for f in docs/superpowers/measurements/2026-05-21-cce16-run*-source-collector.stream.jsonl; do
  head -1 "$f" | python3 -c "
import sys, json
e = json.loads(sys.stdin.read())
agents = e.get('agents', [])
has = 'engineering-docs-agent:source-collector' in agents
errors = e.get('plugin_errors')
print(f\"  {'OK' if has and not errors else 'FAIL'}  agents-has-sc={has}  plugin_errors={errors}\")
"
done
```

Expected: all 5 lines say `OK  agents-has-sc=True  plugin_errors=None`. If any line says FAIL, the manifest fix did not propagate — return to Task 1 Step 7 and diagnose.

- [ ] **Step 5: Commit Task 2 (artifacts only, no doc yet)**

```bash
git add docs/superpowers/measurements/2026-05-21-cce16-run*-source-collector.*
git commit -m "$(cat <<'EOF'
docs(CCE-16): 5-run Mode B re-baseline forensic artifacts

First valid measurement of the actual source-collector subagent in
production — all prior baselines (CCE-12, CCE-14, CCE-15) measured
default Claude Code with an injected prompt because the plugin
manifest was rejected by the loader.

Same dispatch window as CCE-12/14/15 for direct comparability:
a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d
on theoju/engineering-docs-agent.

Summary doc + supersession notices follow in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: New baseline doc + supersession notices

**Files:**

- Create: `docs/superpowers/measurements/2026-05-21-cce16-real-baseline.md`
- Modify: `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md` (prepend supersession block)
- Modify: `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md` (prepend supersession block)
- Modify: `docs/superpowers/measurements/2026-05-20-cce12-source-collector-tool-use-baseline.md` (prepend supersession block — only the headline/dispatch-validity section, the diagnostic infrastructure conclusions remain valid)

### Why supersede rather than rewrite

The CCE-12/14/15 baselines documented genuine work and real findings — they shouldn't be deleted. But the **conclusions about source-collector behavior** are invalid because the agent never executed. Prepending a clearly-formatted supersession block at the top of each doc preserves the audit trail while warning future readers.

- [ ] **Step 1: Analyze the 5 new runs**

For each run, extract the relevant fields. Run this command and capture the table for the new baseline doc:

```bash
for i in 1 2 3 4 5; do
  meta="docs/superpowers/measurements/2026-05-21-cce16-run${i}-source-collector.meta.json"
  stdout="docs/superpowers/measurements/2026-05-21-cce16-run${i}-source-collector.stdout.txt"
  python3 -c "
import json, pathlib
meta = json.loads(pathlib.Path('$meta').read_text())
stdout = pathlib.Path('$stdout').read_text()
tu = meta.get('tool_use', {})
print(f'run $i:')
print(f'  returncode: {meta.get(\"returncode\")}')
print(f'  total_calls: {tu.get(\"total_calls\")}')
print(f'  by_name: {tu.get(\"by_name\")}')
print(f'  stop_reason: {tu.get(\"stop_reason\")}')
print(f'  duration_ms: {tu.get(\"duration_ms\")}')
print(f'  stdout (first 200 chars): {stdout[:200]!r}')
"
done
```

Hand-classify each run into one of:

- **Category A** (zero tool calls — agent emitted empty arrays without invoking tools)
- **Category B** (tools called but result discarded — empty or wrong output despite real fetches)
- **Data returned** (canonical JSON with non-empty `prs` array, indicating real PRs fetched and serialized)

- [ ] **Step 2: Write the new baseline doc**

Create `docs/superpowers/measurements/2026-05-21-cce16-real-baseline.md` with this exact structure. Fill in the table cells from the Step 1 analysis. The headline + delta sections describe outcomes; do **not** invent numbers — use the actual measurements.

```markdown
# CCE-16: Source-Collector Real Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-16](https://designitright.atlassian.net/browse/CCE-16)
**Branch:** `fix/CCE-16-plugin-manifest-author`
**Date:** 2026-05-21
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent (IDENTICAL to CCE-12, CCE-14, CCE-15)
**PR filter:** `docs-agent/*`
**Intervention:** `.claude-plugin/plugin.json` `author` field corrected from string to object — plugin now loads, all 7 subagents available.

## Critical context

This is the **first valid measurement** of the source-collector agent in production. CCE-12, CCE-14, and CCE-15 all measured default Claude Code with an injected user prompt because the plugin manifest was rejected at load time by the Claude CLI's Zod schema validator (`author: expected object, received string`). The agent definition in `agents/source-collector.md` never executed in any prior baseline. See [CCE-16](https://designitright.atlassian.net/browse/CCE-16) for the smoking-gun forensic capture and root-cause analysis.

## Per-run table

| Run | total_calls | by_name | category | gh pr list? | returncode | duration_ms |
| --: | ----------: | ------- | -------- | :---------: | ---------: | ----------: |
|   1 |      <FILL> | <FILL>  | <FILL>   |   <FILL>    |     <FILL> |      <FILL> |
|   2 |      <FILL> | <FILL>  | <FILL>   |   <FILL>    |     <FILL> |      <FILL> |
|   3 |      <FILL> | <FILL>  | <FILL>   |   <FILL>    |     <FILL> |      <FILL> |
|   4 |      <FILL> | <FILL>  | <FILL>   |   <FILL>    |     <FILL> |      <FILL> |
|   5 |      <FILL> | <FILL>  | <FILL>   |   <FILL>    |     <FILL> |      <FILL> |

Raw artifacts: `2026-05-21-cce16-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Headline

<2-3 sentence summary describing the actual behavior. Honest reporting required — do not paper over failures.>

## Delta vs prior (invalid) baselines

The CCE-12/CCE-14/CCE-15 column comparisons in those docs are **not meaningful** for source-collector behavior because the agent never ran. The only valid comparison is CCE-16 against expectations from the prompt design itself: agent should invoke `gh pr list --base <branch> --state merged --search 'head:docs-agent/*'` (or `gh api repos/.../pulls` equivalent) and return PRs merged in the window matching the branch filter.

## Acceptance check

- Target: ≥4 of 5 runs return canonical JSON with non-empty `prs` array (real PR data from the dispatch window).
- Target: ≥4 of 5 runs invoke `gh pr list` or `gh api repos/.../pulls`.
- Target: zero runs with `plugin_errors` populated (manifest validation).

Result: **<FILL: PASS / PARTIAL PASS / FAIL>** — <one sentence justification referencing the per-run table>.

## What this rewrites

Three prior baseline docs document failure modes attributed to source-collector prompt non-compliance. All three measurements actually captured default Claude Code responding (or refusing) to the orchestrator's `<inputs>` framing. Specifically:

- **CCE-12** (stream-json instrumentation baseline) — the instrumentation worked. The "Category A" classification of 4/5 runs as "zero tool calls" was correct as raw data but mis-attributed to source-collector behavior. The agent was never loaded.
- **CCE-14** (prompt-hardening intervention) — the prompt restructure to a gated checklist + Forbidden §5 was a correct intervention against the documented failure modes, but it **never executed** in any measurement run. The 2/5 Category-A persistence reported in the CCE-14 baseline was default Claude Code's behavior, not a non-compliant source-collector.
- **CCE-15** (root-cause sweep: rescue + schema + setting-sources) — the schema-tightening (Fix #2) and prose-tolerant rescue (Fix #3) remain valid defense-in-depth measures regardless. The `--setting-sources project,local` swap (Fix #1) was unnecessary for the plugin-load problem (which had a different root cause), but `--setting-sources project,local` is still desirable for SessionStart hook exclusion and is retained.

CCE-16 is the first measurement that exercises the actual source-collector prompt. If failures appear here, they are **real** source-collector failures worth designing against.

## Follow-up

<Conditional on outcome — list specific follow-up tickets the result implies. If real data is returned reliably, the agent is healthy and CCE-15's defenses are sufficient. If Category-A bypass persists at high rate, CCE-14's prompt-hardening logic may need rework now that it can actually be tested. If a specific new failure mode appears, file a new CCE ticket for it.>
```

The `<FILL: ...>` placeholders MUST be replaced with the actual measurement outcomes before commit. Do not commit a doc with literal `<FILL>` strings. If you cannot determine a value, surface it to the user before continuing.

- [ ] **Step 3: Prepend supersession block to CCE-14 baseline**

Read the existing file:

```bash
head -10 docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md
```

Edit `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md`. Insert this block **immediately after the first H1 line** (`# CCE-14: ...`) and before any other content:

```markdown
> **⚠ SUPERSEDED — see [CCE-16 real baseline](2026-05-21-cce16-real-baseline.md).**
>
> This measurement is invalid for source-collector prompt-compliance conclusions. The plugin manifest (`.claude-plugin/plugin.json`) had an invalid `author` field that caused the Claude CLI loader to silently reject the entire plugin, so every dispatch in this baseline ran as default Claude Code responding to an injected user prompt — the source-collector agent never executed. The prompt-hardening intervention described below is a sound design but was untested by this baseline; see CCE-16 for the first real measurement.
>
> The diagnostic infrastructure (stream-json capture, forensic artifacts) and the prompt-restructure intervention itself are retained — only the conclusions about agent behavior in §Headline, §Acceptance check, and §Delta are invalidated.
```

- [ ] **Step 4: Prepend supersession block to CCE-15 baseline**

Same procedure for `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md`. Insert immediately after the first H1 line:

```markdown
> **⚠ SUPERSEDED — see [CCE-16 real baseline](2026-05-21-cce16-real-baseline.md).**
>
> The "PARTIAL PASS" verdict in this baseline is misattributed. The schema-tightening (Fix #2) and prose-tolerant rescue (Fix #3) results are valid as defenses against any dispatch's output, but the source-collector agent itself never executed in these runs — the plugin manifest's `author` field violated the Claude CLI loader's Zod schema and the plugin was rejected silently. The 4/5 Category-A bypass rate reported below was default Claude Code's behavior, not a non-compliant source-collector. See CCE-16 for the first real measurement of agent behavior.
>
> The CCE-15 code changes (rescue helper, schema additionalProperties:false, --setting-sources project,local) are retained on main as valid defense-in-depth — only the agent-behavior conclusions are invalidated.
```

- [ ] **Step 5: Prepend supersession block to CCE-12 baseline**

Locate the CCE-12 baseline doc (search for it if the exact filename is uncertain):

```bash
ls docs/superpowers/measurements/2026-05-20-cce12-*.md
```

For each `.md` file matching that pattern, insert this narrower notice immediately after the first H1 line:

```markdown
> **⚠ PARTIAL SUPERSESSION — see [CCE-16 real baseline](2026-05-21-cce16-real-baseline.md).**
>
> The stream-json instrumentation infrastructure described in this baseline (forensic artifact capture, tool-use summary, DOCS_AGENT_DEBUG_DIR gate) is sound and remains in production. However, the conclusions classifying source-collector behavior into Category A / B / C are based on dispatches where the plugin manifest was rejected by the Claude CLI loader (the `author` field violated the schema), so every dispatch in this baseline ran as default Claude Code, not the source-collector agent. The classification distribution is real data about default Claude Code's response to the orchestrator's `<inputs>` framing, but should not be read as source-collector compliance behavior. See CCE-16.
```

- [ ] **Step 6: Run schema tests one more time to confirm nothing broke**

```bash
.venv/bin/pytest tests/schemas/ -v
```

Expected: all schema tests pass, including the new `test_plugin_manifest_schema.py`.

- [ ] **Step 7: Commit Task 3**

```bash
git add docs/superpowers/measurements/2026-05-21-cce16-real-baseline.md \
        docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md \
        docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md \
        docs/superpowers/measurements/2026-05-20-cce12-*.md
git commit -m "$(cat <<'EOF'
docs(CCE-16): baseline writeup + supersession notices on CCE-12/14/15

CCE-16 is the first valid measurement of source-collector behavior;
all prior baselines captured default Claude Code with an injected
prompt because the plugin manifest was rejected at load time. Adds
the corrected baseline doc with per-run table + headline + delta vs
expectations, and prepends supersession notices to the three affected
prior baselines so future readers don't have to dig through commit
history to discover the conclusions are invalid.

The code changes from CCE-15 (rescue helper, additionalProperties:false,
--setting-sources project,local) remain in production as valid
defense-in-depth; only the agent-behavior conclusions are invalidated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Closeout

After Task 3 commits, the branch should have three CCE-16 commits totaling: 1 schema file + 1 test file + 1 manifest edit + 25 forensic artifacts + 1 baseline doc + 3 supersession edits.

Standing directive: pre-authorized to invoke `/ship` once all three tasks are committed and tests pass. /ship will run the standard 8-stage flow against the branch (test → verify → simplify → review → commit (idempotent skip) → push+PR → Jira).

After /ship completes and the PR opens, also update the CCE-16 Jira description (via Atlassian MCP `editJiraIssue` or a closeout comment) to correct the root-cause framing. The current ticket body still describes the `--setting-sources` hypothesis that was disproved during systematic-debugging — replace the "Root-cause hypothesis" section with: "**Real root cause:** `.claude-plugin/plugin.json` `author` field was a string; the Claude CLI plugin loader's Zod schema requires it to be an object. Bug present since commit 628a7262 (2026-05-19). Confirmed by stream-json `plugin_errors` field showing identical message in all 5 CCE-15 baseline forensic captures and today's verification dispatch. One-line fix in Task 1 of this plan."

---

## Self-review notes

Spec coverage: the plan covers all elements the user requested in Option A — manifest fix (Task 1), 5-run re-baseline (Task 2), CCE-15 baseline doc supersession (Task 3 Step 4), plus the natural extension of also superseding CCE-12 and CCE-14 since the same root cause invalidates them.

Type/path consistency: schema file path (`templates/plugin_manifest.schema.json`) and test path (`tests/schemas/test_plugin_manifest_schema.py`) match the existing `templates/state.schema.json` + `tests/schemas/test_state_schema.py` convention. Artifact filename pattern (`2026-05-21-cce16-run<N>-source-collector.<ext>`) matches the CCE-15 convention exactly.

Out-of-scope items deliberately NOT included:

- A pre-flight assertion in `dispatch_subagent` that checks `plugin_errors` on every run (cost: latency tradeoff). Worth a separate CCE-17 if the re-baseline reveals more silent-failure surface.
- Tightening the `jira_issues.items` schema (raised in CCE-15 Stage 2 review). Worth a separate small ticket.
- Updating the CCE-14 prompt design itself. The intervention design is still sound; we just need to actually test it (which CCE-16 does).
