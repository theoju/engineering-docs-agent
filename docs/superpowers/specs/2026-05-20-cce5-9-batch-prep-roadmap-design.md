---
title: CCE-5 through CCE-9 — Batch prep roadmap
status: approved
created: 2026-05-20
owner: theo
jira:
  - CCE-5
  - CCE-9
  - CCE-6
  - CCE-7
  - CCE-8
related:
  - CCE-4 (v0.1.2 schema enforcement — preconditions CCE-6's live tests)
---

# CCE-5 through CCE-9 — Batch prep roadmap

## 1. Goal

Sequence the second post-v0.1.2 hardening wave across five independent tickets. Each ticket ships as its own PR through `/ship`; this roadmap is the connective tissue — dependency analysis, locked order, per-ticket scope summaries, and inter-ticket interaction notes.

The trigger was the Mode B smoke test against ADIS on 2026-05-20 after CCE-4 (v0.1.2) merged. The new validator surfaced a specific `schema_invalid: source-collector: 'prs' is a required property` reason in `partial_reasons`, alongside a leftover `unsafe_page_path: docs/connectors/foo.md` from a pre-CCE-4 run that the orchestrator's carry-forward logic had preserved. Both observations motivated tickets in this batch.

**Audience:** operator (Theo), future-you reading the journal, any contributor browsing the CCE-5..9 range and wondering why this order.

## 2. Non-goals

- A single mega-PR landing all 5 tickets. Each ticket is independently revertable; bundling would create a large review surface for low compounding value.
- Re-litigating the CCE-4 design. Schema enforcement is the floor this builds on.
- Brainstorming new tickets beyond CCE-5..9. Out-of-band findings get filed; this roadmap doesn't expand mid-execution.

## 3. Architecture: dependency graph + locked order

```
CCE-5 (state hygiene)
   └──→ CCE-9 (source-collector investigation)   ← cleaner signal once CCE-5 lands
            └──→ CCE-6 (--live pytest gate)      ← institutionalizes CCE-9's measurement
                       (independent) CCE-7 (per-agent tools)   ← orthogonal hardening
                       (independent) CCE-8 (marketplace.json)  ← only blocks external installs
```

**Locked order:** `CCE-5 → CCE-9 → CCE-6 → CCE-7 → CCE-8`

Rationale (signal-to-effort, compounding):

1. **CCE-5 first** — clears stale `partial_reasons` on new-run init. Without it, every CCE-9 measurement run is mixed with leftover noise from earlier runs. Already observed the failure mode during the post-CCE-4 sandbox test.
2. **CCE-9 second** — addresses the root cause CCE-4 made visible. A clean state from CCE-5 lets you read source-collector behavior precisely. Investigation may produce a small prompt change or a documented null result + follow-up ticket.
3. **CCE-6 third** — institutionalizes the measurement protocol from CCE-9 into CI. Pre-conditioned by CCE-4's `dispatch_validated` tuple return (already shipped).
4. **CCE-7 fourth** — defense-in-depth `--allowedTools` narrowing. Independent of the above; sequenced fourth because it doesn't unblock anything and the union grant is functional today.
5. **CCE-8 fifth** — only urgent when external testers want a `--plugin-dir`-free install. Today's workaround works; defer until external publishing is in scope.

Each ticket = one PR through `/ship`, matching the CCE-2/3/4 pattern. Branches named `feat/CCE-<N>-<slug>` (or `fix/CCE-<N>-<slug>` for bug-flagged tickets).

## 4. CCE-5 — partial_reasons carry-forward hygiene

### 4.1 Problem

`scripts/orchestrator_runner.py:208-216` unconditionally preserves `partial` and `partial_reasons` across runs:

```python
carried_partial = state.get("current_run", {}).get("partial", False)
carried_reasons = state.get("current_run", {}).get("partial_reasons", [])
state["current_run"] = {
    "started_at": now,
    "head_sha": head_sha,
    "partial": carried_partial,
    "partial_reasons": list(carried_reasons),
}
```

The intent (don't lose context across attempts that haven't been promoted yet) is reasonable. The consequence (stale reasons live forever until `verify_runner` promotes `current_run` → `last_successful_run`) is the operator-UX bug observed on 2026-05-20: a `source_collector_invalid: returned None` reason from a pre-CCE-4 run leaked into a post-CCE-4 run.

### 4.2 Root cause

No allowlist distinguishes transient (`*_invalid: returned None`, `schema_invalid: *`, `gh_failed`, network errors) from persistent (`unsafe_page_path` for a path still in the agent's output, `dismissed_gap_flags` references). All carry forward.

### 4.3 Approach

Invert the default — clear `partial_reasons` on new-run init. If a condition is still true this run, the pipeline's normal flow re-adds it organically. Transient one-off failures disappear.

### 4.4 Acceptance criteria

1. New-run init writes `partial: false`, `partial_reasons: []` unconditionally.
2. Persistent conditions re-accumulate naturally as the run encounters them (proven by existing tests that already exercise these conditions).
3. Transient reasons do NOT carry forward.
4. Future carry-forward of specific reason classes must be opt-in via an explicit allowlist (none today).
5. New unit test: after a failed run, a fresh run starts with `partial_reasons: []`; persistent conditions re-surface from the pipeline's own logic.
6. No regression in `test_verify_runner.py::test_verify_runner_writes_state_even_on_dispatch_failure` (try/finally state-write contract).

### 4.5 Out of scope

- Time-based reason expiry (separate concern; only file if needed).
- Dashboard surfacing.

### 4.6 Risk + effort

- **Risk:** Low. 5-line region + 1-2 tests. Conceptual risk ("what if we lose a real persistent condition") is answered by criterion 4.4.2.
- **Effort estimate:** ~2-3 hours, ~6 tasks (TDD red → green → audit → commit).

## 5. CCE-9 — source-collector reliability investigation

### 5.1 Problem

Post-CCE-4 Mode B run against ADIS produced `schema_invalid: source-collector: 'prs' is a required property` even though the canonical schema is now embedded in the source-collector system prompt (CCE-4 option #2). CCE-4's validation layer caught it; the prompt-sharpening layer didn't prevent it. Every off-contract response wastes LLM tokens + writes a partial state.

### 5.2 Systematic-debugging Phase 1 — evidence

- N=1 observation of off-contract response _after_ CCE-4 (with canonical schema in prompt).
- N=1 observation of `source_collector_invalid: returned None` _before_ CCE-4 (likely the same underlying behavior, just pre-validation).
- Source-collector's schema is the largest of seven (deep nested PR objects with 10+ optional fields).
- source-collector has the most permissive tools list of the seven agents (`Bash, Read, WebFetch`).
- ADIS state had `last_sha: ""` — no scan-window anchor.

### 5.3 Hypotheses (ranked by likelihood)

| #      | Hypothesis                                                                                                          | How to test                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **H1** | Legacy `## Output contract` block creates conflicting signal alongside the new `## Output schema (canonical)` block | Remove the legacy block from `agents/source-collector.md`. Measure rate.       |
| H2     | Schema too verbose; falls out of active context after `Bash` tool calls                                             | Add a "final reminder" line at end of prompt with one-line schema restatement. |
| H3     | Tools list invites the agent to summarize observations rather than emit canonical shape                             | Post-mortem: log full stdout + reasoning trace for one bad-shape response.     |
| H4     | Empty `last_sha` confuses the agent into emitting a "no work" summary shape                                         | Seed `last_successful_run.head_sha` with a real SHA before measuring.          |

### 5.4 Approach (Phase 3 — Hypothesis and Testing)

1. **Baseline:** 5 Mode B runs against ADIS, same configuration (empty `last_sha`, post-CCE-5 state). Record canonical-shape rate.
2. **Test H1 only this PR:** remove the legacy `## Output contract` block from `agents/source-collector.md`. Commit.
3. **Re-measure:** 5 more Mode B runs.
4. **Decide:**
   - If correctness rate improved meaningfully: land the change. File CCE-N follow-up if H2/H3/H4 worth testing later.
   - If no improvement: revert, document the null result, file CCE-N for the next hypothesis. Don't blindly chain H2 in this PR.

### 5.5 Acceptance criteria

1. Baseline of ≥5 runs documented (commit message body or a measurement-results .md file).
2. H1 tested with one before/after comparison.
3. Either the change lands with measurable improvement OR a documented null result + follow-up ticket.
4. No other agent .md modified in this PR.
5. If the change lands, the drift-prevention lint (`test_schema_md_sync.py`) still passes (the schema _block_ must remain JSON-equivalent to the schema _file_ — that's independent of the prose section being removed).

### 5.6 Out of scope

- Retry-on-schema-invalid (deferred at CCE-4 design time; revisit only if the residual rate is too high after this investigation).
- Testing H2/H3/H4 in the same PR.
- Other agents' prompts.

### 5.7 Risk + effort

- **Risk:** Medium. Open-ended investigation; null result is possible.
- **Mitigation:** time-box to one working session; pre-commit to single-hypothesis testing; accept null result as a legitimate outcome.
- **Effort estimate:** ~3-4 hours, ~8 tasks (5 runs + analysis × 2 cycles + commit).

## 6. CCE-6 — --live pytest gate

### 6.1 Problem

The 158-test suite mocks `subprocess.run` for every `dispatch_subagent` test. Unit coverage is solid; integration coverage against the live `claude` CLI is zero. v0.1.0 shipped with `dispatch_subagent` calling a non-existent CLI surface — the bug only surfaced when Mode B was attempted by hand. One small live test would have caught it pre-merge.

### 6.2 Approach

1. Register a `live` marker in `pyproject.toml` `[tool.pytest.ini_options]`.
2. Add `tests/conftest.py` with a `--live` CLI option + auto-skip logic for `@pytest.mark.live` tests when the flag is absent.
3. Two live tests:
   - **Happy path:** invoke the cheapest agent (notifier with a trivial digest) via real `dispatch_validated`. Assert RC=0 + canonical JSON.
   - **Smoke:** full `orchestrator_runner.run(<tmp_repo>, dry_run_dir=None, no_pr=True)` against a committed fixture repo with one merged PR. Assert exit 0 + non-empty `prs` consumed.
4. Fixture repo at `tests/fixtures/live-repo/` — committed shallow clone with one merged PR + recorded `last_sha`/`head_sha` so source-collector's scan window is deterministic.
5. README + CHANGELOG: how to run; expected cost (~$1-3 per pass); CI runs on tag pushes only.
6. `.github/workflows/release.yml` (or new `live-tests.yml`) runs `pytest --live` on `release/*` tag pushes.

### 6.3 Acceptance criteria

1. `pytest -q` skips live tests; total runtime stays under 15s.
2. `pytest --live` runs them and passes against a normally-authenticated machine.
3. The smoke test fails loudly with a `schema_invalid:` reason if the model drifts — regression sentinel for CCE-4's promise.
4. CI workflow runs `pytest --live` on tag push, not per-PR push.
5. CHANGELOG documents the new command + cost expectation.

### 6.4 Out of scope

- Recording live responses for replay (separate CCE-N if cost becomes an issue).
- Per-agent live tests for all 7 agents (one happy + one smoke proves the pipeline end-to-end).

### 6.5 Risk + effort

- **Risk:** Medium. Per-pass cost (~$1-3 × CI runs); fixture-repo drift risk.
- **Mitigation:** tag-push gating; explicit cost notice in README.
- **Effort estimate:** ~4-5 hours, ~10 tasks (marker setup + conftest + 2 tests + fixture repo + CI workflow + docs).

## 7. CCE-7 — per-agent --allowedTools narrowing

### 7.1 Problem

`scripts/orchestrator_runner.py:65` declares `_AGENT_ALLOWED_TOOLS = ("Bash", "Read", "Write", "Edit", "WebFetch")` — the union across all 7 agents. Every dispatch passes this union, regardless of what the agent declared. A compromised or buggy prompt for, say, `pr-summarizer` (which only needs `Read`) can now invoke `Bash` or `Write`.

### 7.2 What each agent .md frontmatter declares

| Agent             | Declared `tools:`      |
| ----------------- | ---------------------- |
| pr-summarizer     | `Read`                 |
| gap-detector      | `Read`                 |
| notifier          | `Bash`                 |
| content-validator | `Bash, Read`           |
| publish-verifier  | `Bash, WebFetch`       |
| source-collector  | `Bash, Read, WebFetch` |
| page-author       | `Read, Edit, Write`    |

PyYAML is already a runtime dep (`scripts/state_io.py:8`), so frontmatter parsing is free.

### 7.3 Approach

1. Add a module-level helper `_load_agent_tools(agent_name: str) -> tuple[str, ...]` that lazily parses `agents/<name>.md` YAML frontmatter `tools:` once, caches the result by name.
2. `dispatch_subagent` calls `_load_agent_tools(name)` and passes only those tools to `--allowedTools`.
3. If the agent declares no `tools:` field → omit `--allowedTools` entirely (relies on default permissioning).
4. Keep `_AGENT_ALLOWED_TOOLS` as a documented fallback for unknown agent names (defense in depth).

### 7.4 Acceptance criteria

1. Argv inspection: `dispatch_subagent("pr-summarizer", ...)` passes `--allowedTools Read` (not the full union).
2. Argv inspection: `dispatch_subagent("page-author", ...)` passes `--allowedTools "Read Edit Write"`.
3. Unit test: an agent .md missing a `tools:` field → no `--allowedTools` argv (not the union, not a crash).
4. Frontmatter parse failure (malformed YAML) → log + fall back to `_AGENT_ALLOWED_TOOLS`; don't crash.
5. No regression in the 158-test baseline.

### 7.5 Out of scope

- Adding new tool declarations to agent .md files (separate concern).
- Per-agent `--permission-mode`.
- Renaming `_AGENT_ALLOWED_TOOLS`.

### 7.6 Risk + effort

- **Risk:** Low. One new helper, one signature shift inside `dispatch_subagent`, ~5 new unit tests.
- **Effort estimate:** ~2-3 hours, ~6 tasks.

## 8. CCE-8 — marketplace.json fix

### 8.1 Problem

Two failures observed in Claude Code CLI v2.1.145:

1. `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent` → "Marketplace file not found at .../.claude-plugin/marketplace.json" — file is at repo ROOT, not in `.claude-plugin/`.
2. After moving the file: "Invalid schema: owner: Invalid input: expected object, received undefined" — schema requires an `owner` object that's absent.

Current `marketplace.json` body (241 bytes):

```json
{
  "name": "engineering-docs-agent-marketplace",
  "description": "Self-hosted marketplace for engineering-docs-agent.",
  "plugins": [
    { "name": "engineering-docs-agent", "source": ".", "version": "0.1.1" }
  ]
}
```

Missing `owner` field. `.claude-plugin/plugin.json` exists (correctly placed); `.claude-plugin/marketplace.json` does not.

### 8.2 Approach

1. Move `marketplace.json` → `.claude-plugin/marketplace.json`.
2. Add `owner` object. Exact shape confirmed during implementation via `claude plugin validate` output; likely `{ name, url, email }`.
3. Bump `plugins[0].version` from `0.1.1` to `0.1.2` (matches current tagged release).
4. README: add "Install from local clone" section showing the marketplace + install commands.
5. Delete the root `marketplace.json` (single source of truth).

### 8.3 Acceptance criteria

1. `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent` succeeds without errors.
2. `claude plugin install engineering-docs-agent@<marketplace-name>` succeeds and the 7 agents resolve without `--plugin-dir`.
3. `claude plugin validate /Users/theo/Projects/engineering-docs-agent` returns clean.
4. README has the install snippet.
5. Only one `marketplace.json` exists in the repo (in `.claude-plugin/`).

### 8.4 Out of scope

- Publishing to an external marketplace.
- `claude plugin tag` automation for versioned releases.

### 8.5 Risk + effort

- **Risk:** Low. Pure config + docs. Only unknown is the exact `owner` schema — resolved by reading the CLI error during implementation.
- **Effort estimate:** ~1-2 hours, ~4 tasks (move + edit + validate + README).

## 9. Inter-ticket interactions

**Sequencing wins (compounding):**

- **CCE-5 → CCE-9:** Clean state lets each Mode B measurement run read its own `partial_reasons` without leftover noise. The `len(reasons) == 1` invariant post-CCE-5 becomes a useful regression check during the H1 hypothesis test.
- **CCE-9 → CCE-6:** CCE-9 produces a measured baseline ("source-collector returns canonical shape X% of the time on N runs"). CCE-6's `--live` smoke test asserts the new floor. Without CCE-9, CCE-6's only assertion would be "exit 0" — weak.
- **CCE-4 → CCE-6 (already shipped):** `dispatch_validated`'s tuple return makes CCE-6's "schema_invalid" assertion trivial. Pre-conditioning done.

**Independence:**

- CCE-7 is orthogonal to all four others. Could ship in any slot. Placed fourth because it unblocks nothing.
- CCE-8 is orthogonal too. Placed fifth because the workaround (`--plugin-dir`) is acceptable for the inner-loop tester.

**Risks per ticket (consolidated):**

| Ticket | Risk                                                         | Mitigation                                                                              |
| ------ | ------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| CCE-5  | Loss of legitimately persistent context                      | Persistent conditions re-surface naturally — pipeline still hits them                   |
| CCE-9  | Inconclusive investigation across H1-H4                      | Time-box to one session; H1-only-per-PR; accept null result + follow-up                 |
| CCE-6  | Per-CI-run cost overrun                                      | Tag-push gating; one happy + one smoke; explicit cost notice in README                  |
| CCE-7  | Frontmatter parse failure breaks dispatch                    | Fall back to `_AGENT_ALLOWED_TOOLS` on parse error; don't crash                         |
| CCE-8  | Plugin install still fails after fix (unknown `owner` shape) | Read the CLI error during implementation; iterate until `claude plugin validate` passes |

## 10. Success criteria for the batch

1. All 5 tickets transitioned to Done in Jira.
2. 5 PRs merged through `/ship`, one per ticket.
3. Each PR independently revertable on `main`.
4. A `v0.1.3` tag after CCE-5 + CCE-9 land (or one tag per ticket — operator's call at the time).
5. CCE-9 either lands an empirically validated source-collector prompt change OR documents a null result + files a follow-up ticket.
6. CCE-6 `--live` gate proven by running it once against the real CLI and observing a clean pass.
7. CCE-8 verified by `claude plugin marketplace add .` succeeding from a fresh shell.

## 11. Effort summary

| Ticket    | Effort          | Tasks   | PR size                     |
| --------- | --------------- | ------- | --------------------------- |
| CCE-5     | 2-3 hours       | ~6      | Small                       |
| CCE-9     | 3-4 hours       | ~8      | Small (investigation-heavy) |
| CCE-6     | 4-5 hours       | ~10     | Medium                      |
| CCE-7     | 2-3 hours       | ~6      | Small                       |
| CCE-8     | 1-2 hours       | ~4      | Small                       |
| **Total** | **12-17 hours** | **~34** | **5 PRs**                   |

## 12. Next step

After this roadmap is approved + committed, invoke the `superpowers:writing-plans` skill to create the **CCE-5 implementation plan** (the first ticket in the locked order). The other four tickets get their own brainstorming + writing-plans cycle once CCE-5 ships.
