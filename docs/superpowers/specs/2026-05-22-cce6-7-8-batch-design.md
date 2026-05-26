# CCE-6 / CCE-7 / CCE-8 batch design

**Status:** approved 2026-05-22; per-ticket plans next.
**Jira:** CCE-6, CCE-7, CCE-8 (all Bug, all Medium, all currently in Backlog).
**Predecessor:** `docs/superpowers/specs/2026-05-21-post-second-run-defects-design.md` deferred these three as "needs Phase-1 root-cause investigation." Direct reading of the tickets shows each already has a clear root cause and complete acceptance criteria — no Phase-1 work is actually required. This spec records the sequencing decision and the one real design call (CCE-6 live-test execution policy).

---

## Scope confirmation

All three tickets were filed 2026-05-20 with detailed acceptance criteria. Restating each in one sentence:

- **CCE-6 — Live pytest gate.** Add `@pytest.mark.live` marker (default-skip), one live test per dispatch path (e.g. `notifier` happy path + full orchestrator smoke against a committed fixture repo), CI workflow that runs `pytest --live` on tag pushes only.
- **CCE-7 — Per-agent `--allowedTools`.** Parse each `agents/<name>.md`'s `tools:` YAML frontmatter; `dispatch_subagent` passes only that agent's declared tools to `--allowedTools` instead of the union currently used. Agents with no `tools:` frontmatter get no `--allowedTools` flag (default permissioning).
- **CCE-8 — Plugin marketplace registration.** Move `marketplace.json` to `.claude-plugin/marketplace.json` AND add the missing required `owner` block so `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent` succeeds. README gains a one-paragraph "Install from local clone" section.

The originally-filed tickets are the source of truth for acceptance criteria. This spec adds only what the tickets don't already say.

---

## Sequence and rationale

Three separate cycles, smallest first:

1. **CCE-8** (smallest)
2. **CCE-7** (medium)
3. **CCE-6** (largest, has unique cost/auth surface)

Rationale:

- The three tickets touch entirely disjoint file sets (`.claude-plugin/marketplace.json` + `README.md` for CCE-8; `scripts/` dispatch logic + agent `.md` files for CCE-7; `tests/` + `.github/workflows/` for CCE-6). Zero merge-conflict risk if interleaved, but sequencing simplifies review and Jira tracking.
- Smallest-first means the first PR is the easiest review and proves the per-ticket cycle works for this batch before larger changes land.
- CCE-6 last because it introduces an external-cost dependency (live API calls, API key in env, CI workflow on tag pushes). Landing it after CCE-7/CCE-8 means the live-test gate validates against final-state code.

Each cycle: branch off updated main → subagent-driven-development → /ship → user merges → Jira to Done → next.

---

## CCE-6 live-test execution policy

This is the one real design decision unique to this batch.

CCE-6 builds infrastructure that costs ~$1-3 per full pass to actually execute. Three options for when live tests run during development:

| Option                                                          | When                                    | Cost   | Trade-off                                         |
| --------------------------------------------------------------- | --------------------------------------- | ------ | ------------------------------------------------- |
| A: Build gate only; verify with `pytest -m live --collect-only` | Never during dev                        | $0     | Wiring bugs surface at first release-tag CI run   |
| B (chosen)                                                      | Once at end of CCE-6 impl, before /ship | ~$1-3  | One-time cost; needs `ANTHROPIC_API_KEY` in shell |
| C: Run after each acceptance criterion                          | ~5-10x during impl                      | ~$5-15 | Catches wiring bugs immediately; expensive        |

**Decision: Option B.** Run live tests once at the end of CCE-6 implementation, before opening the PR. Validates end-to-end without runaway cost. If the user prefers $0 dev cost, fall back to Option A — CI on the next release tag becomes the validating run.

Concretely, the CCE-6 plan's final task before /ship will be:

1. Ensure `ANTHROPIC_API_KEY` is set in the shell.
2. Run `pytest -m live` once.
3. Confirm exit 0; the `notifier` happy path and orchestrator smoke both produce parseable output.
4. If anything fails, fix the wiring (not the live tests themselves) and re-run.

The plan must include a clear "do not run live tests automatically on `pytest` or in CI" assertion; the `-m live` opt-in is the only path.

---

## Architecture per ticket (one paragraph each)

### CCE-8 — Plugin marketplace registration

