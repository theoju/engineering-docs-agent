# CCE-6: Live pytest gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `@pytest.mark.live` opt-in gate so we have at least one real-LLM smoke test per dispatch path, validating end-to-end that `dispatch_subagent` actually talks to the `claude` CLI correctly. The gate is default-skip; CI runs it on release tags only.

**Architecture:** Register a `live` marker in `pyproject.toml`; add a `pytest_collection_modifyitems` hook in the top-level `conftest.py` that auto-skips `live`-marked tests unless `-m live` is on the command line. Two new live tests: a `dispatch_subagent("notifier", ...)` happy path and a `dispatch_subagent("pr-summarizer", ...)` happy path against canned inputs. A GitHub Actions workflow runs `pytest -m live` on tag pushes only. Per the spec's Option B, run live tests once at end of implementation before /ship; CI then takes over on the next release tag.

**Tech Stack:** pytest markers + `conftest.py` hook; GitHub Actions workflow YAML; markdown for README/CHANGELOG. Live tests invoke the real `claude` CLI (cost ~$1-3 per full pass).

**Spec reference:** `docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md` — CCE-6 section.

---

## File Structure

- **Modify:** `pyproject.toml` — register `live` marker under `[tool.pytest.ini_options].markers`.
- **Modify:** `conftest.py` (repo root) — add `pytest_collection_modifyitems` default-skip hook.
- **Create:** `tests/live/__init__.py` — empty, marks the directory as a test package.
- **Create:** `tests/live/test_dispatch_subagent_live.py` — two live tests for the dispatch path.
- **Create:** `tests/fixtures/live-repo/seed.json` — pinned `last_sha` + `head_sha` for any future orchestrator-smoke extension. **Not used by the initial two tests** but committed so a future task can extend coverage without scaffolding.
- **Create:** `.github/workflows/release.yml` — GitHub Actions workflow with a `live-tests` job that runs `pytest -m live` only on tag pushes.
- **Modify:** `README.md` — add a "Live integration tests" subsection.
- **Modify:** `CHANGELOG.md` (or create if missing) — note the new gate, cost, and CI cadence.

**Rationale for two `dispatch_subagent` tests instead of one dispatch + one full orchestrator:** The dispatch path IS the system-under-test for the live gate. The "full orchestrator smoke" the ticket mentions is harder to make deterministic without mocking GitHub PR enumeration — which defeats the purpose of a live gate. Two dispatch tests covering different agents (notifier with a digest, pr-summarizer with PR metadata) exercise the same dispatch path with different payload shapes, which is what catches the kinds of bugs CCE-2 and CCE-3 were fixing. The spec explicitly invites Option B's "we'll surface and adjust" stance for this kind of nuance.

If the user prefers a true orchestrator-level live smoke, Task 5 includes an optional sub-task that wires up an orchestrator run against the live-repo fixture.

---

## Task 1: Register the `live` marker

**Files:**

- Modify: `pyproject.toml` — add `markers` block under `[tool.pytest.ini_options]`.

- [ ] **Step 1: Read current `pyproject.toml`**

Run: `cat pyproject.toml`

Expected current state (relevant block):

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

- [ ] **Step 2: Add the marker registration**

Edit `pyproject.toml`. Replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
markers = [
    "live: real-LLM integration test; skipped by default (use `pytest -m live` to opt in)",
]
```

- [ ] **Step 3: Verify pytest accepts the marker**

Run: `python3 -m pytest --markers 2>&1 | grep live`

Expected: a line `@pytest.mark.live: real-LLM integration test; skipped by default...`.

- [ ] **Step 4: Confirm baseline suite still passes**

Run: `pytest -q 2>&1 | tail -3`

Expected: 235 passed (no live tests exist yet).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
chore(CCE-6): register @pytest.mark.live marker

Real-LLM integration tests opt-in via pytest -m live. Skip behavior
in the next commit. Cost ~$1-3 per full pass; CI runs them on tag
pushes only.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Default-skip behavior in `conftest.py`

**Files:**

- Modify: `conftest.py` (repo root).

- [ ] **Step 1: Read current `conftest.py`**

Run: `cat conftest.py`

Expected:

```python
# conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Step 2: Add the default-skip hook**

