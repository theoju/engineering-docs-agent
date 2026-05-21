# CCE-10 — Source-collector canonical-shape compliance: design

**Status:** Draft for implementation
**Date:** 2026-05-20
**Branch:** `feat/CCE-10-source-collector-canonical-shape`
**Depends on:** CCE-9 (v0.1.4 — diagnostic infra), CCE-11 (v0.1.4 — self-host harness)
**Blocks:** CCE-12 (tool-use diagnostics — needs canonical shape stable first)

## Problem

Source-collector is the first agent in the orchestrator chain. When it fails, every downstream stage (`spec-extractor`, `page-author`, `lint-runner`, etc.) is blocked. Across CCE-9 Phase 1 + CCE-9 H4 validation + CCE-11 dogfood, source-collector has failed schema validation in **5 out of 5 captured Mode B runs**. The bundled prompt + dispatch fix in this design closes the three confirmed root causes.

## Evidence base (Phase 1 — confirmed root causes)

Three orthogonal root causes have been confirmed with direct evidence. No further instrumentation is needed before implementing fixes.

### Root cause 1 — Stop-verify hook contaminates subagent stdout

`~/.claude/hooks/stop-verify.sh` fires inside the `claude -p ... --agent source-collector` child session and returns `{"decision":"block","reason":"Before yielding, verify your work..."}`. The child agent then emits a "Verification statement:" prose preamble before its JSON. `dispatch_subagent` calls `json.loads(stdout)` on the entire stdout string, which fails when the preamble is present.

**Evidence:**

- Runs 1 and 2 of CCE-9 H4 validation begin with verbatim "Verification statement:" / "Verification:" prose. Source: `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md`.
- Run 3's `notes` field cites "the 25 files / 18567 lines flagged by the stop hook" — direct quote of the hook's trigger output.
- The hook source at `~/.claude/hooks/stop-verify.sh:22` documents the escape hatch: `[[ "${CLAUDE_STOP_VERIFY:-1}" == "0" ]] && exit 0`.

### Root cause 2 — Status-report reflex overrides all canonical-shape signals

Despite three explicit canonical-shape declarations in the source-collector prompt (`## Output schema (canonical)`, legacy `## Output contract`, and the CCE-9 Procedure step 0), the agent reflexively emits `{"status":"idle", "reason":..., "commits_analyzed":0, "branches_scanned":0, ...}` when reporting "nothing to process."

**Evidence:** 4/4 captured Mode B runs (CCE-9 Phase 1 + CCE-9 H4 validation runs 1-3) emit this shape verbatim. Source: same measurement docs.

### Root cause 3 — F1 rename: `jira_issues` → `issues`

When a populated `last_sha` defeats root cause 2 (the agent does attempt the canonical shape), it still renames the `jira_issues` array to `issues`, failing schema validation.

**Evidence:** CCE-11 self-host dogfood run with seeded v0.1.0 SHA produced `{"prs":[],"commits":[],"issues":[],"partial":false,"partial_reasons":[]}` → `schema_invalid: source-collector: 'jira_issues' is a required property`. Source: Jira CCE-10 comment 11022.

## Out of scope (split to CCE-12)

The CCE-11 dogfood also revealed F2 — agent returns `prs:[]` despite 6 mergeable PRs in the scan window. This is a tool-invocation failure (different class from output-shape failure) and is tracked in CCE-12. CCE-12 logically depends on CCE-10 landing first so the schema-validation failure mode does not mask the tool-use measurement.

## Design

Three independent fixes shipped as one PR, each addressing one confirmed root cause.

### Architecture

The three fixes live in two files. Component 1 below covers the code fix; Component 2 covers both prompt fixes (they share the same file edit).