Move `marketplace.json` from repo root to `.claude-plugin/marketplace.json`. Add the required `owner` object (per CLI v2.1.145's schema — verify exact shape via `claude plugin validate` output during implementation). Decide explicitly: the old root `marketplace.json` is deleted (single source of truth), not kept as a legacy copy. README's Self-hosting section gains a 3-4 line "Install from local clone" subsection showing `claude plugin marketplace add .` + `claude plugin install <name>@<marketplace>`. Acceptance: `claude plugin validate /Users/theo/Projects/engineering-docs-agent` clean exit + `claude plugin marketplace add` succeeds.

### CCE-7 — Per-agent `--allowedTools`

Add a helper in `scripts/dispatch_subagent.py` (or wherever `dispatch_subagent` lives) that parses the `tools:` YAML frontmatter from `agents/<name>.md`. Cache the result module-level (or per-call — YAGNI, single-call is fine). `dispatch_subagent` consults the cache for the agent being dispatched and passes ONLY those tools to `--allowedTools`. Behavior when `tools:` is absent: omit `--allowedTools` entirely (default permissioning, matching CCE-7 acceptance #3). Unit tests cover (a) `dispatch_subagent("pr-summarizer", ...)` argv contains `--allowedTools Read` exactly, and (b) an agent with no `tools:` frontmatter resolves to no `--allowedTools` flag. The current `_AGENT_ALLOWED_TOOLS` constant is preserved as a default-deny floor / documented fallback.

### CCE-6 — Live pytest gate

Add `pytest.mark.live` to `pytest.ini` or `pyproject.toml`'s `markers` list. Add a default-skip behavior: a `conftest.py` hook (or `pytest_collection_modifyitems`) that auto-skips `live`-marked tests unless `-m live` or `--live` is passed. Create the fixture repo at `tests/fixtures/live-repo/` — a committed mini-repo with one PR's worth of commits, recorded `last_sha` and `head_sha` in a seed state file, so source-collector returns deterministic input. At least one live test per dispatch path: (1) `dispatch_subagent("notifier", ...)` with a trivial digest, assert rc=0 + JSON-parseable response; (2) full `orchestrator_runner.run(...)` against the fixture, assert exit 0 and ≥1 PR consumed. Add `.github/workflows/release.yml` (or equivalent) that runs `pytest --live` on tag pushes only. README + CHANGELOG document the cost (~$1-3/pass) and CI cadence (tag-push only).

---

## What this spec does NOT change

- The three tickets' acceptance criteria stand as-is.
- The runtime filter in `scripts/orchestrator_runner.py` is unchanged (none of the three tickets need it).
- The `_AGENT_ALLOWED_TOOLS` constant stays (CCE-7 explicitly preserves it as a fallback).
- No new runtime dependencies. Existing pyyaml (already used by `state_io.py`) parses the agent frontmatter for CCE-7.

---

## Risks and mitigations

- **CCE-8 `owner` schema drift.** The CLI's marketplace schema may have changed between v2.1.145 and the current installed version. The plan must include a Task 1 step that runs `claude plugin validate` to capture the current exact error before defining the `owner` block. If the schema requires more than `owner`, surface and adjust.
- **CCE-7 frontmatter parse-error handling.** Malformed YAML in an agent `.md` file should produce a clear error at dispatch time, not silently fall back to the union. Plan must include a test for this case.
- **CCE-6 cost overrun.** Option B caps dev cost at one full pass. If the live test runner accidentally loops (e.g., retry-on-failure with no max attempts), cost could blow up. The plan must include explicit "no auto-retry" wiring in the live test path.
- **CCE-6 fixture repo determinism.** If `last_sha`/`head_sha` are not pinned to specific commits in the committed fixture repo, source-collector's output drifts and the test becomes flaky. Plan must include a step that verifies `git -C tests/fixtures/live-repo log --oneline` matches the seed state exactly.

---

## Validation strategy

- **CCE-8:** `claude plugin validate` clean + manual `claude plugin marketplace add .` smoke test by the user during PR review.
- **CCE-7:** Unit tests for per-agent argv shape (at least 2 agents — one with declared tools, one without). No live test needed; the change is observable in `dispatch_subagent`'s constructed argv.
- **CCE-6:** The live test IS the dogfood. Option B's end-of-impl run is the validation pass.

After all three ship, no further orchestrator dogfood run is needed — none of these tickets affects orchestrator behavior in a way that the existing 235-test suite doesn't already exercise. (CCE-6 ADDS live coverage; CCE-7's argv change is unit-tested; CCE-8 is packaging-only.)

---

## Implementation handoff

The next step is to invoke `writing-plans` to create three separate implementation plans:

- `docs/superpowers/plans/2026-05-22-cce8-plugin-marketplace-fix.md`
- `docs/superpowers/plans/2026-05-22-cce7-per-agent-allowed-tools.md`
- `docs/superpowers/plans/2026-05-22-cce6-live-pytest-gate.md`

The plans land on this same `docs/CCE-6-7-8-batch-design` branch; implementation branches off updated main, one per ticket, in the sequence above.
