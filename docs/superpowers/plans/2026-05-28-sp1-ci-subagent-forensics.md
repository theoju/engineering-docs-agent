# SP-1 CI Subagent Forensics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOTE for this plan specifically:** scope is tiny (one file, ~12 lines net). The brainstorm's execution-handoff recommendation is **inline /ship**, not SDD. SDD is overkill for a one-task YAML edit.

**Goal:** Enable the orchestrator's built-in subagent forensic capture in the nightly workflow and upload the artifacts so every CI failure is self-diagnosing.

**Architecture:** The runner already writes per-subagent forensics (`prompt.txt`, `stdout.txt`, `stderr.txt`, `stream.jsonl`, `meta.json`) when `DOCS_AGENT_DEBUG_DIR` is set. SP-1 sets that env var on the existing "Run nightly authoring" step and adds a new `actions/upload-artifact@v4` step with `if: always()` so artifacts are captured even when the runner exits non-zero. No Python changes.

**Tech Stack:** GitHub Actions, `actions/upload-artifact@v4`, Python 3.11 (orchestrator unchanged), PyYAML (for the lint step).

---

## Task 1: Workflow YAML — env var + upload step

**Files:**

- Modify: `.github/workflows/docs-agent-nightly.yml` — augment the "Run nightly authoring" step (lines 67-78 as of branch HEAD `beafd3a`) and add a new "Upload subagent forensics" step immediately after it.

**Context for the engineer:**

- The runner's code path: `scripts/orchestrator_runner.py:357-372` (CCE-9 + CCE-12 comment block) describes the forensic capture mode. When `DOCS_AGENT_DEBUG_DIR` is set, `claude` is invoked with `--output-format stream-json --verbose` and 5 files are written per subagent dispatch.
- `runner.temp` is the standard GitHub Actions per-job scratch directory. Lives at `/home/runner/work/_temp` on ubuntu-latest.
- `if: always()` ensures the upload step runs even when "Run nightly authoring" exits 1 — that is the failure case we most want forensics for.
- `actions/upload-artifact@v4` differs from v3: v4 disallows duplicate artifact names within a single run, hence the `${{ github.run_id }}` suffix in the artifact name to keep concurrent runs distinct.

- [ ] **Step 1: Confirm current state of the file**

Run: `git status --porcelain && git rev-parse --abbrev-ref HEAD`

Expected: empty status (clean tree), branch `feat/CCE-41-subagent-forensics-ci`.

- [ ] **Step 2: Add `env:` block to the "Run nightly authoring" step**

Use the Edit tool with this exact replacement to inject the env var:

`old_string`:

```
      - name: Run nightly authoring
        # The runner reads .engineering-docs-agent/{config.yml,state.json},
        # computes the window vs HEAD, dispatches the pipeline, prepends
        # What's New, opens or append-commits to docs-agent/YYYY-MM-DD, and
        # writes state. Per spec §8: a partial run opens the PR anyway with
        # partial: true in the body — the workflow itself stays green so the
        # next nightly fire isn't suppressed by a red status.
        #
        # --repo-root is required by argparse; GITHUB_WORKSPACE is always set
        # by actions/checkout to the absolute path of the checked-out tree,
        # so no plumbing is needed beyond passing it through.
        run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"
```

`new_string`:

```
      - name: Run nightly authoring
        # The runner reads .engineering-docs-agent/{config.yml,state.json},
        # computes the window vs HEAD, dispatches the pipeline, prepends
        # What's New, opens or append-commits to docs-agent/YYYY-MM-DD, and
        # writes state. Per spec §8: a partial run opens the PR anyway with
        # partial: true in the body — the workflow itself stays green so the
        # next nightly fire isn't suppressed by a red status.
        #
        # --repo-root is required by argparse; GITHUB_WORKSPACE is always set
        # by actions/checkout to the absolute path of the checked-out tree,
        # so no plumbing is needed beyond passing it through.
        #
        # DOCS_AGENT_DEBUG_DIR (SP-1/CCE-41): toggle the runner's
        # forensic capture mode (see scripts/orchestrator_runner.py:357).
        # Per-dispatch prompt/stdout/stderr/stream/meta land in this dir
        # and are persisted past the runner via the upload step below.
        env:
          DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug
        run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"
```

- [ ] **Step 3: Insert the "Upload subagent forensics" step**

Use the Edit tool with this exact replacement to add the new step BEFORE the existing "Run summary" step:

`old_string`:

```
        run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"

      - name: Run summary
        if: always()
```

`new_string`:

```
        run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"

      - name: Upload subagent forensics
        # SP-1/CCE-41: persist the per-dispatch forensics the runner wrote
        # to DOCS_AGENT_DEBUG_DIR. `if: always()` runs the upload on success
        # AND failure — failures are the primary use case. `if-no-files-found:
        # warn` tolerates a runner step that fails before any dispatch happens
        # (config invalid, state corrupted) without breaking the workflow.
        # github.run_id is appended to the artifact name because v4 disallows
        # duplicate names within a single run.
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: docs-agent-subagent-forensics-${{ github.run_id }}
          path: ${{ runner.temp }}/docs-agent-debug/
          retention-days: 14
          if-no-files-found: warn

      - name: Run summary
        if: always()