```
                    ┌────────────────────────────────┐
                    │  orchestrator_runner.run()     │
                    └──────────┬─────────────────────┘
                               │ dispatch_subagent("source-collector", inputs)
                               ▼
            ┌──────────────────────────────────────────────────────┐
            │  scripts/orchestrator_runner.py: dispatch_subagent   │
            │                                                      │
            │  [Component 1 — code]                                │
            │    env = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}   │
            │    subprocess.run(argv, env=env, ...)                │
            └──────────┬───────────────────────────────────────────┘
                       │ claude -p <prompt> --agent source-collector ...
                       ▼
            ┌──────────────────────────────────────────────────────┐
            │  source-collector subagent (Sonnet)                  │
            │                                                      │
            │  Reads: agents/source-collector.md                   │
            │    [Component 2 — prompt edit A]                     │
            │      Add "## Forbidden outputs" subsection:          │
            │        - {"status":"idle",...} → forbidden           │
            │        - top-level "issues" key → forbidden          │
            │        - prose preamble → forbidden                  │
            │    [Component 2 — prompt edit B]                     │
            │      Remove legacy `## Output contract`              │
            │      block (current lines 66-99)                     │
            │                                                      │
            │  stop-verify hook fires →                            │
            │    sees CLAUDE_STOP_VERIFY=0 → exits 0 (no block)    │
            │  Emits: {"prs":[…], "jira_issues":[…]} only          │
            └──────────────────────────────────────────────────────┘
```

### Components

#### Component 1 — `dispatch_subagent` env passthrough

**File:** `scripts/orchestrator_runner.py`
**Change:** Add an explicit `env` dict to the `subprocess.run` invocation that copies `os.environ` and overlays `CLAUDE_STOP_VERIFY=0`. Always-on for every subagent dispatch.

Code shape:

```python
env = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}
run_kwargs["env"] = env
```

**Rationale for "always on" rather than per-agent opt-in:** Every subagent today is a JSON emitter whose stdout is parsed by `json.loads`. The stop-verify hook is fundamentally incompatible with that protocol — a prose preamble breaks parsing regardless of which agent triggered it. A per-agent knob would be uniform `false` across all 7 agents today. YAGNI.

**Future-proofing:** If a future subagent legitimately needs verification, we revisit then. The change here is small enough to undo or generalize.

#### Component 2 — `agents/source-collector.md` prompt changes

**File:** `agents/source-collector.md`

Two edits:

1. **Remove** the legacy `## Output contract` block (current lines 66-99). It duplicates the canonical schema with a redundant example and includes a tie-breaker meta-instruction ("the schema is authoritative if they disagree") that itself signals ambiguity to the model.

2. **Add** a new `## Forbidden outputs` subsection placed between `## Output schema (canonical)` and `## Procedure`. The subsection names — with concrete examples — the bad shapes the agent has been observed to invent:
   - `{"status":"idle", "reason":..., "commits_analyzed":0, ...}` and variants
   - Top-level `issues` / `jira` / `tickets` arrays (the canonical name is `jira_issues`)
   - Any prose preamble before or after the JSON object

The subsection uses imperative-negative phrasing ("NEVER emit…", "MUST be named `jira_issues`") with literal bad-shape JSON blocks. The CCE-9 H4 validation doc established that purely positive specification (three places saying "use canonical shape") was insufficient; the addition of explicit negative examples is what's new.

#### Component 3 — Measurement protocol

**Artifact:** `docs/superpowers/measurements/YYYY-MM-DD-cce10-canonical-shape-validation.md` (new — date stamp is the date the measurement is captured)

5 consecutive Mode B runs against the CCE-11 self-host harness:

- `DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate` set before each run
- State reset to seeded `state.example.json` (head_sha = v0.1.0 commit `1f4563c2…`) before each iteration
- Each run captures stdout to a numbered file (run1, run2, …, run5)

Pass criterion (binary): **5/5 runs emit canonical `{"prs":[…],"jira_issues":[…]}` AND pass `validate_and_parse` schema validation**. Anything less fails the ship criterion and triggers iteration.

### Data flow

1. Parent orchestrator process inherits the user's normal environment (`CLAUDE_STOP_VERIFY` unset, hook would fire).
2. `dispatch_subagent` builds a child env dict with `CLAUDE_STOP_VERIFY=0` overlaid.
3. `subprocess.run` launches `claude -p ... --agent source-collector` with that env.
4. The child Claude session inherits the env. When its stop hook checks the variable at `~/.claude/hooks/stop-verify.sh:22`, it sees `"0"` → exits 0 → emits no block decision → no verification prose preamble.
5. The agent emits its JSON response cleanly. `json.loads(stdout)` succeeds.
6. With the prompt forbidden-outputs subsection, the agent emits the canonical `{"prs":[…],"jira_issues":[…]}` shape (the bad shapes it would otherwise reflex into are explicitly forbidden).
7. `validate_and_parse` passes; the orchestrator advances to the next pipeline stage.