Replace the file with:

```python
# conftest.py
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.live tests unless `-m live` is passed on the command line.

    Rationale: live tests cost ~$1-3 per full pass and need ANTHROPIC_API_KEY.
    They must never run by accident on `pytest -q` or in CI's regular suite.
    """
    marker_expr = config.getoption("-m") or ""
    if "live" in marker_expr:
        # User explicitly opted in; collect normally.
        return

    skip_live = pytest.mark.skip(reason="live test — run with `pytest -m live` to opt in")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
```

- [ ] **Step 3: Write a tiny throwaway live test to verify the gate**

Create a temporary file `tests/live/__init__.py` (empty) and `tests/live/test_gate_smoke.py`:

```python
"""Verify the @pytest.mark.live gate works as intended.

These tests don't actually call the LLM — they're sanity checks that
the default-skip behavior is correct and that `-m live` opts in.
"""
import pytest


@pytest.mark.live
def test_live_marker_runs_when_opted_in():
    """Sanity: when this test runs, the gate worked."""
    assert True
```

- [ ] **Step 4: Confirm default-skip works**

Run: `pytest tests/live/test_gate_smoke.py -v 2>&1 | tail -5`

Expected: `1 skipped` with reason `live test — run with \`pytest -m live\` to opt in`.

- [ ] **Step 5: Confirm opt-in works**

Run: `pytest -m live tests/live/test_gate_smoke.py -v 2>&1 | tail -5`

Expected: `1 passed`. The test actually executes when the marker is selected.

- [ ] **Step 6: Confirm the rest of the suite is unaffected**

Run: `pytest -q 2>&1 | tail -3`

Expected: 235 passed, 1 skipped. (The 1 skipped is the gate-smoke test.)

- [ ] **Step 7: Commit**

```bash
git add conftest.py tests/live/__init__.py tests/live/test_gate_smoke.py
git commit -m "$(cat <<'EOF'
feat(CCE-6): default-skip @pytest.mark.live tests; opt in with `pytest -m live`

conftest.py hook adds a skip marker to every `live`-marked test
unless the command line specified `-m live`. Includes a tiny
gate-smoke test that proves both modes work without calling the LLM.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Live test — `dispatch_subagent("notifier", ...)` happy path

**Files:**

- Create: `tests/live/test_dispatch_subagent_live.py`

- [ ] **Step 1: Write the live test**

Create `tests/live/test_dispatch_subagent_live.py`:

```python
"""Live integration tests for dispatch_subagent.

These tests invoke the real `claude` CLI and require:
- `claude` binary installed and authenticated (OAuth or ANTHROPIC_API_KEY)
- network access
- API quota (each test costs roughly $0.10-$0.50)

Run with: `pytest -m live tests/live/test_dispatch_subagent_live.py -v`

NEVER run on every `pytest` invocation. Default-skipped by conftest.py.
"""

from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner  # noqa: E402


def _require_claude_cli():
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not installed")
    # OAuth keychain auth is enough; ANTHROPIC_API_KEY isn't strictly required
    # for local dev, but flag it if neither auth path is set.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Soft check: just informational. Don't skip; OAuth may be in keychain.
        pass


