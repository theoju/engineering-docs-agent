# CCE-127 — App-Token Degrade-to-Partial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a failed GitHub App-token step degrade the nightly to a `partial` run on `GITHUB_TOKEN` instead of killing the job at step 2.

**Architecture:** The workflow's App-token step gains `continue-on-error: true`, which makes `steps.app-token.outcome` retain the true `failure` while `conclusion` is rewritten to `success` so the job proceeds. That outcome is exported to the orchestrator as `DOCS_AGENT_APP_TOKEN_STATUS`. The orchestrator reads it once at run start and, **only** for the literal string `failure`, records a blocking `app_token_unavailable` reason. Flipping `partial` reuses the existing `_maybe_auto_merge` interlock, so no new gate code is written.

**Tech Stack:** Python 3.11 (stdlib only), pytest, ruamel.yaml (test-only), GitHub Actions YAML.

## Global Constraints

- **Python: stdlib-first.** No new runtime dependency. `ruamel.yaml` is test-only and already in `requirements-dev.txt`.
- **Only the literal `"failure"` degrades a run.** `"skipped"`, `"success"`, and unset must all stay silent. `"skipped"` is the documented bare-host path and is the largest host population.
- **`_record_dispatch_reasons(state, reasons, *, ok: bool)` — `ok` maps directly onto `info_only`.** So `ok=False` is the BLOCKING case. This reads backwards; getting it wrong makes the reason advisory and silently defeats the whole ticket.
- **Env reads use `os.environ.get(...)`, never subscript.** `os` is already imported at `scripts/orchestrator_runner.py` line 9.
- **Docs cite code line-free:** `` `path/file.py` `` or `` `path/file.py:symbol` ``, never `path:line`.
- **Branch:** `feat/CCE-127-app-token-degrade-partial`, already created off `origin/main`. Never commit to `main`.
- **T4 (the death alarm) is OUT OF SCOPE** — split to CCE-128. Do not create `scripts/notify_run_death.py`.

---

### Task 0: Establish a runnable test environment

Nothing in this plan can be verified until this is done. `python3` is Homebrew 3.14.6; there is no `.venv`; and `pytest`, `yaml`, and `jsonschema` all fail to import. Critically, `tests/templates/test_workflow_run_parity.py` guards its imports with `pytest.importorskip`, so a missing `ruamel.yaml` makes the whole parity suite report **skipped** — which scrolls past looking like success. A green-looking run that tested nothing is the failure mode this task exists to prevent.

CI (`.github/workflows/test.yml`) runs a matrix over Python 3.11 and 3.12. We pin local to **3.11** so local and CI agree.

**Files:**

- Create: `.venv/` (git-ignored, not committed)
- Read only: `requirements-dev.txt`, `pyproject.toml`

**Interfaces:**

- Produces: a working `.venv/bin/python` on 3.11 with pytest, pyyaml, jsonschema, and ruamel.yaml. Every later task's verification step invokes `.venv/bin/python -m pytest`.

- [ ] **Step 1: Install CPython 3.11 via uv**

`uv` is present at `/Users/theo/.local/bin/uv`. Neither pyenv nor a brew `python@3.11` formula is installed, so uv is the path of least resistance.

```bash
cd /Users/theo/Projects/engineering-docs-agent
uv python install 3.11
```

- [ ] **Step 2: Create the virtualenv**

`--seed` is required: a bare `uv venv` creates a **pip-less** environment, and Step 3's `python -m pip install` then fails with "No module named pip". `--clear` is required because a stale Python 3.13 `.venv` from 2026-05-20 is already present — its `bin/python` is a dangling symlink to a Homebrew `python@3.13` that no longer exists, so it is listed by `find` but errors with ENOENT on execution.

```bash
uv venv --python 3.11 --seed --clear .venv
.venv/bin/python --version
```

Expected: `Python 3.11.x`

- [ ] **Step 3: Install dependencies, matching what CI installs**

`.github/workflows/test.yml` installs `pyyaml jsonschema pytest` then `-r requirements-dev.txt` (which supplies `ruamel.yaml`). Mirror it exactly.

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install pyyaml jsonschema pytest
.venv/bin/python -m pip install -r requirements-dev.txt
```

- [ ] **Step 4: Verify the parity suite RUNS rather than skips**

This is the whole point of the task. A skipped suite is not a passing suite.

```bash
.venv/bin/python -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: 8 tests, all **PASSED**. If you see `skipped`, a dependency is still missing — do not proceed.