```

- [ ] **Step 4: YAML lint**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs-agent-nightly.yml'))"`

Expected: no output (parse succeeds, exit 0). Any error here is a YAML structure problem — fix and re-lint before continuing.

- [ ] **Step 5: Inspect the diff**

Run: `git diff .github/workflows/docs-agent-nightly.yml`

Expected: 2 hunks. First hunk adds the `env:` block (lines around 78). Second hunk adds the entire "Upload subagent forensics" step before "Run summary". Net additions: ~22 lines (the spec's "~12 lines net" estimate was the literal `env:` value + `uses:` + `with:` block; comments add the rest).

If the diff includes anything else (e.g., other files, accidental indentation churn elsewhere), reset and retry.

- [ ] **Step 6: Run the pytest suite (sanity)**

Run: `python3 -m pytest -q`

Expected: `568 passed, 3 skipped` (current main count) — no Python changed, so this is a sanity check that nothing pre-existing is broken on this branch.

If the count differs by more than the 3 skipped, investigate before committing. The branch was created off `main` at `36d3743` with `pytest` green at that count.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/docs-agent-nightly.yml docs/superpowers/plans/2026-05-28-sp1-ci-subagent-forensics.md
git commit -m "$(cat <<'EOF'
feat(CCE-41): enable subagent forensics + upload-artifact in nightly cron

Turns on the runner's existing DOCS_AGENT_DEBUG_DIR forensic capture
mode (built in CCE-9 + CCE-12) and persists the artifacts past the
runner's destruction via actions/upload-artifact@v4 with 14-day
retention.

The runner already writes per-subagent prompt/stdout/stderr/stream/meta
files when the env var is set; this change enables that env var on the
"Run nightly authoring" step and adds an upload step with `if: always()`
so artifacts are captured on success AND failure. failure is the
primary use case (PR #54-style opacity).

No Python changes. Storage estimate per run: 0.2-0.4 MB; at 1/day with
14-day retention, under 6 MB peak.

Spec:  docs/superpowers/specs/2026-05-28-sp1-ci-subagent-forensics.md
Plan:  docs/superpowers/plans/2026-05-28-sp1-ci-subagent-forensics.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage:**

| Spec section                                                                                                        | Plan task                                                                                   |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| §1 Goal — emit forensics + persist as artifact                                                                      | Task 1 entirely                                                                             |
| §2 Architecture — env var, upload step, no-files-found tolerance                                                    | Task 1 Step 2 (env), Step 3 (upload + `if-no-files-found: warn`)                            |
| §3 YAML diff — the literal change                                                                                   | Task 1 Steps 2-3 use the spec's diff verbatim                                               |
| §4 Data flow + retention                                                                                            | `retention-days: 14` set in Step 3 matches spec                                             |
| §5 Failure modes — runner fails early / upload fails / collision                                                    | `if-no-files-found: warn` + `if: always()` + `${{ github.run_id }}` cover all three         |
| §6 Acceptance criteria 1-3 (YAML changes, parse, pytest)                                                            | Steps 2-3, Step 4, Step 6                                                                   |
| §6 Acceptance criteria 4-6 (post-merge artifact present, contains source-collector files, runner outcome unchanged) | Covered by post-merge smoke-test (NOT a plan task — verification step after `/ship` merges) |

No spec section uncovered. Acceptance 4-6 are intentionally post-merge — the plan ships the change; the smoke-test verifies it.

**Placeholder scan:** no TBD / TODO / "add appropriate" / "similar to" patterns. Every Edit step shows the exact `old_string` / `new_string`. The commit message is a complete HEREDOC.

**Type consistency:** no types/signatures to cross-check; this is workflow YAML. The artifact name + path are consistent between the upload step (`${{ runner.temp }}/docs-agent-debug/`) and the env var (`${{ runner.temp }}/docs-agent-debug`). The trailing slash on the upload `path:` is correct per `actions/upload-artifact@v4` docs — directory uploads accept trailing slash and treat the contents as the artifact root.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-sp1-ci-subagent-forensics.md`. The brainstorm's pre-stated recommendation was **inline /ship** for a one-task YAML edit. Two execution options:

**1. Inline /ship (recommended)** — Execute Task 1 inline in this session, then invoke `/ship` for the full pipeline (tests → verify → simplify → code-review → commit → push → PR → Jira). One task, six steps, ~5 minutes of work.

**2. Subagent-Driven Development** — Dispatch a fresh subagent for Task 1 with two-stage review (spec compliance + code quality). Overkill for a one-file YAML edit but available if you want the extra rigor.

Which approach?