@pytest.mark.live
def test_dispatch_notifier_happy_path():
    """notifier with a trivial digest produces a parseable response.

    notifier is the cheapest agent (sonnet, small prompt, no tool calls in
    the happy path). Catches: claude CLI missing, --agent flag broken,
    plugin not installed, response schema drift.
    """
    _require_claude_cli()

    digest = {
        "pr_url": "https://github.com/example/repo/pull/1",
        "run_summary_bullets": [
            "Added a hello-world doc to confirm the live-test gate works.",
        ],
        "doc_links": [],
    }

    result = orchestrator_runner.dispatch_subagent(
        "notifier", digest, dry_run_dir=None
    )

    assert result is not None, (
        "dispatch_subagent returned None — check claude CLI auth, "
        "agent resolution, and the JSON parsing path in dispatch_subagent"
    )
    assert isinstance(result, dict), f"expected dict response; got {type(result)}"
```

- [ ] **Step 2: Confirm the test is collected and default-skipped**

Run: `pytest tests/live/test_dispatch_subagent_live.py --collect-only 2>&1 | tail -10`

Expected: `1 test collected` (notifier test). NO `1 selected` count — collection happens before skip.

Run: `pytest tests/live/test_dispatch_subagent_live.py -v 2>&1 | tail -5`

Expected: `1 skipped` (default-skip behavior).

- [ ] **Step 3: Verify the test would RUN if opted in (do NOT actually run live yet)**

Run: `pytest -m live tests/live/test_dispatch_subagent_live.py --collect-only 2>&1 | tail -5`

Expected: `1 test collected` and selected.

**Do NOT actually invoke `pytest -m live` yet** — Task 7 is the one end-of-implementation live run. Running it now is a sequence violation per Option B.

- [ ] **Step 4: Commit**

```bash
git add tests/live/test_dispatch_subagent_live.py
git commit -m "$(cat <<'EOF'
test(CCE-6): live test — dispatch_subagent("notifier", ...) happy path

Default-skipped; opt in with `pytest -m live`. notifier is the
cheapest agent to invoke live, making it the first line of defense
against dispatch-wiring regressions (the kind CCE-2/CCE-3 fixed).

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Live test — `dispatch_subagent("pr-summarizer", ...)` happy path

**Files:**

- Modify: `tests/live/test_dispatch_subagent_live.py` — add a second test for a different agent and payload shape.

- [ ] **Step 1: Append the new test**

Add to `tests/live/test_dispatch_subagent_live.py`:

```python
@pytest.mark.live
def test_dispatch_pr_summarizer_happy_path():
    """pr-summarizer with a canned PR payload produces a schema-conformant response.

    Exercises a different agent + payload shape than the notifier test,
    so a regression that only affects PR-shaped inputs gets caught.
    Also validates that pr-summarizer's per-agent --allowedTools=Read
    (CCE-7) doesn't break the happy path.
    """
    _require_claude_cli()

    pr_input = {
        "pr": {
            "number": 1,
            "title": "Add hello-world doc",
            "body": "Adds docs/hello.md as a smoke test for the live integration gate.",
            "merged_at": "2026-05-22T00:00:00Z",
            "merge_sha": "abc123",
            "files": [{"path": "docs/hello.md", "additions": 5, "deletions": 0}],
        },
        "jira_issues": [],
    }

    result = orchestrator_runner.dispatch_subagent(
        "pr-summarizer", pr_input, dry_run_dir=None
    )

    assert result is not None, "dispatch_subagent returned None"
    assert isinstance(result, dict), f"expected dict; got {type(result)}"
    # pr-summarizer's schema (per agents/schemas/pr_summarizer.schema.json) requires
    # at least these top-level keys. If the model drifts, the test fails loudly.
    for required_key in ("what_changed", "why", "breaking"):
        assert required_key in result, (
            f"pr-summarizer response missing required key '{required_key}'; "
            f"got keys: {list(result.keys())}"
        )
```

- [ ] **Step 2: Verify collection picks up both tests**

Run: `pytest -m live tests/live/test_dispatch_subagent_live.py --collect-only 2>&1 | tail -5`

Expected: `2 tests collected`.

- [ ] **Step 3: Verify default-skip still applies to both**

Run: `pytest tests/live/test_dispatch_subagent_live.py -v 2>&1 | tail -5`