- [ ] **Step 5: Verify the full baseline suite is green before changing anything**

```bash
.venv/bin/python -m pytest -q
```

Expected: all pass. Record the count. If anything fails now, it is pre-existing and must be reported before continuing — do not start CCE-127 on a red tree.

- [ ] **Step 6: Confirm `.venv` is git-ignored**

```bash
git status --porcelain | grep "^?? .venv" && echo "NOT IGNORED — fix .gitignore" || echo "ignored (good)"
```

Expected: `ignored (good)`. If it reports NOT IGNORED, add `.venv/` to `.gitignore` and commit that one-line change.

---

### Task 1: Orchestrator reads the status and records a blocking reason (T3)

**Files:**

- Modify: `scripts/orchestrator_runner.py` (insert in `run`, after the prior-run stale-check block, immediately before the `try:`)
- Test: `tests/orchestrator/test_pipeline_integration.py` (append; reuse the module's existing `_run_inproc` helper and the `conftest.py` fixtures `init_host` / `read_current_run`)

**Interfaces:**

- Consumes: `_record_dispatch_reasons(state, reasons, *, ok: bool) -> None` and `state["current_run"]` (keys `partial: bool`, `partial_reasons: list[str]`), both already defined.
- Produces: the reason string prefix `app_token_unavailable:` — Task 4's docs key off it.

**Placement is load-bearing.** `run` returns 2 at three points _before_ `state["current_run"]` is created (no config, invalid config, invalid state). The read must land **after** the `current_run` dict literal and **before** the `try:`. It cannot be hoisted: `state_io.add_partial` creates a stub `current_run` when the key is missing, and the dict literal would then overwrite it, silently swallowing the reason. It must also precede the `_maybe_auto_merge` callsite, which it does by roughly 690 lines.

- [ ] **Step 1: Read the insertion site to get exact surrounding bytes**

```bash
sed -n '1340,1370p' scripts/orchestrator_runner.py
```

You are looking for the `state["current_run"] = {...}` literal, then an `if prior_run is not None:` block, then a blank line, then `try:`. Insert between the end of that block and the `try:`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/orchestrator/test_pipeline_integration.py`. First read an existing test in that file to match its fixture-usage style, then add:

```python
def test_app_token_failure_flips_partial(tmp_path, monkeypatch, init_host, read_current_run):
    """CCE-127: a failed App-token step degrades the run instead of killing it."""
    init_host(tmp_path)
    monkeypatch.setenv("DOCS_AGENT_APP_TOKEN_STATUS", "failure")
    _run_inproc(tmp_path)
    cr = read_current_run(tmp_path)
    assert cr["partial"] is True
    assert any(r.startswith("app_token_unavailable:") for r in cr["partial_reasons"])


def test_app_token_skipped_is_silent(tmp_path, monkeypatch, init_host, read_current_run):
    """The bare-host path: no App configured is normal, not a degradation."""
    init_host(tmp_path)
    monkeypatch.setenv("DOCS_AGENT_APP_TOKEN_STATUS", "skipped")
    _run_inproc(tmp_path)
    cr = read_current_run(tmp_path)
    assert not any(r.startswith("app_token_unavailable") for r in cr["partial_reasons"])


def test_app_token_unset_is_silent(tmp_path, monkeypatch, init_host, read_current_run):
    """Unset must behave identically to skipped — local runs set nothing."""
    init_host(tmp_path)
    monkeypatch.delenv("DOCS_AGENT_APP_TOKEN_STATUS", raising=False)
    _run_inproc(tmp_path)
    cr = read_current_run(tmp_path)
    assert not any(r.startswith("app_token_unavailable") for r in cr["partial_reasons"])


def test_partial_run_skips_auto_merge():
    """CCE-127 rests entirely on this interlock — lock it explicitly."""
    import orchestrator_runner as runner

    outcome, reasons = runner._maybe_auto_merge(
        gh=None,  # never dereferenced: the partial guard short-circuits first
        pr_number=1,
        partial=True,
        fact_warnings=[],
        merge_settings={"policy": "auto"},
        build_workflow="docs-pages.yml",
        deadline=None,
        clock=lambda: 0.0,
    )
    assert outcome == {"merged": False, "reason": "partial_run"}
    assert reasons == [("auto_merge_skipped: partial_run", True)]
```

Note on the last test: `clock` is a **required** keyword-only parameter with no default. Omitting it raises `TypeError`.

Note on tests 2 and 3: they assert only the absence of `app_token_unavailable`, not `partial is False`. A dry-run may legitimately be partial for unrelated reasons; asserting the whole flag would make these tests fail for the wrong cause.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/orchestrator/test_pipeline_integration.py -k "app_token or auto_merge" -v
```

Expected: `test_app_token_failure_flips_partial` FAILS (no reason recorded). The two silent tests and the interlock test should already PASS — they assert existing behavior and are regression locks.

- [ ] **Step 4: Implement**

Insert immediately before the `try:` in `run`:

```python
    # CCE-127: the workflow's App-token step runs under continue-on-error, so a
    # failure to mint the installation token no longer kills the job — the run
    # degrades to secrets.GITHUB_TOKEN. Record that as a BLOCKING reason so
    # _maybe_auto_merge skips with "partial_run": a PR built on GITHUB_TOKEN
    # never fires host CI, and zero registered checks would otherwise read as
    # "nothing failed" and auto-merge unvalidated docs.
    #
    # Only the literal "failure" degrades the run. "skipped" is the documented
    # bare-host path (no DOCS_AGENT_APP_CLIENT_ID configured) and must stay
    # silent, as must "success" and unset. Placement is deliberate: after
    # current_run exists (add_partial would otherwise create a stub that the
    # dict literal above overwrites) and before the auto-merge decision.
    if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
        _record_dispatch_reasons(
            state,
            [
                "app_token_unavailable: GitHub App installation token could not "
                "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
                "fire on this PR. Verify the App is installed on this repo."
            ],
            ok=False,
        )
```

`ok=False` is the blocking case. Do not write `ok=True`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/orchestrator/test_pipeline_integration.py -k "app_token or auto_merge" -v
```

Expected: 4 PASSED.

- [ ] **Step 6: Run the full suite for regressions**

```bash
.venv/bin/python -m pytest -q
```

Expected: the Task 0 Step 5 baseline count, plus 4.

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_pipeline_integration.py
git commit -m "feat(CCE-127): app-token failure records a blocking partial reason

Only the literal failure value degrades the run; skipped (the bare-host
path) and unset stay silent. Flipping partial reuses the existing
_maybe_auto_merge interlock, so a GITHUB_TOKEN-degraded PR whose host CI
never fires cannot auto-merge unvalidated docs.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Template workflow degrades and exports the status (T1)

**Files:**

- Modify: `templates/workflow-run.yml` (App-token step; the `Run docs-agent` step's env block; the stale explanatory comments)

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `DOCS_AGENT_APP_TOKEN_STATUS` in the authoring step's env — Task 1's code reads it, Task 3's new parity test asserts it.

The env export must be at **step** scope, not job scope. GitHub's runtime validator rejects `steps.*` references in job-level `env:` because job-env resolves before any step runs. The file already documents this for `GH_TOKEN`.

- [ ] **Step 1: Add `continue-on-error` to the App-token step**

In the step named `Generate GitHub App installation token` (it has `id: app-token` and an `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` guard), add after the `if:`:

```yaml
# CCE-127: a failed token mint must not kill the job. continue-on-error
# makes `conclusion` report success so the job proceeds, while `outcome`
# retains the true `failure` — which is what we export below. Without
# this, the step aborts the job and the `||` fallback on the next step
# is never evaluated (GitHub only resolves it for a *skipped* step).
continue-on-error: true
```

- [ ] **Step 2: Export the outcome into the authoring step's env**

In the step named `Run docs-agent` (`id: docs-agent`), add to its existing `env:` block alongside `DOCS_AGENT_DEBUG_DIR` and `GH_TOKEN`:

```yaml
# CCE-127: "failure" here makes the orchestrator record a blocking
# app_token_unavailable reason, flipping the run to partial so
# auto-merge is skipped. "skipped" (no App configured) is silent.
DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}
```

- [ ] **Step 3: Correct the stale comments that encoded the original defect**

The file documents degradation as skipped-only — for example _"Without `DOCS_AGENT_APP_CLIENT_ID` set, this step is skipped and the workflow falls back to `secrets.GITHUB_TOKEN`"_ — and repeats that framing above the `token:` and `GH_TOKEN` lines. That wording is precisely what made the unreachable fallback look correct for two months. Update each to state both paths: skipped (never configured, silent) and failed (configured but broken, degrades to a partial run).

```bash
grep -n "skipped" templates/workflow-run.yml
```

Revise every hit that describes degradation.

- [ ] **Step 4: Lint the template explicitly**

CI does **not** lint this file — `.github/workflows/actionlint.yml` runs bare `actionlint -color`, which searches `.github/workflows/` only. Invoke it directly:

```bash
actionlint templates/workflow-run.yml
```

Expected: no output. If `actionlint` is not installed: `brew install actionlint`.

- [ ] **Step 5: Run the workflow-touching suites**

```bash
.venv/bin/python -m pytest tests/templates/ tests/ci/ -q
```

Expected: green. `tests/ci/test_workflow_auth_tier.py` and `tests/ci/test_workflow_node_runtime.py` both glob this file and must stay green; neither needs editing.

- [ ] **Step 6: Commit**

```bash
git add templates/workflow-run.yml
git commit -m "feat(CCE-127): template app-token step degrades instead of aborting

