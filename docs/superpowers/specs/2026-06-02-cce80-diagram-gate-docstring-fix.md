# CCE-80 follow-up — scaffold_workflow.py docstring fenced-block fix

**Status:** Draft (ready for review)
**Tracker:** CCE-80 (this fix lands as an additional commit on PR #101)
**Branch:** `chore/CCE-80-template-workflow-run-refresh`
**Type:** Bug fix — CI gate unblock
**Author:** Theo Jungeblut + Claude (Opus 4.7, 1M context)

## Context

CCE-80's PR #101 lands `scripts/scaffold_workflow.py` — the deterministic per-host cron rewriter. The new file's module docstring contains a `Usage:` example whose 4-space-indented body has bare `--FLAG VALUE` tokens (`--out PATH`, `--template PATH`).

`mkdocstrings[python]>=0.25` (declared in `templates/docs-requirements.txt`) renders that docstring into `api/reference/scaffold_workflow.md`. `mkdocs-autorefs` (a transitive dep of mkdocstrings) then scans the rendered page, sees `--out PATH` as prose, and tries to resolve it as a cross-reference target. Resolution fails; autorefs emits a WARNING; `mkdocs build --strict` (run by the `diagram-gate` job in `.github/workflows/docs.yml:60`) promotes that lone warning to exit 1.

PR #101's CI is currently:

- `actionlint` — pass
- `pytest (3.11)` — pass
- `pytest (3.12)` — pass
- `diagram-gate` — fail (this fix)

The `diagram-gate` check is **not branch-protected** on `main` — only `pytest (3.11/3.12)` and `actionlint` are. PR #101 is technically mergeable today. But cutting `v0.5.0` with a red gate on the merge commit pollutes main's CI history. This spec captures the surgical content fix to land before merge.

Empirically confirmed by local repro on this tree (2026-06-02 07:55 PDT):

- `mkdocs build --strict` → `WARNING - mkdocs_autorefs: api/reference/scaffold_workflow.md: from .../scripts/scaffold_workflow.py:1: (scaffold_workflow) Could not find cross-reference target '--out PATH'` → `Aborted with 1 warnings in strict mode!`
- Byte-for-byte identical to CI run 26827087952's failed-job log.
- `git log -p -- scripts/scaffold_workflow.py` confirms the `Usage:` block was introduced in the same commit that created the file. This is not a regression from a prior green state; it is a new-file content defect.

## Goal

Make `mkdocs build --strict` exit 0 on `chore/CCE-80-template-workflow-run-refresh` so `diagram-gate` turns green and PR #101's CI history is clean before the `v0.5.0` tag-cut.

## Non-goals

- Do not relax CI strictness (`--strict` stays on).
- Do not pin or downgrade `mkdocs-autorefs` / `mkdocstrings` / `griffe`. The diagnosis confirmed this is new-file content, not a transitive dep regression.
- Do not modify argparse argument-parsing behavior. The docstring is human documentation; argparse is not wired to it in `scaffold_workflow.py`.
- Do not modify `diagram-gate`'s `paths:` trigger, branch-protection state, or required-check list. Those are separate follow-up tickets (see Out of scope).
- Do not modify any test in `tests/setup/test_scaffold_workflow.py`. The fix is content-only.
- Do not modify `tests/skills/test_setup_skill_md.py`. That suite greps for the literal path `scripts/scaffold_workflow.py` in SKILL.md; the path is unchanged by this fix and the suite stays green.
- Do not add a defensive lint that bans bare `--FLAG VALUE` tokens in `scripts/*.py` docstrings. Worth doing; tracked separately so this PR stays surgical.

## Architecture

A single-file content edit. No new modules, no new files, no new tests.

Affected file: `scripts/scaffold_workflow.py` lines 1–12.

### Current docstring

```python
"""Render templates/workflow-run.yml for a host repo.

Rewrites the cron line to a deterministic per-host minute so 100 hosts
don't all hit :07 UTC. Everything else is byte-for-byte copy.

Usage:
    python scripts/scaffold_workflow.py --owner OWNER --repo REPO \\
        [--template PATH] [--out PATH]

--template defaults to the plugin's templates/workflow-run.yml; "-" reads stdin.
--out defaults to stdout.
"""
```

### Fixed docstring

```python
"""Render templates/workflow-run.yml for a host repo.

Rewrites the cron line to a deterministic per-host minute so 100 hosts
don't all hit :07 UTC. Everything else is byte-for-byte copy.

Usage::

    python scripts/scaffold_workflow.py --owner OWNER --repo REPO \\
        [--template PATH] [--out PATH]

`--template` defaults to the plugin's templates/workflow-run.yml; `-` reads stdin.
`--out` defaults to stdout.
"""
```

### Two changes

1. **Code-fence the Usage example** (line 6 change). Replace `Usage:` with `Usage::` (reST double-colon literal-block syntax). mkdocstrings renders the next indented block as a literal `<pre><code>`, taking the body out of autorefs' parsing scope. This protects both the bare-flag tokens on the command line (line 7) AND the square-bracket-wrapped tokens on line 8 (`[--template PATH]`, `[--out PATH]`). The latter is in scope but is not matched by the empirical-probe grep `^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+` because the bracket precedes the `--`; the fence protects them anyway.
2. **Inline-backtick the prose flag references** (lines 10–11 change). Wrap `--template`, `--out`, and `-` (the stdin sentinel) in single backticks. These lines are prose, not part of the fenced block, so they need their own inline `<code>` wrapping. This is strictly necessary — without it, lines 10–11 retain bare `--template` / `--out` tokens that autorefs would warn on once the line-7 token stops shadowing them.

Net result: zero bare `--FLAG`-shape tokens in the docstring for autorefs to resolve, whether in fenced or prose context.

### Implementation trap (load-bearing)

The blank line between `Usage::` (line 6) and the indented command block (lines 8–9) is **load-bearing**. If the blank line is accidentally omitted during editing, the reST literal-block directive fires silently and the indented content may render as a continuation paragraph with the `--FLAG` tokens re-exposed as prose. Verify with `mkdocs build --strict` (acceptance criterion 2).

### Why `Usage::` over a triple-backtick fence

- `Usage::` is the reST convention that mkdocstrings already understands; it renders as a single `:` in HTML with the next indented block becoming a `<pre>` code block.
- Triple-backtick fences would render correctly today but show literal fence characters if anyone later wires `description=` to the module docstring in argparse. `Usage::` is the defensive choice.

## Components

None affected besides the single docstring. Static type checks, runtime behavior, public API, CLI surface — all unchanged.

## Data flow

`mkdocs.yml:27` sets `mkdocstrings.handlers.python.paths: ["scripts"]` — this is the ONLY directory mkdocstrings scans for autorefs targets in this repo. `scripts/gen_ref_pages.py:7-8` (`SCAN_DIR = "scripts"`) mirrors the constraint. Files in `agents/`, `tests/`, and top-level Python files are excluded from rendering and cannot produce autorefs warnings. The empirical-probe grep `^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+` confirmed no other `--FLAG VALUE` shapes exist in `scripts/*.py`, so this single-file fix is exhaustive for the rendered scope.

Rendering chain: `mkdocstrings` reads `__doc__` from `scripts/scaffold_workflow.py` → renders into `api/reference/scaffold_workflow.md` → `mkdocs-autorefs` scans the rendered page → the `Usage::` block is rendered as `<pre>` (skipped by autorefs); the prose lines below render with their `--template` / `--out` tokens already inside inline `<code>` (also skipped) → no warning emitted → `mkdocs build --strict` exits 0 → `diagram-gate` job step succeeds.

## Error handling

N/A — this is a content fix, not a logic change. No new error paths, no new fallbacks, no new validation.

## Acceptance criteria

1. **CI gate green:** `diagram-gate` on PR #101's HEAD turns green in the auto-rerun triggered by the fix commit.
2. **Local strict build clears all autorefs warnings:** `mkdocs build --strict` from repo root exits 0. The previously-reported `--out PATH` warning is gone AND no new warnings appear (the line-8 `[--template PATH]` / `[--out PATH]` square-bracket tokens must also be silent). Remaining stderr is only `INFO` lines plus the pre-existing benign MkDocs-2 advisory.
3. **`--help` smoke:** `python3 scripts/scaffold_workflow.py --help` exits 0 and produces argparse's auto-generated help text (the docstring is NOT included today — `argparse.ArgumentParser()` at `scripts/scaffold_workflow.py:58` has no `description=` kwarg). This criterion is a smoke test only: if someone later wires `description=__doc__`, the `--help` output should still be readable (no orphan `"""`, no fence-rendering oddities). If a future PR adds the wiring, that PR owns updating this criterion to assert specific rendered text.
4. **No test regressions:** `python3 -m pytest` reports the same `passed` / `skipped` / `failed` counts as a pre-fix baseline captured immediately before the edit. (Do not hard-code numbers here; the branch may have gained or lost tests since the spec was written.)
5. **No drift on required checks:** `pytest (3.11)`, `pytest (3.12)`, `actionlint` all remain green on PR #101 after the fix commit.

## Testing approach

No new unit tests. The autorefs warning surfaces only at the mkdocs-build layer, which already runs in `diagram-gate`. The fix is verified by:

- **Local repro before fix.** Confirmed today; reproduces the CI failure verbatim.
- **Local strict build after fix.** Must exit 0 (acceptance criterion 2).
- **CI rerun.** Push the fix commit; observe `diagram-gate` on the new run turns green.

A defensive lint (e.g. `tests/lint/test_no_bare_flag_tokens_in_docstrings.py` that greps `scripts/*.py` for the `^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+` shape) is explicitly out of scope here. Tracked as a follow-up ticket so this PR stays surgical.

## Out of scope (file as follow-up tickets before merging PR #101)

These were flagged by the reviewer panel during brainstorming. None block this fix; each deserves its own spec.

- **`CCE-XX-gate-required`** — Promote `diagram-gate` to a branch-protection-required check on `main` so future docstring regressions can't slip through.
- **`CCE-XX-paths-trigger-narrowing`** — Narrow `docs.yml`'s `paths:` trigger so `diagram-gate` does not fire on PRs that only touch `docs/runbooks/**` or `docs/superpowers/**`. The current trigger fires the gate on any `docs/**` change, which over-includes operator docs that the gate cannot meaningfully validate.
- **`CCE-XX-runbook-polish`** — Update `docs/runbooks/cce80-host-migration.md` with: CHANGELOG-update step, rollback playbook (`gh release delete v0.5.0 --cleanup-tag --yes`), two-clock SLA framing (release.yml live-tests ~5–10 min; host pickup up to ~60 min), and tag-cut-misfire recovery procedure.
- **`CCE-XX-docstring-flag-lint`** — Defensive test that fails CI when any `scripts/*.py` docstring contains a `--FLAG VALUE` shape outside a fenced or inline code block. Prevents this class of bug recurring. Implementation hint: grep for the pattern `^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+` across `scripts/*.py`; the pattern matches the line-7 prose form. Note this pattern does NOT catch the bracket-prefixed form `[--FLAG VALUE]` (line 8 of the current file) — the lint should add a second pattern `\[--[a-z][a-z_-]+\s+[A-Z][A-Z_]+\]` to cover that shape, OR rely on `mkdocs build --strict` as the canonical check.

## Implementation outline (for the planning skill)

1. Capture the pre-fix test baseline: `python3 -m pytest --tb=no -q 2>&1 | tail -1` → record the `N passed, M skipped` line for use in acceptance criterion 4.
2. Edit `scripts/scaffold_workflow.py` lines 1–12 per the Architecture section's fixed docstring. Preserve the blank line between `Usage::` and the indented command block (load-bearing — see Implementation trap).
3. Run `mkdocs build --strict` → confirm exit 0 and warning list is empty (acceptance criterion 2).
4. Run `python3 scripts/scaffold_workflow.py --help` → visually inspect output against acceptance criterion 3.
5. Run `python3 -m pytest --tb=short -q` → confirm same `passed` / `skipped` counts as step 1's baseline.
6. Stage `scripts/scaffold_workflow.py`. Commit on `chore/CCE-80-template-workflow-run-refresh` with:
   - **Subject:** `fix(CCE-80): wrap scaffold_workflow.py Usage docstring to clear mkdocs_autorefs --out PATH warning`
   - **Body:** two bullets describing the `Usage::` fence + inline-backtick changes; one bullet citing PR #101 + the v0.5.0 tag-cut unblock as the rationale.
   - **Trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (standing convention for this branch's commits — see existing 24 commits on the same branch for examples).
   - **Forbidden flags:** no `--amend`, no `--no-verify`, no force-push.
7. `git push origin chore/CCE-80-template-workflow-run-refresh`.
8. Observe `diagram-gate` rerun on PR #101. Confirm green (acceptance criterion 1).
9. (Out of this spec) Merge PR #101 + cut `v0.5.0` + execute host-migration runbook.

## Risk

Very low. Pure content change in a docstring; no logic, no API, no test, no CI config touched. The most concrete risk is `--help` output regression — caught by acceptance criterion 3.

## Rollback

If the fix accidentally breaks `--help` output or fails to clear the autorefs warning, revert the single commit (`git revert <sha>`) and reopen brainstorming for an alternative docstring shape — for example a fully fenced triple-backtick block, or rephrasing `Usage:` in pure prose without any flag tokens.

The revert is safe to push directly. `diagram-gate` is not branch-protected, so a revert that re-introduces the failing warning does NOT block future merges to `main` — it just restores the red gate that PR #101 carried before this fix. No force-push, no CI-config change, no branch-protection bypass needed.