Expected: `2 skipped`.

- [ ] **Step 4: Commit**

```bash
git add tests/live/test_dispatch_subagent_live.py
git commit -m "$(cat <<'EOF'
test(CCE-6): live test — dispatch_subagent("pr-summarizer", ...) happy path

Different agent + different payload shape than the notifier test,
so dispatch wiring regressions specific to one shape get caught.
Also confirms pr-summarizer's per-agent --allowedTools=Read
(landed in CCE-7) doesn't break the happy path.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Commit live-repo seed for future extension

**Files:**

- Create: `tests/fixtures/live-repo/seed.json`
- Create: `tests/fixtures/live-repo/README.md`

This task commits a placeholder fixture so a future ticket can extend live-test coverage to a full orchestrator smoke without re-scaffolding. The seed pins `last_sha`/`head_sha` to specific commits in THIS repo's history so any orchestrator-smoke test is deterministic.

- [ ] **Step 1: Identify two real SHAs from this repo's history**

Run:

```bash
git log --oneline | head -10
git log --oneline | tail -5
```

Pick:

- `last_sha`: the v0.1.0 tag commit, or whatever the project's earliest "stable" commit is.
  - Verify: `git tag -l | head -5` and `git rev-parse v0.1.0 2>/dev/null`. If `v0.1.0` doesn't resolve, use the earliest commit in `git log`.
- `head_sha`: the most recent commit on main after CCE-22 merged (`git rev-parse main`).

Record the SHAs.

- [ ] **Step 2: Write the seed file**

Create `tests/fixtures/live-repo/seed.json`:

```json
{
  "purpose": "Pinned SHAs for future live-orchestrator-smoke tests. Not used by the initial live tests in tests/live/. See tests/fixtures/live-repo/README.md.",
  "repo": {
    "owner": "theoju",
    "name": "engineering-docs-agent"
  },
  "last_sha": "<paste from Step 1>",
  "head_sha": "<paste from Step 1>"
}
```

Replace the `<paste from Step 1>` placeholders with the actual SHAs from Step 1.

- [ ] **Step 3: Write the fixture README**

Create `tests/fixtures/live-repo/README.md`:

```markdown
# live-repo fixture

Pinned SHAs for extending the @pytest.mark.live gate to an orchestrator-level smoke test.

## Why this exists but isn't used yet

CCE-6 acceptance mentions a "full orchestrator_runner.run(...)" live smoke against a fixture repo with deterministic SHAs. The initial CCE-6 implementation lands two `dispatch_subagent` live tests instead (notifier + pr-summarizer), which exercise the same dispatch wiring with two different payload shapes. The orchestrator-level smoke is harder to make deterministic without mocking GitHub PR enumeration — which would defeat the live-test purpose.

This seed.json pins two SHAs from THIS repo's history so a future ticket can:

1. Initialize a real git clone at tmp_path pointing at these SHAs.
2. Invoke `orchestrator_runner.run(tmp_path, dry_run_dir=None, no_pr=True)`.
3. Assert exit 0 and ≥1 PR or Jira issue consumed.

When that ticket lands, update `seed.json` if the SHAs drift out of relevance.

## Not for general fixture data

Other test fixtures live under `tests/fixtures/<name>/`. This directory is specifically for the live-repo orchestrator-smoke extension.
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/live-repo/
git commit -m "$(cat <<'EOF'
chore(CCE-6): seed for future live-orchestrator-smoke extension

tests/fixtures/live-repo/seed.json pins last_sha + head_sha from this
repo's history. The initial CCE-6 lands two dispatch_subagent live
tests (notifier + pr-summarizer); a future ticket can extend to a
full orchestrator-level smoke using this seed. README in the
fixture dir explains the rationale.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: GitHub Actions workflow for tag-push live tests

**Files:**

- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Confirm the workflow doesn't already exist**

Run: `ls .github/workflows/ 2>&1`