### Error handling

| Failure mode                                                          | Detection                                                                     | Response                                                                                                                                                                                     |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Env var doesn't disable the hook (subprocess.run env not propagating) | Run 1 stdout still has "Verification statement:" preamble                     | Investigate `subprocess.run` env-passing; the hook source already confirms it honors `CLAUDE_STOP_VERIFY=0`, so failure here points to a parent-process bug                                  |
| Prompt fix produces < 5/5 canonical-shape                             | Measurement run captures which runs failed and which shapes the agent emitted | Iterate on the forbidden-outputs subsection until 5/5 passes, or escalate to a more invasive structural change (option (c) from the brainstorming session, or rewriting source-collector.md) |
| Drift lint (`tests/agents/test_schema_md_sync.py`) fails              | CI / local pytest run                                                         | Should not happen — the canonical `## Output schema` block is untouched; only the legacy redundant block is removed and a non-schema subsection is added                                     |

### Testing

#### Unit tests

**New: `tests/orchestrator/test_dispatch_subagent_env.py`** (~30 lines)

- Monkeypatch `subprocess.run` to capture its `kwargs`
- Call `dispatch_subagent("source-collector", {"last_sha": "abc", "head_sha": "def", "repo": {"owner": "x", "name": "y"}}, dry_run_dir=None)`
- Assert `kwargs["env"]["CLAUDE_STOP_VERIFY"] == "0"`
- Assert `kwargs["env"]["PATH"] == os.environ["PATH"]` (sanity-check `os.environ` was extended, not replaced)

#### Drift lint (existing)

- `tests/agents/test_schema_md_sync.py` — re-run after prompt edits. Should still pass.

#### Integration measurement

- Lives outside the pytest suite. Manual ceremony per the existing CCE-9 pattern.
- Captured artifacts committed alongside the spec at the measurement doc above.

### Commit ordering (TDD)

Each fix lands as a separate commit, failing test first:

1. **Commit 1 — code + test:** `test_dispatch_subagent_env.py` (failing) → env passthrough in `dispatch_subagent` (test passing). Independently shippable.
2. **Commit 2 — prompt:** edit `agents/source-collector.md` (remove legacy block + add forbidden-outputs subsection). Drift lint must pass.
3. **Commit 3 — measurement:** 5 Mode B runs documented; ship criterion met → commit measurement doc + raw stdouts.

This ordering means Commit 1 is independently valuable (it unblocks ALL subagent JSON parsing, not just source-collector) and ships even if Commits 2/3 turn out to need iteration.

## Acceptance criteria

1. `dispatch_subagent` passes `CLAUDE_STOP_VERIFY=0` to every subprocess invocation. Verified by `test_dispatch_subagent_env.py`.
2. `agents/source-collector.md` no longer contains the legacy `## Output contract` block (current lines 66-99).
3. `agents/source-collector.md` contains a `## Forbidden outputs` subsection that names the three observed bad shapes with concrete JSON examples.
4. Drift lint (`tests/agents/test_schema_md_sync.py`) passes.
5. Full pytest suite passes.
6. 5/5 consecutive Mode B runs against the CCE-11 self-host harness with seeded v0.1.0 SHA emit canonical `{"prs":[…],"jira_issues":[…]}` and pass schema validation. Captured at `docs/superpowers/measurements/<measurement-date>-cce10-canonical-shape-validation.md`.

## Effort estimate

~2 hours total:

- 20 min: Commit 1 (test + env passthrough)
- 30 min: Commit 2 (prompt edits)
- 60 min: Commit 3 (5 Mode B runs + measurement doc)
- 30 min: code review iteration, /ship ceremony

## Out of scope (explicit)

- F2 `prs:[]` tool-use failure → CCE-12 (depends on this ticket landing)
- Moving empty-`last_sha` rule into `## Output schema (canonical)` (option c from brainstorming) — redundant with the forbidden-outputs subsection's `{"status":"idle",...}` listing
- Per-agent stop-verify configuration knob — YAGNI; all 7 subagents are JSON emitters today
- End-to-end Mode B run that exercises spec-extractor + page-author downstream — separate follow-up after CCE-10 + CCE-12 both land