continue-on-error keeps outcome=failure observable while letting the job
proceed, and the authoring step exports it as DOCS_AGENT_APP_TOKEN_STATUS.
Also corrects the skipped-only degradation comments that made the
unreachable fallback read as correct.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Dogfood workflow reaches parity, and the parity tests enforce it (T2)

**Files:**

- Modify: `.github/workflows/docs-agent-nightly.yml`
- Modify: `tests/templates/test_workflow_run_parity.py`

**Interfaces:**

- Consumes: `DOCS_AGENT_APP_TOKEN_STATUS` (Task 2's export contract).
- Produces: nothing downstream.

The dogfood file is missing four things the template has, all verified: no `if:` guard on the App-token step; no `|| secrets.GITHUB_TOKEN` on the checkout `token:`; none on `GH_TOKEN`; and no `SLACK_WEBHOOK_URL` in job-env. It also lacks `id: docs-agent` on its authoring step, which is named `Run nightly authoring` rather than `Run docs-agent`.

**Decision on the missing `id`:** add `id: docs-agent` to the dogfood authoring step. This is safe for `test_01_step_signature_parity` because `_step_signature` keys **run-steps** on the first line of `run:` and uses `id` only for `uses:`-steps — so adding an `id` cannot change that step's signature. It lets the generalized `test_05` locate the authoring step by one uniform predicate in both files. Do **not** rename the step; the name is unrelated to the signature.

- [ ] **Step 1: Apply the five dogfood edits**

1. App-token step: add `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` and `continue-on-error: true`.
2. `Checkout host repo`: change `token: ${{ steps.app-token.outputs.token }}` to `token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}`.
3. Authoring step: add `id: docs-agent`; add the `|| secrets.GITHUB_TOKEN` fallback to the existing `GH_TOKEN` line; add `DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}`.
4. Job-level `env:`: add `SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}`.
5. Correct the same skipped-only degradation comments as in Task 2 Step 3.

- [ ] **Step 2: Update the three existing parity-test surfaces**

In `tests/templates/test_workflow_run_parity.py`:

- `test_04_literal_equals_shape_contract` — add `"SLACK_WEBHOOK_URL"` to the job-env key tuple now that both files carry it.
- `test_05_app_token_conditional_shape` — its body asserts on `template_steps` only, and its docstring declares the dogfood divergence intentional. Convert to `for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:` and rewrite the docstring to say CCE-127 closed it.
- `_TEMPLATE_ONLY_DIVERGENCES` — delete the three entries T2 makes false: the `env.SLACK_WEBHOOK_URL` entry, the `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` entry, and the `with.token uses ||-fallback` entry. This list is documentation-only and nothing detects staleness, so removal is editorial — but leaving them would document a divergence that no longer exists.

Leave `_ALLOWLIST` alone. It has three entries, none relating to the App-token step, and `test_06` validates each is neither stale nor redundant.

- [ ] **Step 3: Write the new test**

Append after the last test:

```python
def test_09_app_token_failure_is_non_fatal_and_signalled(template_doc, dogfood_doc):
    """CCE-127: both files must degrade on a failed token mint, not abort.

    continue-on-error is what keeps `outcome` observable while letting the job
    proceed; the env export is what carries that outcome to the orchestrator.
    Either one alone is inert, so assert both in both files.
    """
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = doc["jobs"]["author"]["steps"]

        app_token = next(s for s in steps if s.get("id") == "app-token")
        assert app_token.get("continue-on-error") is True, (
            f"{label}: app-token step must set continue-on-error: true, or a "
            f"failed mint aborts the job before any fallback is evaluated"
        )

        authoring = next(s for s in steps if s.get("id") == "docs-agent")
        env = authoring.get("env") or {}
        assert env.get("DOCS_AGENT_APP_TOKEN_STATUS") == "${{ steps.app-token.outcome }}", (
            f"{label}: authoring step must export the app-token OUTCOME "
            f"(not conclusion — continue-on-error rewrites conclusion to success)"
        )
```

- [ ] **Step 4: Verify red, then green**

If you did Step 1 first, this already passes. To observe the red state, stash the workflow edits:

```bash
git stash push .github/workflows/docs-agent-nightly.yml templates/workflow-run.yml
.venv/bin/python -m pytest tests/templates/test_workflow_run_parity.py::test_09_app_token_failure_is_non_fatal_and_signalled -v
git stash pop
.venv/bin/python -m pytest tests/templates/test_workflow_run_parity.py::test_09_app_token_failure_is_non_fatal_and_signalled -v
```

Expected: FAIL while stashed (`StopIteration` or assertion), PASS after `stash pop`.

- [ ] **Step 5: Lint and run every affected suite**

```bash
actionlint .github/workflows/docs-agent-nightly.yml
actionlint templates/workflow-run.yml
.venv/bin/python -m pytest tests/templates/ tests/ci/ -q
.venv/bin/python -m pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/docs-agent-nightly.yml tests/templates/test_workflow_run_parity.py
git commit -m "feat(CCE-127): dogfood workflow reaches template parity on auth

Adds the if: guard, both GITHUB_TOKEN fallbacks, SLACK_WEBHOOK_URL
job-env, continue-on-error, and the status export. Adds id: docs-agent so
the generalized test_05 locates the authoring step uniformly. Closes the
CCE-71/CCE-80 divergence and drops the three now-false entries from
_TEMPLATE_ONLY_DIVERGENCES.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Document the new env var

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `README.md`

`DOCS_AGENT_APP_TOKEN_STATUS` is the second orchestrator env var after `DOCS_AGENT_DEBUG_DIR`, which is documented in both files. Shipping a new env var undocumented is a predictable reviewer objection.

**Interfaces:**

- Consumes: the reason prefix `app_token_unavailable:` from Task 1 and the variable name from Task 2.
- Produces: nothing.

- [ ] **Step 1: Find how the precedent var is documented**

```bash
grep -n "DOCS_AGENT_DEBUG_DIR" README.md CHANGELOG.md
```

Match the surrounding style and placement.

- [ ] **Step 2: Add the CHANGELOG entry**

Under the existing `[Unreleased]` heading, following the one-bullet-per-ticket convention used by CCE-125, CCE-122, and CCE-121:

```markdown
- **CCE-127** — A failed GitHub App-token step no longer kills the nightly. The workflow
  runs it under `continue-on-error` and exports `steps.app-token.outcome` as
  `DOCS_AGENT_APP_TOKEN_STATUS`; the orchestrator records a blocking
  `app_token_unavailable` reason for the literal `failure` only, flipping the run to
  `partial` so auto-merge is skipped. `skipped` (no App configured) stays silent. Also
  closes the CCE-71/CCE-80 template-vs-dogfood divergence.
```

- [ ] **Step 3: Add the README entry**

Alongside the `DOCS_AGENT_DEBUG_DIR` documentation:

```markdown
- `DOCS_AGENT_APP_TOKEN_STATUS` — set by the workflow to `steps.app-token.outcome`.
  When it is exactly `failure`, the orchestrator records a blocking
  `app_token_unavailable` reason and the run is marked partial (which disables
  auto-merge, because a PR built on `GITHUB_TOKEN` never triggers host CI). Values
  `skipped`, `success`, and unset are all silent. Set nothing when running locally.
```

- [ ] **Step 4: Verify docs lint passes**

```bash
.venv/bin/python -m pytest tests/lint/ tests/docs/ -q
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(CCE-127): document DOCS_AGENT_APP_TOKEN_STATUS

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Integrated verification and PR

**Files:** none modified.

- [ ] **Step 1: Merge `main` locally and run the integrated suite**

Per `CLAUDE.md`, merge on a green _integrated_ suite, never on GitHub's mergeable flag.

```bash
git fetch origin
git merge origin/main
.venv/bin/python -m pytest -q
```

Expected: green. Resolve any conflict before proceeding.

- [ ] **Step 2: Confirm the diff contains no CCE-128 scope**

```bash
git diff origin/main --stat
test ! -f scripts/notify_run_death.py && echo "OK: no T4 leakage"
```

Expected: seven files changed — `scripts/orchestrator_runner.py`, `tests/orchestrator/test_pipeline_integration.py`, `templates/workflow-run.yml`, `.github/workflows/docs-agent-nightly.yml`, `tests/templates/test_workflow_run_parity.py`, `CHANGELOG.md`, `README.md` — plus the spec and plan already committed. And `OK: no T4 leakage`.

- [ ] **Step 3: Push and open the PR**

The title must contain `CCE-127` so the Atlassian integration auto-links and `scripts/jira_transition_on_merge.py` can close the ticket — it reads keys from the **title** only.

```bash
git push -u origin feat/CCE-127-app-token-degrade-partial
gh pr create --title "CCE-127: app-token failure degrades to a partial run instead of killing the nightly" --body "$(cat <<'EOF'
## Problem

The dogfood nightly failed 15 consecutive nights (2026-07-24 → 2026-08-07), dying at step 2
of 12 with a 404 on the App installation lookup. The `engineering-docs-agent-bot` App was
transferred to the `Design-It-Right` org during the ADIS migration, dropping its
installation on this personal repo.

That exposed the real defect: the template's `|| secrets.GITHUB_TOKEN` fallback only ever
covered the *skipped* step path. GitHub evaluates it only when a step is skipped; a *failed*
step aborts the job first. CCE-80 §9.3 documented exactly that reasoning — correct for the
path it considered, and no one asked about the other one.

## Change

`continue-on-error: true` on the App-token step keeps `outcome` observable while
`conclusion` lets the job proceed. That outcome is exported as
`DOCS_AGENT_APP_TOKEN_STATUS`; the orchestrator records a blocking `app_token_unavailable`
reason for the literal `failure` only. Flipping `partial` reuses the existing
`_maybe_auto_merge` interlock — no new gate code — which matters because a PR built on
`GITHUB_TOKEN` never fires host CI, and zero registered checks would otherwise read as
"nothing failed".

`skipped` (no App configured) stays silent. That is the largest host population and the
regression lock most likely to catch a careless future change.

Also closes the CCE-71/CCE-80 divergence: the dogfood gains the `if:` guard, both
`|| GITHUB_TOKEN` fallbacks, and `SLACK_WEBHOOK_URL`.

## Out of scope

The death alarm is split to **CCE-128**. Adversarial review found six unresolved design
questions and one factual error in the draft — it assumed the tree is checked out when an
`if: failure()` step runs, which is false for pre-checkout failures.

Spec: `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Prune merged branches after the merge lands**

```bash
python3 scripts/prune_merged_branches.py --apply
```

---

## Operational work (operator, not implementer)

These have side effects on a live repository and are **not** part of any task above.

1. **Restore the nightly — do this first, independent of this PR.** Transfer
   `engineering-docs-agent-bot` from `Design-It-Right` back to `theoju`, then install it on
   `theoju/engineering-docs-agent` scoped to that repo. `vars.DOCS_AGENT_APP_CLIENT_ID` and
   `secrets.DOCS_AGENT_APP_PRIVATE_KEY` need no change — a transfer moves ownership, not
   credentials, and preserving them preserves the bot identity that
   `_DOCS_AGENT_BOT_AUTHOR_NAMES` matches against.
2. **Verify the healthy path after merge:**
   `gh workflow run docs-agent-nightly.yml --repo theoju/engineering-docs-agent` → expect a
   non-partial run.
3. **Verify the degraded path.** Temporarily repoint `vars.DOCS_AGENT_APP_CLIENT_ID` at a
   client ID with no installation, fire the workflow, and expect: green workflow, open PR,
   `partial: true`, `app_token_unavailable` in the digest, `auto_merge_skipped: partial_run`.
   **Record the original value first — `Iv23liZ5XLCf77iny1gT` — and restore it immediately
   after.** Leaving it repointed makes every subsequent nightly partial.
4. **Enable a notification channel** if you want CCE-128 to be useful later.
   `notifications.slack.enabled` is `false` and no `SLACK_WEBHOOK_URL` secret is set.