If `release.yml` exists, surface that — this plan assumed it doesn't. If it does, the task becomes "amend" instead of "create".

- [ ] **Step 2: Create the workflow**

Create `.github/workflows/release.yml`:

```yaml
name: release

on:
  push:
    tags:
      - "v*"

jobs:
  live-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Install claude CLI
        run: |
          npm install -g @anthropic-ai/claude-cli || true
          which claude || (echo "claude CLI not installed" && exit 1)

      - name: Run live tests
        run: pytest -m live -v
```

- [ ] **Step 3: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`

Expected: no error.

If you have `act` or `actionlint` installed locally, also run:

```bash
actionlint .github/workflows/release.yml 2>&1
```

Expected: clean. If not installed, skip — GitHub will surface workflow-syntax errors on first tag push.

- [ ] **Step 4: Confirm the workflow trigger is tag-only**

Re-read the `on:` block. It should be ONLY `push.tags: - "v*"` — not `push.branches` or `workflow_dispatch`. The spec is explicit: CI runs live tests on **release tags only**, not per push.

If you want a manual-dispatch escape hatch, surface that as a follow-up question — but the spec says "tag pushes only", so default to NOT adding `workflow_dispatch`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "$(cat <<'EOF'
ci(CCE-6): release workflow runs `pytest -m live` on tag pushes only

Triggered by tags matching v* (e.g., v0.2.0). Requires
secrets.ANTHROPIC_API_KEY. Each tag-push run costs ~$1-3.

Does NOT run on regular pushes or PRs — the live gate is a release
quality bar, not a per-PR cost.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Documentation — README + CHANGELOG

**Files:**

- Modify: `README.md` — add "Live integration tests" subsection.
- Create or modify: `CHANGELOG.md` — add an entry.

- [ ] **Step 1: Find the right README insertion point**

Run: `grep -n "## Self-hosting\|### Lens paths\|### Install from local" README.md`

Insert the new subsection as a top-level `## Live integration tests` AFTER the Self-hosting block (i.e., not nested under Self-hosting; it's a development-process topic, not a setup topic).

- [ ] **Step 2: Add the README subsection**

Append (or insert at the right place):

````markdown
## Live integration tests

The default `pytest` run is fully mocked — no network, no LLM, no cost. A separate `@pytest.mark.live` gate covers the real-LLM dispatch path:

```bash
pytest -m live -v
```
````

These tests invoke the real `claude` CLI and cost roughly **$1-3 per full pass** (each test ~$0.10-$0.50). They require:

- `claude` CLI installed and authenticated (OAuth or `ANTHROPIC_API_KEY`)
- Network access
- API quota

Live tests are skipped by default (`conftest.py` hook). Opt in with `-m live`. CI runs them only on tag pushes (`.github/workflows/release.yml`), not per PR or per push.

What's covered: one `dispatch_subagent` call per agent payload shape (notifier with a digest, pr-summarizer with PR metadata). The dispatch path is the system-under-test — the kinds of bugs CCE-2 and CCE-3 fixed are exactly what live tests catch.

````

- [ ] **Step 3: Add or update CHANGELOG**

Run: `ls CHANGELOG.md 2>&1`

If CHANGELOG.md exists, prepend a new entry to the top. If not, create it.

For the new entry, add (or create-with):

```markdown
# Changelog

## Unreleased

- Live integration tests via `@pytest.mark.live` (CCE-6). Default-skipped; opt in with `pytest -m live`. CI runs them on tag pushes only. Cost ~$1-3 per full pass.
````

If CHANGELOG.md exists with prior entries, insert the `## Unreleased` block at the top (after the `# Changelog` header) — keep existing content intact.

- [ ] **Step 4: Smoke**

Run: `pytest -q 2>&1 | tail -3`

Expected: 235 passed, 3 skipped (the 1 gate-smoke + 2 dispatch live tests from Task 3/4).

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(CCE-6): README + CHANGELOG — live integration tests

README gains a "Live integration tests" section explaining the opt-in
gate, costs, requirements, and CI cadence. CHANGELOG entry under
Unreleased documents the new gate.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Option B — one end-of-implementation live run

**Files:**

- (no code changes — operator action)

This is the validation pass per the spec's Option B. It runs ONCE, before /ship.

- [ ] **Step 1: Confirm `claude` CLI is available and authenticated**

Run: `which claude && claude --version 2>&1`

Expected: a version string. If the command isn't found, the live tests will skip — fix authentication before proceeding. The validation pass requires real LLM calls.

- [ ] **Step 2: Run the live suite**

Run: `pytest -m live -v 2>&1 | tee /tmp/cce6-live-run.log`

Expected: 3 passed (1 gate-smoke + 2 dispatch tests). Approximate cost: $0.20-$1.

If any of the dispatch tests fail, **do not edit the live tests themselves to make them pass.** The live tests are pinning the dispatch contract; a failure indicates a real wiring bug. Surface the failure, debug from the dispatch code side, then re-run.

- [ ] **Step 3: Capture the live-run evidence in a commit message**

Note the duration, cost (approximate, from API console if available), and pass count. This goes in the /ship commit message OR PR body — operators / reviewers want to see the live run actually executed.

- [ ] **Step 4: No commit — this is a validation pass**

The /ship invocation that follows this plan is what opens the PR. The live-run evidence goes in the PR body (Task 7 of /ship's plan, but we'll capture it in the message we write at /ship time).

If the live run fails and a fix commit is needed: name the fix `fix(CCE-6): <what was wrong>` and re-run the live suite afterward.

---

## Spec coverage check

Spec acceptance criteria for CCE-6:

- [x] `@pytest.mark.live` marker registered — Task 1.
- [x] Tests so marked are **skipped by default** when `pytest -q` runs — Task 2 (`conftest.py` hook).
- [x] `pytest -m live` (or `pytest --live`) opts in — Task 2 (the conftest hook checks for `live` in the `-m` expr; `pytest -m live` is the canonical invocation).
- [x] At least one live test per dispatch path — Tasks 3 and 4 (two `dispatch_subagent` tests for different agent/payload shapes).
- [x] Fixture repo for deterministic PR enumeration — Task 5 (committed seed; orchestrator-smoke extension deferred to a future ticket per the plan's rationale).
- [x] README + CHANGELOG entry — Task 7.
- [x] `.github/workflows/release.yml` runs `pytest --live` on tag pushes only — Task 6.

One deviation from the original ticket: the "full `orchestrator_runner.run(...)` smoke" is deferred to a future ticket (Task 5 commits the seed for it). Rationale: making the orchestrator smoke deterministic without mocking GitHub API undermines the live-test purpose. Two `dispatch_subagent` live tests with different payload shapes give the same wiring-regression signal at lower cost and higher reliability. The spec calls out the live-test policy as the "one real design call" — this is the natural follow-through.

## `pytest -q` does NOT auto-run live tests

Verified by Task 2 step 6: `pytest -q` shows 235 passed + 3 skipped (gate smoke + 2 dispatch live tests). No accidental cost.

## Risk and YAGNI

- This plan does NOT cache live responses for replay (out of scope per ticket — could be a separate ticket if cost becomes a concern).
- This plan does NOT add per-agent live tests for all seven agents (out of scope per ticket — one happy path per dispatch payload shape is enough).
- The fixture repo committed in Task 5 is **seed-only**; no test in this plan uses it. A future ticket extending to orchestrator-smoke live coverage will consume the seed. Committing it now avoids re-scaffolding later.
- The release workflow uses `npm install -g @anthropic-ai/claude-cli` to install the CLI in CI. The exact npm package name may change; verify against current docs at PR-creation time. Falling back: install via the official install script if npm doesn't work.
