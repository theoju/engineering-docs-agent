# CCE-80 — Refresh `templates/workflow-run.yml` Implementation Plan (v2 — post-validation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb 16 STALE divergences from `.github/workflows/docs-agent-nightly.yml` into `templates/workflow-run.yml`, add deterministic per-host cron randomization at scaffold time, lock parity with a live test, and document the host-migration runbook.

**Architecture:** TDD-first parity test (`tests/templates/test_workflow_run_parity.py`, 8 functions, xfailed-skeleton-first) lifts xfails as each absorption phase lands. Two new stdlib-only helpers (`scripts/scaffold_workflow.py` for cron rewrite, `scripts/setup_discover.discover_git_origin()` for owner/repo) drive the setup-skill changes in `skills/engineering-docs-agent-setup/SKILL.md`. Bundled CCE-73 stdout-echo step is co-edited into the dogfood workflow in the same PR (locked decision CO-EDIT). Plugin pin is `v0.5.0`, cut by PR author within 5 min of merge per spec §5.4.

**Tech Stack:** Python 3.11 stdlib (helpers), ruamel.yaml 0.18+ (parity test parser — preserves YAML 1.2 semantics for the `on:` key, NOT PyYAML), pytest with `xfail` markers + `importorskip` guard, GitHub Actions YAML, bash + jq + actionlint + shellcheck (CI lint).

**Spec:** `docs/superpowers/specs/2026-06-01-cce80-templates-workflow-run-refresh.md` (583 lines; revisions commit `c450653`)
**Branch:** `chore/CCE-80-template-workflow-run-refresh` (3 commits ahead of main: spec `b959da0` + revisions `c450653` + plan v1 `f64ffcf` — to be amended by this v2 plan)
**Commit trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
**Test runner:** `python3 -m pytest`

---

## Changelog vs v1 (the 3-validator panel surfaced 5 criticals + 12 importants)

| #        | Issue                                                                                                                                                                   | v2 resolution                                                                                                                                                           |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CC1**  | `_ALLOWLIST` run-entry truncated; dogfood checkout step had no `id:`, breaking step-signature parity                                                                    | Fixed `_ALLOWLIST` entry to dogfood's full first-line form; **Task 8 (was Task 9)** now co-edits dogfood to add `id: checkout-host`                                     |
| **CC2**  | actionlint 1.7.7 **EMPIRICALLY VERIFIED** to flag `steps.app-token.outputs.token` dangling reference (exit 1, two errors) — Tasks 5–8 would push red CI between commits | **Folded Task 6 (App-token) into Task 5** — single absorption commit lands both. Spec §5.1.1's 5-commit sequence → 4 commits. Documented deviation.                     |
| **CC3**  | Many Edit operations described in natural language, not verbatim old_string/new_string blocks                                                                           | All Edit operations rewritten with explicit pre/post text. Template uses Write (full-file overwrite).                                                                   |
| **CC4**  | Pytest expected totals off-by-one; propagated through Tasks 3–9                                                                                                         | Replaced integer totals with **qualitative invariant** ("monotonically increasing passed count; no previously-passing test regresses") + per-task delta annotation      |
| **CC5**  | Commit count assertions inconsistent (12 vs 13 vs 11) and didn't account for branch's 3 pre-existing commits                                                            | Anchored to stable ref: `git log c450653..HEAD \| wc -l` should equal 12 (11 impl commits + plan v2 amendment). Reconciled across §0, Task 12 step 7, step 8            |
| **CI1**  | `_CRON_PATTERN` substitution drops the space between `7` and `*` (produces `42 7* * *`) — **EMPIRICALLY VERIFIED**                                                      | Fixed regex: move `\s+` into group 2. Added explicit substring assertion.                                                                                               |
| **CI2**  | Plan added `workflow_dispatch` to job-level `if:` without spec authorization                                                                                            | **Adopted.** Note added to Task 5: this is a small spec extension (manual dispatch must run when gated).                                                                |
| **CI3**  | Template Run-summary heading `## docs-agent` vs dogfood `## docs-agent-nightly` — silent UX divergence                                                                  | Standardized BOTH to `## docs-agent-nightly`. Task 5 template uses dogfood form; no dogfood edit needed.                                                                |
| **CI4**  | Non-step `_ALLOWLIST` entries are documentation-only ghosts (test_06 filters them out)                                                                                  | Moved to separate `_TEMPLATE_ONLY_DIVERGENCES` constant (documentation-only, with explanatory comment). `_ALLOWLIST` retains ONLY uses:/run: entries the test enforces. |
| **CI6**  | `test_skill_step8_warns_about_app_token_for_ci` had dead-code assert (same clause twice)                                                                                | Fixed: second clause is `'host ci' in text.lower()` (lowercase).                                                                                                        |
| **CI9**  | Spec §5.3.4 setup-guide.md provisioning matrix flagged as gap, deferred                                                                                                 | **Added Task 10**: append vars/secrets matrix to `docs/site-src/setup-guide.md`. Total tasks: 12 (was 12 — Task 5+6 fold offsets new Task 10).                          |
| **CI10** | Parity test imports ruamel.yaml at module level — if pip install fails, every subsequent task's pytest collection dies RED                                              | Added `ruamel = pytest.importorskip('ruamel.yaml')` at module top. Task 1 step 2 marked **HARD GATE**.                                                                  |
| **CI11** | SKILL.md Edit operations to same paragraph in two stages                                                                                                                | Single Edit operation with full verbatim line-33 old_string.                                                                                                            |
| **CI12** | SKILL.md prose/code-block sub-bullet numbering contradiction (6c BEFORE 6a vs 6b AFTER 6a)                                                                              | Subsumed by CC3. Standardized on **6b immediately AFTER existing 6a**.                                                                                                  |

---

## File structure

Files **created**:

| Path                                          | Purpose                                                                   |
| --------------------------------------------- | ------------------------------------------------------------------------- |
| `requirements-dev.txt`                        | Dev-only deps (`ruamel.yaml>=0.18` for parity test); never ships to hosts |
| `scripts/scaffold_workflow.py`                | Stdlib-only helper to rewrite cron with per-host deterministic minute     |
| `tests/templates/__init__.py`                 | Test package marker                                                       |
| `tests/templates/test_workflow_run_parity.py` | 8-function live-dogfood parity test                                       |
| `tests/setup/test_scaffold_workflow.py`       | 6-function helper test                                                    |
| `tests/skills/__init__.py`                    | Test package marker                                                       |
| `tests/skills/test_setup_skill_md.py`         | 4-function grep-style SKILL.md test                                       |
| `docs/runbooks/cce80-host-migration.md`       | Per-host migration runbook with verification commands                     |
| `CONTRIBUTING.md`                             | Dogfood↔template parity gate note (file does not yet exist in repo)       |

Files **modified**:

| Path                                           | Change                                                                                                                                                                                                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `templates/workflow-run.yml`                   | Absorb 16 STALE divergences (full-file rewrite from 53 → ~165 lines)                                                                                                                                                                                       |
| `.github/workflows/docs-agent-nightly.yml`     | Co-edits: (a) add `id: checkout-host` to existing checkout step; (b) add "Print partial-run reasons" step (CCE-73 bundle); (c) standardize Run-summary heading text to `docs-agent-nightly` (already correct on dogfood — no change actually needed there) |
| `scripts/setup_discover.py`                    | Add `discover_git_origin()` + integrate into `discover()` under `"git"` key                                                                                                                                                                                |
| `tests/setup/test_setup_discover.py`           | Append 3 test cases (SSH URL, HTTPS URL, missing-remote None)                                                                                                                                                                                              |
| `skills/engineering-docs-agent-setup/SKILL.md` | Step 6: invoke `scaffold_workflow.py`; Step 8: App-token CI warning                                                                                                                                                                                        |
| `docs/site-src/setup-guide.md`                 | Append vars/secrets provisioning matrix (Task 10, was deferred in v1)                                                                                                                                                                                      |

**Commit total within PR:** 11 implementation commits (Task 12 is verification-only). With the 3 already-on-branch commits (`b959da0`, `c450653`, `f64ffcf` + this v2 amendment as `<v2-sha>`), branch ends at 4 + 11 = 15 commits ahead of `main`; anchored count `git log c450653..HEAD | wc -l == 12` (plan-v2 amendment + 11 impl commits).

**Pre-merge dogfooding requirement:** Operators re-scaffolding any host before merge MUST first run `claude plugin add --local /Users/theo/Projects/engineering-docs-agent` so the setup skill resolves to the feature branch's SKILL.md + scripts (per spec §5.3.6). This plan does not implement that — it's an operator-runtime instruction captured in the migration runbook.

---

## Test-total convention (CC4 resolution)

Instead of tracking exact pytest pass/fail/xfail counters across tasks (fragile, propagates off-by-one), this plan uses a **qualitative invariant**:

> Every task that runs `python3 -m pytest` must satisfy:
>
> 1. **No previously-passing test regresses** (pass count must NOT decrease).
> 2. **All xfails are accounted for** by the matrix below.
> 3. **No accidental ERRORs** (test-collection failures count as ERROR, not XFAIL).

Each task notes the **delta** (new tests added / xfails lifted) plus a sanity check:

```bash
python3 -m pytest --tb=no -q 2>&1 | tail -3
```

Look for the summary line (e.g., `743 passed, 3 skipped, 5 xfailed in 12.34s`). If it matches the expected shape AND the failure summary is empty, the task is green. Exact integer matching is NOT required.

**Reference matrix** (baseline 726 passed from CCE-74 merge, used for orientation only):

| After task                                | New passing | Xfails outstanding                         | Notes                                                                                                                   |
| ----------------------------------------- | ----------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 1                                         | +0          | 8 (parity test skeleton)                   | All 8 parity tests xfailed                                                                                              |
| 2                                         | +5          | 8 + 2 = 10 (parity 8, scaffold-workflow 2) | 5 of 6 scaffold tests pass; round-trip + CLI smoke xfail-guard inside test body until Task 5                            |
| 3                                         | +3          | 10 (unchanged)                             | 3 discover_git_origin tests pass                                                                                        |
| 4                                         | +4          | 10 (unchanged)                             | 4 SKILL.md grep tests pass                                                                                              |
| 5 (folded — CCE-39 baseline + App-token)  | +5          | 4 (test_01/02/03/06 outstanding)           | Lifts test_04, test_05, test_07, test_08; scaffold-workflow xfail guards now lift (template has `7 7` cron + FN header) |
| 6 (OAuth assert)                          | +0          | 4 (unchanged)                              | Substring tests wait for partial_reasons from Task 8                                                                    |
| 7 (Forensics)                             | +0          | 4 (unchanged)                              | Step-signature tests wait for full step set                                                                             |
| 8 (CCE-73 echo + dogfood co-edits)        | +4          | 0                                          | Lifts test_01, test_02, test_03, test_06                                                                                |
| 9–11 (runbook, setup-guide, CONTRIBUTING) | +0          | 0                                          | Documentation tasks only                                                                                                |
| 12                                        | +0          | 0                                          | Verification only                                                                                                       |

---

## Task 1: Bootstrap parity-test infrastructure (xfailed skeleton)

**Files:**

- Create: `requirements-dev.txt`
- Create: `tests/templates/__init__.py`
- Create: `tests/templates/test_workflow_run_parity.py`

**Why first?** The xfailed-skeleton pattern lets every subsequent template-absorption task lift its bucket of xfails. Suite stays green throughout the absorption sequence. Module-level `pytest.importorskip` guards against ruamel.yaml install failures cascading red across the rest of the plan (CI10).

- [ ] **Step 1: Create `requirements-dev.txt`** (use the Write tool)

File path: `requirements-dev.txt`

File content (verbatim):

```text
# Dev-only dependencies — NOT shipped to host repos.
# templates/docs-requirements.txt is the host-facing list; keep this separate.

ruamel.yaml>=0.18  # YAML 1.2 parser for tests/templates/test_workflow_run_parity.py
                   # PyYAML SafeLoader collapses YAML-1.1 `on:` → True; ruamel preserves it as a string.
```

- [ ] **Step 2: Install dev deps locally — HARD GATE**

Run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -c "import ruamel.yaml; print('ruamel.yaml', ruamel.yaml.__version__)"
```

Expected: prints `ruamel.yaml <version>` where version starts with `0.18.` or higher. No traceback.

**HARD GATE: if either command exits non-zero, HALT and surface to the user.** Do NOT proceed to Step 3 — the parity test will fail to collect across every subsequent task otherwise.

- [ ] **Step 3: Create test package marker**

Run:

```bash
mkdir -p tests/templates && : > tests/templates/__init__.py
```

- [ ] **Step 4: Write the skeleton parity test (all 8 functions xfailed, importorskip guarded)**

Use the Write tool. File path: `tests/templates/test_workflow_run_parity.py`. File content (verbatim):

```python
"""Parity test for templates/workflow-run.yml ↔ .github/workflows/docs-agent-nightly.yml.

Key grammar (the strings used in _ALLOWLIST and matcher logic):
  uses:<action>@<ver>              — matches step by uses: signature only (no id required)
  uses:<action>@<ver>#<id>         — matches step by uses: AND id: (disambiguates duplicates)
  run:<prefix>                     — matches a step whose run: scalar starts with the prefix (first line, normalized whitespace)

XFAIL DISCIPLINE: tests are xfailed until their template-absorption task lands. Each
task in the implementation plan lifts the xfail markers it satisfies, leaving the
suite green throughout the absorption sequence (CCE-80 plan tasks 5, 6, 8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# CI10: module-level importorskip — if ruamel.yaml is missing, every test in this
# module SKIPS instead of erroring at collection time. Downstream tasks remain green.
ruamel = pytest.importorskip("ruamel.yaml")

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "workflow-run.yml"
DOGFOOD = ROOT / ".github" / "workflows" / "docs-agent-nightly.yml"


# _ALLOWLIST: step-signature entries that test_06 actively enforces (uses:/run: prefixes).
# Any step in dogfood OR template matching one of these signatures bypasses test_01's
# step-signature parity check. Entries are validated by test_06 to be neither stale
# (no matching step anywhere) nor redundant (matching step in BOTH files).
_ALLOWLIST: dict[str, str] = {
    "uses:actions/checkout@v5#checkout-plugin":
        "Template-only: plugin vendoring step (id: checkout-plugin discriminates from host checkout)",
    'run:python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .':
        "HOST-SPECIFIC entrypoint: template uses vendored-plugin path; dogfood uses its own scripts/ tree",
    'run:python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"':
        "HOST-SPECIFIC entrypoint: dogfood-side counterpart to the template's vendored-plugin run line",
}


# _TEMPLATE_ONLY_DIVERGENCES: documentation-only notes for non-step divergences
# (triggers, env keys, if-expressions, with-keys). These are NOT enforced by any
# test function — they record WHY the human reviewer should accept these
# divergences when reading the diff. See spec §5.2.
_TEMPLATE_ONLY_DIVERGENCES = {
    "on.pull_request.types == [closed]":
        "Template-only trigger: real-time docs update on merge for hosts (D4)",
    "jobs.run.if contains `github.event_name == 'schedule'`":
        "Template-only job-level guard: paired with pull_request.closed trigger (D4 self-loop)",
    "with.path == .docs-agent-plugin":
        "Template-only: vendored-plugin checkout target (paired with checkout-plugin step)",
    "env.SLACK_WEBHOOK_URL":
        "Template-only opt-in: consumed by agents/notifier.md when notifications.slack.enabled: true",
    "if: vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true' on Assert OAuth step":
        "Template-only: enterprise/Bedrock/Vertex hosts can opt out; dogfood owns its own auth",
    "if: vars.DOCS_AGENT_APP_CLIENT_ID != '' on Generate GitHub App token step":
        "Template-only: hosts without an App fall back to GITHUB_TOKEN (with host-CI suppression caveat); dogfood requires the App",
    "with.token uses ||-fallback":
        "Template-only: checkout-host and docs-agent step env use `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`; dogfood uses only the App token",
}


_WITH_KEY_CONTRACT: dict[str, set[str]] = {
    "actions/checkout@v5": {"token"},
    "actions/create-github-app-token@v3": {"client-id", "private-key"},
    "actions/upload-artifact@v6": {"name", "path", "retention-days", "if-no-files-found"},
}


def _load(path: Path) -> dict:
    yaml = ruamel.yaml.YAML(typ="rt")
    with path.open() as fh:
        return yaml.load(fh)


@pytest.fixture(scope="module")
def template_doc() -> dict:
    return _load(TEMPLATE)


@pytest.fixture(scope="module")
def dogfood_doc() -> dict:
    return _load(DOGFOOD)


# ---------------------------------------------------------------------------
# 8 numbered assertion functions (xfailed-skeleton; bodies replaced as tasks land)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: full step-signature parity awaits CCE-73 stdout echo bundle + dogfood id co-edit")
def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: with-key contract on all absorbed actions")
def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: substring asserts include partial_reasons (CCE-73 bundle)")
def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: literal-equals shape contract on CCE-39 baseline + App-token folded")
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: App-token conditional shape (template-only properties)")
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: allowlist orphan/redundant guards run when all steps present")
def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: run-summary `if: always()` (CCE-39 baseline)")
def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: on-key regression guard (catches PyYAML escape route)")
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- [ ] **Step 5: Run the parity test — expect 8 xfailed, 0 failed, 0 errors**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: 8 xfailed, no failures, no collection errors.

- [ ] **Step 6: Run the full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected summary shape: `<N> passed, <M> skipped, 8 xfailed in <T>s`. The pass count `<N>` must be ≥ baseline (the merged trunk's baseline at the time of task execution).

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tests/templates/__init__.py tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
test(CCE-80): xfailed parity-test skeleton + ruamel.yaml dev dep

Sets up the live-dogfood parity test with all 8 numbered assertion
functions xfailed. Each subsequent CCE-80 task lifts its bucket of xfails
so the suite stays green through the 4-commit absorption sequence (Tasks
5–8 after the post-validation Task 5+6 fold).

Uses ruamel.yaml (not PyYAML) to preserve YAML-1.2 semantics for the
top-level on: key. Module-level pytest.importorskip("ruamel.yaml") so a
missing dep skips this file's tests instead of failing collection across
every later task. requirements-dev.txt keeps dev deps out of the
host-facing templates/docs-requirements.txt.

_ALLOWLIST contains only step-signature entries (uses:/run:) that test_06
actually enforces. Non-step divergences live in _TEMPLATE_ONLY_DIVERGENCES
as documentation-only notes — eliminates the "ghost entries" problem
flagged by V1+V2 validators.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `scripts/scaffold_workflow.py` helper (TDD) — CI1 cron regex fix

**Files:**

- Create: `scripts/scaffold_workflow.py`
- Create: `tests/setup/test_scaffold_workflow.py`

**Why next?** SKILL.md edits in Task 4 invoke this helper. The helper must exist + be tested first.

**CI1 fix:** the `_CRON_PATTERN` regex captures the trailing space between `7` and `*` inside group 2 so the substitution preserves it. Plus an explicit substring assertion.

- [ ] **Step 1: Write failing test `test_deterministic_cron_minute_stable`** (use Write tool)

File path: `tests/setup/test_scaffold_workflow.py`. File content (verbatim — this is the COMPLETE final test file; Steps 5 doesn't add to it):

```python
"""Tests for scripts/scaffold_workflow.py — cron-randomization helper.

Determinism + bounds + anchor sanity + real-template round-trip + CLI smoke +
explicit-substring lock against the CI1 regex-spacing bug.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "scaffold_workflow.py"
TEMPLATE = ROOT / "templates" / "workflow-run.yml"

sys.path.insert(0, str(ROOT / "scripts"))


def _expected_minute(owner: str, repo: str) -> int:
    """Mirror of the production algorithm (NOT a tautology — bounds + distribution
    + real-template round-trip catch lockstep drift)."""
    return int(hashlib.sha256(f"{owner}/{repo}".encode()).hexdigest(), 16) % 51 + 5


def test_deterministic_cron_minute_stable() -> None:
    """Same input → same output. No drift across calls."""
    from scaffold_workflow import deterministic_cron_minute

    assert deterministic_cron_minute("theoju", "adis") == deterministic_cron_minute("theoju", "adis")
    assert deterministic_cron_minute("theoju", "ccsa") == deterministic_cron_minute("theoju", "ccsa")


def test_known_fixture_minutes() -> None:
    """Lock specific (owner, repo) → minute mappings. Regenerate _expected_minute
    output if the algorithm changes intentionally."""
    from scaffold_workflow import deterministic_cron_minute

    for owner, repo in [
        ("theoju", "adis"),
        ("theoju", "ccsa"),
        ("theoju", "data-importer"),
        ("theoju", "dogfood"),
    ]:
        assert deterministic_cron_minute(owner, repo) == _expected_minute(owner, repo)


def test_cron_minute_bounds() -> None:
    """Sweep — every minute must land in [5, 55]."""
    from scaffold_workflow import deterministic_cron_minute

    fixtures = [
        ("theoju", "adis"), ("theoju", "ccsa"), ("theoju", "data-importer"),
        ("theoju", "dogfood"), ("acme", "service-x"), ("contoso", "monorepo"),
        ("foo", "bar"), ("xyz", "lorem-ipsum"),
    ]
    for owner, repo in fixtures:
        m = deterministic_cron_minute(owner, repo)
        assert 5 <= m <= 55, f"{owner}/{repo}: minute {m} outside [5, 55]"


def test_rewrite_cron_anchor_zero_matches_raises() -> None:
    """A template without the anchored cron line must raise loudly."""
    from scaffold_workflow import rewrite_cron

    text = "name: docs-agent run\non:\n  workflow_dispatch:\n"
    with pytest.raises(RuntimeError, match=r"found 0"):
        rewrite_cron(text, "theoju", "dogfood")


def test_rewrite_cron_anchor_two_matches_raises() -> None:
    """A template with duplicate cron lines must also raise."""
    from scaffold_workflow import rewrite_cron

    text = (
        "on:\n"
        '  schedule:\n'
        '    - cron: "7 7 * * *"\n'
        '    - cron: "7 7 * * *"\n'
    )
    with pytest.raises(RuntimeError, match=r"found 2"):
        rewrite_cron(text, "theoju", "dogfood")


def test_rewrite_cron_preserves_spacing_CI1_regression() -> None:
    """CI1 (3-validator panel finding): the regex must preserve the space between
    the minute and the first `*`. The pre-fix regex produced `42 7* * *`.
    Lock the exact rendered substring to prevent regression.
    """
    from scaffold_workflow import deterministic_cron_minute, rewrite_cron

    text = 'on:\n  schedule:\n    - cron: "7 7 * * *"\n'
    minute = deterministic_cron_minute("theoju", "dogfood")
    result = rewrite_cron(text, "theoju", "dogfood")
    assert f'cron: "{minute} 7 * * *"' in result, \
        f"cron-line spacing broken (CI1 regression). Got: {result!r}"


def test_rewrite_cron_round_trip_on_real_template() -> None:
    """Real template — output differs from input by exactly the cron line and
    parses cleanly under ruamel.yaml.

    Inline xfail guard: if Task 5 has not yet refreshed the template (cron is
    still '0 7 * * *'), this test xfails until the refresh lands.
    """
    ruamel = pytest.importorskip("ruamel.yaml")
    from scaffold_workflow import rewrite_cron

    raw = TEMPLATE.read_text()
    if '- cron: "7 7 * * *"' not in raw:
        pytest.xfail("CCE-80 plan task 5 sets cron to '7 7 * * *' in the template")

    rendered = rewrite_cron(raw, "theoju", "dogfood")
    raw_lines = raw.splitlines()
    rendered_lines = rendered.splitlines()
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(raw_lines, rendered_lines)) if a != b]
    assert len(diffs) == 1, f"expected exactly 1 differing line; got {diffs}"
    _, before, after = diffs[0]
    assert 'cron: "7 7 * * *"' in before
    assert 'cron: "' in after
    # Whatever minute is in the rendered line, the trailing `* * *"` must persist intact.
    assert '* * *"' in after

    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.load(rendered)  # raises on malformed YAML

    if shutil.which("actionlint") is None:
        pytest.skip("actionlint not on PATH")
    proc = subprocess.run(["actionlint", "-"], input=rendered, capture_output=True, text=True)
    assert proc.returncode == 0, f"actionlint failed:\n{proc.stdout}{proc.stderr}"


def test_cli_smoke() -> None:
    """Invoke the helper as a script. Inline xfail guard for pre-task-5 state."""
    if not TEMPLATE.exists() or '- cron: "7 7 * * *"' not in TEMPLATE.read_text():
        pytest.xfail("CCE-80 plan task 5 refreshes the template (cron + FN header)")

    from scaffold_workflow import deterministic_cron_minute

    proc = subprocess.run(
        [sys.executable, str(HELPER), "--owner", "theoju", "--repo", "dogfood"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout
    assert "# Drop into the host repo at .github/workflows/docs-agent-nightly.yml" in out
    minute = deterministic_cron_minute("theoju", "dogfood")
    assert f'- cron: "{minute} 7 * * *"' in out
```

- [ ] **Step 2: Run test — expect FAIL (ModuleNotFoundError on `scaffold_workflow`)**

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py::test_deterministic_cron_minute_stable -v
```

Expected: FAILED / ERROR with `ModuleNotFoundError: No module named 'scaffold_workflow'`.

- [ ] **Step 3: Implement scaffold_workflow.py with CI1-fixed regex** (use Write tool)

File path: `scripts/scaffold_workflow.py`. File content (verbatim):

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

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# CI1 fix: group 2 captures the whitespace AFTER the second `7` so the
# substitution `\g<1>{minute} 7\g<2>\g<3>` preserves the space (group 2 starts
# with `\s+`, NOT `*`). The pre-fix form ate the space and produced `42 7* * *`.
# Group 3 tolerates trailing whitespace or an inline comment.
_CRON_PATTERN = re.compile(r'^(\s+- cron: ")7 7(\s+\* \* \*")(.*)$', re.MULTILINE)


def deterministic_cron_minute(owner: str, repo: str) -> int:
    """Stable per-host cron minute in [5, 55].

    Same owner/repo → same minute (no diff churn on re-scaffold).
    SHA-256 mod 51 over distinct owner/repo strings is uniform across [0, 50];
    offset to [5, 55] to stay within GitHub off-minute guidance.
    """
    digest = hashlib.sha256(f"{owner}/{repo}".encode()).hexdigest()
    return int(digest, 16) % 51 + 5


def rewrite_cron(text: str, owner: str, repo: str) -> str:
    """Replace `cron: "7 7 * * *"` with the deterministic per-host minute.

    Anchored substitution. Raises if the template has zero or more than one
    matching line (structural drift guard).
    """
    minute = deterministic_cron_minute(owner, repo)
    new_text, n = _CRON_PATTERN.subn(rf'\g<1>{minute} 7\g<2>\g<3>', text)
    if n != 1:
        raise RuntimeError(
            f"Expected exactly 1 cron line matching the anchor; found {n}. "
            "Template structure changed — update scripts/scaffold_workflow.py "
            "or its tests."
        )
    return new_text


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--template",
        default=None,
        help='Template path; "-" for stdin; default plugin templates/workflow-run.yml',
    )
    parser.add_argument("--out", default=None, help="Output path; default stdout")
    args = parser.parse_args()

    if args.template == "-":
        text = sys.stdin.read()
    elif args.template:
        text = Path(args.template).read_text()
    else:
        plugin_root = Path(__file__).resolve().parent.parent
        text = (plugin_root / "templates" / "workflow-run.yml").read_text()

    rendered = rewrite_cron(text, args.owner, args.repo)

    if args.out:
        Path(args.out).write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run all 7 tests**

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py -v
```

Expected: 5 PASSED (`test_deterministic_cron_minute_stable`, `test_known_fixture_minutes`, `test_cron_minute_bounds`, `test_rewrite_cron_anchor_zero_matches_raises`, `test_rewrite_cron_anchor_two_matches_raises`, `test_rewrite_cron_preserves_spacing_CI1_regression`); 2 xfailed (`test_rewrite_cron_round_trip_on_real_template`, `test_cli_smoke`) — those use inline `pytest.xfail()` guards that fire until Task 5 refreshes the template.

Actually that's 6 passed + 2 xfailed = 8 results. Verify the CI1-regression test passes — that's the load-bearing one.

- [ ] **Step 5: Run full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected shape: `<N>+6 passed, <M> skipped, 10 xfailed in <T>s` (8 parity + 2 inline-guard scaffold).

- [ ] **Step 6: Commit**

```bash
git add scripts/scaffold_workflow.py tests/setup/test_scaffold_workflow.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): scripts/scaffold_workflow.py — deterministic per-host cron rewrite

Stdlib-only helper invoked by the setup skill at SKILL.md step 6. SHA-256
of `<owner>/<repo>` mod 51 + 5 yields a stable minute in [5, 55] — same
input always produces the same output (no diff churn on re-scaffold), and
100 hosts won't pile up at :07 UTC.

CI1 fix (from 3-validator panel): _CRON_PATTERN captures the space between
the minute and the first `*` inside group 2, so the substitution preserves
it. The pre-fix form ate the space and produced `42 7* * *`. Locked by
test_rewrite_cron_preserves_spacing_CI1_regression.

Tests cover: determinism, fixture lock-in, bounds [5, 55], anchor sanity
(zero/two-match raise), CI1 spacing regression, real-template round-trip
(inline xfail-guarded until Task 5), CLI smoke (likewise).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `scripts/setup_discover.discover_git_origin()` (TDD)

**Files:**

- Modify: `scripts/setup_discover.py` (add `discover_git_origin()` + integrate into `discover()` under `"git"` key)
- Modify: `tests/setup/test_setup_discover.py` (append 3 cases at end of file)

**Why:** SKILL.md step 6 needs `discovery["git"]["owner"]` and `discovery["git"]["repo"]` to invoke `scaffold_workflow.py`. The current `setup_discover.py` does not emit these.

- [ ] **Step 1: Append 3 failing tests to `tests/setup/test_setup_discover.py`**

Use the Read tool first to confirm the current end-of-file state. Then use the Edit tool with `old_string` = the file's current last 1–2 lines (whatever they are) and `new_string` = those same lines followed by the 3 new tests below.

The 3 new test functions to APPEND:

```python


def test_discover_git_origin_https_url(tmp_path, monkeypatch) -> None:
    """HTTPS clone URL → {owner, repo} extracted."""
    import subprocess

    import setup_discover

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="https://github.com/theoju/engineering-docs-agent.git\n",
            stderr="",
        )

    monkeypatch.setattr(setup_discover.subprocess, "run", fake_run)

    result = setup_discover.discover_git_origin(tmp_path)
    assert result == {"owner": "theoju", "repo": "engineering-docs-agent"}


def test_discover_git_origin_ssh_url(tmp_path, monkeypatch) -> None:
    """SSH clone URL → {owner, repo} extracted."""
    import subprocess

    import setup_discover

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="git@github.com:theoju/adis.git\n", stderr=""
        )

    monkeypatch.setattr(setup_discover.subprocess, "run", fake_run)

    result = setup_discover.discover_git_origin(tmp_path)
    assert result == {"owner": "theoju", "repo": "adis"}


def test_discover_git_origin_no_remote(tmp_path, monkeypatch) -> None:
    """No `origin` remote → None (caller falls back to AskUserQuestion)."""
    import subprocess

    import setup_discover

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=128,
            stdout="",
            stderr="error: No such remote 'origin'\n",
        )

    monkeypatch.setattr(setup_discover.subprocess, "run", fake_run)

    assert setup_discover.discover_git_origin(tmp_path) is None
```

Note: the monkeypatch target is `setup_discover.subprocess.run` (module-attribute) — V2-R4 verified this is the correct pattern given that `setup_discover.py` uses `import subprocess` (not `from subprocess import run`).

- [ ] **Step 2: Run tests — expect 3 FAILED with ImportError**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py::test_discover_git_origin_https_url tests/setup/test_setup_discover.py::test_discover_git_origin_ssh_url tests/setup/test_setup_discover.py::test_discover_git_origin_no_remote -v
```

Expected: 3 FAILED. The error may be `ImportError: cannot import name 'discover_git_origin'` OR `AttributeError: module 'setup_discover' has no attribute 'discover_git_origin'` depending on how the test imports. Either is fine — the function doesn't exist yet.

- [ ] **Step 3: Edit `scripts/setup_discover.py` — add `import re, subprocess`** (use Edit tool)

Current state of line 4:

```python
import argparse, json, sys
```

Use Edit with:

- `old_string`: `import argparse, json, sys`
- `new_string`: `import argparse, json, re, subprocess, sys`

Note: this works because the original `def detect_jira_hint(...)` function imports `re` locally inside the function body. Adding it to the top is fine — the local import becomes a no-op shadowed by the module-level binding.

- [ ] **Step 4: Edit `scripts/setup_discover.py` — add `discover_git_origin()` function above `def discover(cwd: Path) -> dict:`** (use Edit tool)

Current state (around line 203):

```python
def discover(cwd: Path) -> dict:
    """Discover host repo settings. Returns a structured dict with optional warnings."""
```

Use Edit with:

- `old_string`:

```python
def discover(cwd: Path) -> dict:
    """Discover host repo settings. Returns a structured dict with optional warnings."""
```

- `new_string`:

```python
_REMOTE_PATTERN = re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?/?$")


def discover_git_origin(repo_root: Path) -> dict | None:
    """Return {owner, repo} parsed from `git remote get-url origin`, or None.

    Returns None if no `origin` remote exists, or the URL doesn't match the
    github.com pattern. Caller (SKILL.md) falls back to AskUserQuestion.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    m = _REMOTE_PATTERN.search(result.stdout.strip())
    if not m:
        return None
    return {"owner": m.group(1), "repo": m.group(2)}


def discover(cwd: Path) -> dict:
    """Discover host repo settings. Returns a structured dict with optional warnings."""
```

- [ ] **Step 5: Edit `scripts/setup_discover.py` — wire `discover_git_origin` into `discover()`** (use Edit tool)

Current state (the `out:` dict literal inside `discover()`, around line 221):

```python
    out: dict = {
        "framework": framework,
        "source_dir": source_dir,
        "lens_paths": lens_paths,
        "ci": ci,
        "jira_hint": jira_hint,
        "python": detect_python(cwd),
        "openapi_hint": detect_openapi_hint(cwd),
        "toolchain": detect_toolchain(cwd),
        "pages_publishable": detect_pages_publishable(framework, ci),
    }
```

Use Edit with:

- `old_string`: the block above (verbatim 11 lines).
- `new_string`:

```python
    out: dict = {
        "framework": framework,
        "source_dir": source_dir,
        "lens_paths": lens_paths,
        "ci": ci,
        "jira_hint": jira_hint,
        "python": detect_python(cwd),
        "openapi_hint": detect_openapi_hint(cwd),
        "toolchain": detect_toolchain(cwd),
        "pages_publishable": detect_pages_publishable(framework, ci),
        "git": discover_git_origin(cwd),
    }
```

- [ ] **Step 6: Run the 3 new tests — expect PASS**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py::test_discover_git_origin_https_url tests/setup/test_setup_discover.py::test_discover_git_origin_ssh_url tests/setup/test_setup_discover.py::test_discover_git_origin_no_remote -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Run full setup_discover suite — no regressions**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py -v
```

Expected: all existing setup_discover tests pass + the 3 new tests pass.

- [ ] **Step 8: Run full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected shape: pass count up by 3 vs Task 2; xfail count unchanged (still 10).

- [ ] **Step 9: Commit**

```bash
git add scripts/setup_discover.py tests/setup/test_setup_discover.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): setup_discover.discover_git_origin() — emit {owner, repo}

Parses `git remote get-url origin` to feed SKILL.md step 6's invocation of
scripts/scaffold_workflow.py. Handles SSH and HTTPS URLs; returns None when
no origin remote exists so the caller can fall back to AskUserQuestion.

Integrated into discover() under the new "git" key — additive to existing
discovery shape. Three new tests cover SSH, HTTPS, and missing-remote paths.
Monkeypatches setup_discover.subprocess.run (module-attribute) per the
existing setup-discover-test convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SKILL.md edits + `tests/skills/test_setup_skill_md.py` (TDD grep)

**Files:**

- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_setup_skill_md.py`
- Modify: `skills/engineering-docs-agent-setup/SKILL.md` (single Edit to line 33 + single Edit to step 8)

**Why:** Spec §5.3.2 / §5.3.3. The grep test locks the FN rename + the helper invocation + the App-token warning.

**CI11 fix:** SKILL.md line 33 has both `(CCE-57)` (with parens) and `CCE-70` (no parens). The Edit's `old_string` targets the entire line 33 verbatim, leaving no ambiguity.

**CI12 fix:** Drop the "6c BEFORE 6a" / "6b AFTER 6a" contradiction — use 6b inserted immediately AFTER existing 6a.

**CI6 fix:** Replace the dead-code assertion (`'host CI' in text or 'host CI' in text.lower()`) with `'host CI' in text or 'host ci' in text.lower()`.

- [ ] **Step 1: Create test package marker**

Run:

```bash
mkdir -p tests/skills && : > tests/skills/__init__.py
```

- [ ] **Step 2: Write the 4-test grep file** (use Write tool)

File path: `tests/skills/test_setup_skill_md.py`. File content (verbatim):

```python
"""Grep-style integration test for SKILL.md edits (CCE-80 spec §6.3).

Locks the FN rename, the scaffold_workflow.py invocation, and the App-token warning.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "engineering-docs-agent-setup" / "SKILL.md"


def _content() -> str:
    return SKILL.read_text()


def test_skill_references_docs_agent_nightly_filename() -> None:
    """FN — workflow filename matches dogfood + all 3 known hosts."""
    assert ".github/workflows/docs-agent-nightly.yml" in _content()


def test_skill_does_not_reference_legacy_filename() -> None:
    """`docs-agent-run.yml` is the pre-CCE-80 name; must be fully removed."""
    assert "docs-agent-run.yml" not in _content()


def test_skill_invokes_scaffold_workflow_helper() -> None:
    """SKILL.md step 6 must reference scripts/scaffold_workflow.py."""
    assert "scripts/scaffold_workflow.py" in _content()


def test_skill_step8_warns_about_app_token_for_ci() -> None:
    """Step 8 must surface the App-token-for-host-CI consequence.

    CI6 fix: second clause is `host ci` (lowercase) so the OR is meaningful.
    """
    text = _content()
    assert "DOCS_AGENT_APP_CLIENT_ID" in text
    assert "host CI" in text or "host ci" in text.lower() or "host_ci" in text
```

- [ ] **Step 3: Run the 4 tests — expect at least 2 FAILED**

Run:

```bash
python3 -m pytest tests/skills/test_setup_skill_md.py -v
```

Expected: `test_skill_does_not_reference_legacy_filename` FAILS, `test_skill_references_docs_agent_nightly_filename` FAILS, `test_skill_invokes_scaffold_workflow_helper` FAILS, `test_skill_step8_warns_about_app_token_for_ci` FAILS.

- [ ] **Step 4: Edit SKILL.md line 33 (single Edit, verbatim full-line)** (use Edit tool)

Use Edit with:

- `old_string`:

```
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-run.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`. (CCE-57) The shipped workflow checks out `theoju/engineering-docs-agent` into `.docs-agent-plugin/` and runs the orchestrator from that path — do not delete the checkout step. After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.
```

- `new_string`:

```
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-nightly.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`. (CCE-57, CCE-80) The shipped workflow checks out `theoju/engineering-docs-agent` into `.docs-agent-plugin/` and runs the orchestrator from that path — do not delete the checkout step. After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.
```

Two changes within the line: `docs-agent-run.yml` → `docs-agent-nightly.yml`, and `(CCE-57)` → `(CCE-57, CCE-80)`.

- [ ] **Step 5: Edit SKILL.md to insert sub-bullet 6b after existing 6a** (use Edit tool)

The existing 6a sub-bullet (around line 34) is a single long line. Use Edit with:

- `old_string`: the entire line 34 verbatim (run `head -34 skills/engineering-docs-agent-setup/SKILL.md | tail -1` to capture, OR Read the file and inspect line 34). The line begins with `   6a. If discovery's \`pages_publishable\` is true `and ends with`... "Pages deploy not scaffolded (no MkDocs site and no publishing.build_command) — add one to enable publishing." \`configure-pages(enablement:true)\` sets the repo's Pages source to GitHub Actions on first run.`
- `new_string`: the same line 34 verbatim, followed by a newline, followed by:

````
   6b. **Render the workflow file with a deterministic per-host cron minute** (CCE-80) — instead of writing the raw template, run:
       ```bash
       python <plugin_root>/scripts/scaffold_workflow.py \
           --owner "$OWNER" --repo "$REPO" \
           --out .github/workflows/docs-agent-nightly.yml
       ```
       where `OWNER`/`REPO` come from `discovery["git"]["owner"]` and `discovery["git"]["repo"]` (from `setup_discover.discover_git_origin()`). If `discovery["git"]` is `None`, fall back to `AskUserQuestion("What is the GitHub owner/repo for this host?", header="Repo", ...)`. The helper is deterministic — re-scaffolding the same host always produces the same cron minute, so no operator-visible diff churn.
````

PRACTICAL NOTE for the subagent executing this: line 34 is long; Read the file first to capture exact whitespace/indentation, then construct the Edit accordingly.

- [ ] **Step 6: Edit SKILL.md step 8 — append App-token CI warning** (use Edit tool)

The current step 8 line (line 42) reads exactly:

```
8. Print a final "next steps" summary.
```

Use Edit with:

- `old_string`: `8. Print a final "next steps" summary.`
- `new_string`:

```
8. Print a final "next steps" summary.
   Conditional warning (CCE-80): if `vars.DOCS_AGENT_APP_CLIENT_ID` is unset on the host, append this to the "next steps" output:
   > **Host CI will not run on docs-agent PRs** unless you register a GitHub App. Without `vars.DOCS_AGENT_APP_CLIENT_ID`, the workflow falls back to `secrets.GITHUB_TOKEN`, which GitHub deliberately prevents from triggering `push`/`pull_request` workflows on its own commits. To enable host CI on docs-agent PRs:
   >
   > 1. Register a GitHub App named `engineering-docs-agent` with `Contents: write`, `Pull requests: write`, `Issues: read` permissions.
   > 2. Install it on this repository.
   > 3. Set `vars.DOCS_AGENT_APP_CLIENT_ID` (the App's Client ID) and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` (PEM-form private key).
   > 4. Re-scaffold via this skill (no-op for cron; activates the App-token step).
```

- [ ] **Step 7: Run the 4 grep tests — expect PASS**

Run:

```bash
python3 -m pytest tests/skills/test_setup_skill_md.py -v
```

Expected: 4 PASSED.

- [ ] **Step 8: Run full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected shape: pass count up by 4 vs Task 3; xfail count unchanged (10).

- [ ] **Step 9: Commit**

```bash
git add tests/skills/__init__.py tests/skills/test_setup_skill_md.py skills/engineering-docs-agent-setup/SKILL.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): SKILL.md — invoke scaffold_workflow.py + App-token CI warning

Step 6 rewrites the workflow-write sub-bullet to invoke
scripts/scaffold_workflow.py with --owner/--repo from
discovery["git"], producing a deterministic per-host cron minute.
Filename updates from docs-agent-run.yml to docs-agent-nightly.yml
(matches dogfood + all 3 known hosts).

Step 8 appends a conditional warning surfaced when
vars.DOCS_AGENT_APP_CLIENT_ID is unset, explaining the host-CI
suppression consequence and the App registration flow.

tests/skills/test_setup_skill_md.py grep-locks all 4 substrings.
CI6 fix: dead-code assertion fixed (second clause now lowercase
'host ci' so the OR is meaningful).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Template absorb — CCE-39 baseline + App-token folded (commit 1/4)

**Files:**

- Modify: `templates/workflow-run.yml` (full-file overwrite via Write — 53 lines → ~155 lines)
- Modify: `tests/templates/test_workflow_run_parity.py` (lift xfails on test_04, test_05, test_07, test_08; implement bodies)

**Why a full-file Write?** 95% of the existing 53-line template is being rewritten. A single Write is cleaner and easier to review than 4–5 sequential Edits. The subagent uses Write directly; no diff-tracking needed.

**CC2 fold rationale:** actionlint 1.7.7 empirically REJECTS the `steps.app-token.outputs.token` reference when the `app-token` step doesn't exist (verified at plan-authoring time: `actionlint` exit 1, two `property "app-token" is not defined` errors). Splitting CCE-39 and App-token into two commits would push red CI between them. Folding lands both atomically — the spec's §5.1.1 5-commit sequence becomes 4 commits. This is a documented planned deviation.

**CI2 note:** the job-level `if:` expression now includes `github.event_name == 'workflow_dispatch'` so manual fires actually run when the self-loop guard is in effect. This extends spec §5.2 (which didn't explicitly authorize the manual case but operationally needs it).

**CI3 note:** Run-summary heading is `## docs-agent-nightly` (matches dogfood). No dogfood edit needed for that.

This task DOES NOT absorb: OAuth four-arm assert (Task 6), forensics (Task 7), CCE-73 stdout echo (Task 8).

- [ ] **Step 1: Write the new `templates/workflow-run.yml`** (use Write tool)

File path: `templates/workflow-run.yml`. File content (verbatim — this is the COMPLETE post-Task-5 state):

````yaml
# templates/workflow-run.yml — main authoring workflow
# Drop into the host repo at .github/workflows/docs-agent-nightly.yml (CCE-80 FN).
# This file is rendered through scripts/scaffold_workflow.py at scaffold time,
# which rewrites the cron minute to a deterministic per-host value in [5, 55]
# so 100 onboarded hosts don't all fire at :07 UTC. See SKILL.md step 6.
name: docs-agent run

on:
  schedule:
    # 07:07 UTC off-minute default; setup-skill rewrites per-host so 100 hosts don't pileup at :07.
    - cron: "7 7 * * *"
  workflow_dispatch:
    inputs:
      reason:
        description: "Optional reason for manual fire (shown in run summary)"
        required: false
        default: "manual run"
  pull_request:
    # TEMPLATE-ONLY (D4): real-time docs update on merge for hosts. Paired
    # with the job-level self-loop guard below that skips docs-agent/* branches.
    types: [closed]
    branches: [main]

permissions:
  contents: write # commit + push docs-agent/YYYY-MM-DD branch
  pull-requests: write # gh pr create + append-commit on existing PR
  issues: read # gap-detector reads linked issues (no writes)

concurrency:
  # One nightly authoring run at a time per host. Manual fires queue rather
  # than parallelize so two runs don't race on the same docs-agent/YYYY-MM-DD branch.
  group: docs-agent-nightly
  cancel-in-progress: false

jobs:
  run:
    # TEMPLATE-ONLY (D4 self-loop guard): paired with `pull_request.closed`.
    # CI2 (post-validation extension): workflow_dispatch included so manual
    # fires actually run when this gate is in effect.
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch' || (github.event.pull_request.merged == true && !startsWith(github.head_ref, 'docs-agent/'))
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
      # CCE-53: Jira basic-auth credentials surfaced so source-collector's
      # optional Jira enrichment resolves linked-issue summaries instead of
      # skipping with source_collector_error: jira_auth_missing.
      JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
      JIRA_EMAIL: ${{ vars.JIRA_EMAIL }} # CCE-66: vars (not secrets) — email is public-coordinate-style metadata.
      # TEMPLATE-ONLY: consumed by agents/notifier.md when notifications.slack.enabled: true.
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    steps:
      # Without DOCS_AGENT_APP_CLIENT_ID set, this step is skipped and the workflow
      # falls back to secrets.GITHUB_TOKEN. CONSEQUENCE: docs-agent PRs will NOT
      # trigger your host CI (push/pull_request workflows). To enable host CI on
      # docs-agent PRs, register a GitHub App named engineering-docs-agent and set
      # vars.DOCS_AGENT_APP_CLIENT_ID + secrets.DOCS_AGENT_APP_PRIVATE_KEY.
      - name: Generate GitHub App installation token
        id: app-token
        if: vars.DOCS_AGENT_APP_CLIENT_ID != ''
        # CCE-54: v3 is the first major on Node 24.
        # CCE-66: v3 deprecates `app-id` in favor of `client-id` (the OAuth Client
        # ID, format Iv1.xxx or Iv23li…, NOT the numeric App ID). Stored as a repo
        # Variable because Client IDs are not credentials.
        uses: actions/create-github-app-token@v3
        with:
          client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
          private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}

      - name: Checkout host repo
        id: checkout-host
        uses: actions/checkout@v5
        with:
          fetch-depth: 0 # full history so state.json window math sees all merges
          # CCE-45: checkout configures git's credential helper from this
          # token, so the subsequent `git push` from the runner uses the
          # App token rather than the default GITHUB_TOKEN. The `||` resolves
          # to GITHUB_TOKEN when the App-token step is skipped via its `if:`.
          token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}

      - name: Check out engineering-docs-agent plugin
        id: checkout-plugin
        # TEMPLATE-ONLY (#13): vendor the plugin's scripts/ directory into
        # the runner workspace at .docs-agent-plugin so the orchestrator
        # step can invoke it. `ref: v0.5.0` per CCE-80 §5.4 (PR author cuts
        # the tag <5 min post-merge; tag-cut gates the host migration runbook).
        uses: actions/checkout@v5
        with:
          repository: theoju/engineering-docs-agent
          ref: v0.5.0
          path: .docs-agent-plugin

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Install runtime dependencies
        # Matches release.yml — the flat scripts/ layout isn't pip-installable.
        run: |
          python -m pip install --upgrade pip
          python -m pip install pyyaml jsonschema

      - name: Install claude CLI
        run: |
          npm install -g @anthropic-ai/claude-code
          which claude || (echo "claude CLI not installed" && exit 1)

      - name: Configure git identity
        id: git-identity
        # The runner does `git commit` itself; without an identity it errors
        # out before reaching the PR step.
        run: |
          git config user.name "engineering-docs-agent[bot]"
          git config user.email "engineering-docs-agent@users.noreply.github.com"

      - name: Run docs-agent
        id: docs-agent
        env:
          # CCE-45: GH_TOKEN sourced from the GitHub App installation token
          # (or GITHUB_TOKEN fallback). Lives at step-env (not job-env) because
          # GitHub's runtime validator rejects `steps.*` references at job-env scope.
          GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}
        run: |
          python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .

      - name: Run summary
        if: always()
        # CI3 (post-validation): heading text standardized to `## docs-agent-nightly`
        # to match dogfood, even though the runner is named `docs-agent`. The heading
        # describes the rendered workflow filename (the operator-facing identifier).
        # workflow_dispatch.inputs.reason is user-controlled; pass via env and
        # dereference as a shell var rather than interpolating into the script body.
        env:
          TRIGGER: ${{ github.event_name }}
          REASON: ${{ inputs.reason }}
        run: |
          {
            echo "## docs-agent-nightly"
            echo ""
            echo "- **Run trigger:** \`$TRIGGER\`"
            if [ "$TRIGGER" = "workflow_dispatch" ]; then
              printf -- "- **Reason:** %s\n" "$REASON"
            fi
            echo "- **HEAD:** \`$(git rev-parse --short HEAD)\`"
            echo "- **State file (post-run):**"
            echo '  ```json'
            if [ -f .engineering-docs-agent/state.json ]; then
              jq -e '.' .engineering-docs-agent/state.json 2>/dev/null | sed 's/^/  /' || echo "  (invalid or empty state)"
            else
              echo "  (no state)"
            fi
            echo '  ```'
          } >> "$GITHUB_STEP_SUMMARY"
````

- [ ] **Step 2: Lint with actionlint — expect CLEAN**

Run:

```bash
actionlint templates/workflow-run.yml
```

Expected: NO output, exit code 0. If actionlint flags anything, fix before proceeding — the fold means there should be no dangling step references.

If actionlint is not on PATH, skip with a note; CI catches it. The plan-author EMPIRICALLY verified at plan-authoring time that the post-Task-5 state is actionlint-clean (when both `app-token` step and `steps.app-token.outputs.token` references coexist).

- [ ] **Step 3: Lift parity-test xfails on test_04, test_05, test_07, test_08** (use Edit tool)

In `tests/templates/test_workflow_run_parity.py`, replace each function definition:

For `test_04_literal_equals_shape_contract` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: literal-equals shape contract on CCE-39 baseline + App-token folded")
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- `new_string`:

```python
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    """Locked literal values shared by both files (CCE-39 baseline)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        conc = doc["concurrency"]
        assert conc["group"] == "docs-agent-nightly", f"{label}: concurrency.group != docs-agent-nightly"
        assert conc["cancel-in-progress"] is False, f"{label}: cancel-in-progress != false"
        jobs = list(doc["jobs"].values())
        assert len(jobs) == 1, f"{label}: expected exactly 1 job"
        assert jobs[0]["timeout-minutes"] == 60, f"{label}: timeout-minutes != 60"
        perms = doc["permissions"]
        for k in ("contents", "pull-requests", "issues"):
            assert k in perms, f"{label}: missing permissions.{k}"
        env = jobs[0]["env"]
        for k in ("CLAUDE_CODE_OAUTH_TOKEN", "JIRA_API_TOKEN", "JIRA_EMAIL"):
            assert k in env, f"{label}: missing job-env {k}"
        triggers = doc["on"]
        assert "schedule" in triggers, f"{label}: missing schedule trigger"
        assert "workflow_dispatch" in triggers, f"{label}: missing workflow_dispatch trigger"
```

For `test_05_app_token_conditional_shape` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: App-token conditional shape (template-only properties)")
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- `new_string`:

```python
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    """Template-only property tests on the App-token wiring.

    The TEMPLATE has the `if:` opt-out gate (hosts may skip the App-token step);
    the DOGFOOD does not (we own this repo's auth). The dogfood divergence is
    intentional — documented in _TEMPLATE_ONLY_DIVERGENCES.
    """
    template_jobs = list(template_doc["jobs"].values())
    template_steps = template_jobs[0]["steps"]

    app_token = next((s for s in template_steps if s.get("id") == "app-token"), None)
    assert app_token is not None, "template missing app-token step"
    assert "vars.DOCS_AGENT_APP_CLIENT_ID != ''" in str(app_token.get("if", "")), \
        "template app-token step missing opt-out `if:`"
    assert app_token.get("uses") == "actions/create-github-app-token@v3"
    assert "client-id" in app_token["with"], "app-token must use `client-id` (not deprecated `app-id`)"

    checkout = next((s for s in template_steps if s.get("id") == "checkout-host"), None)
    assert checkout is not None, "template missing checkout-host step"
    token_expr = "".join(str(checkout["with"]["token"]).split())
    expected = "${{steps.app-token.outputs.token||secrets.GITHUB_TOKEN}}"
    assert token_expr == expected, \
        f"checkout-host token wiring mismatch: got {token_expr}, expected {expected}"

    authoring = next((s for s in template_steps if s.get("id") == "docs-agent"), None)
    assert authoring is not None, "template missing docs-agent authoring step"
    gh_token_expr = "".join(str(authoring["env"]["GH_TOKEN"]).split())
    assert gh_token_expr == expected, \
        f"authoring step GH_TOKEN mismatch: got {gh_token_expr}, expected {expected}"
```

For `test_07_run_summary_if_always` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: run-summary `if: always()` (CCE-39 baseline)")
def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- `new_string`:

```python
def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    """Run-summary step must have `if: always()` so partial/failed runs render."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        jobs = list(doc["jobs"].values())
        steps = jobs[0]["steps"]
        run_summary_steps = [s for s in steps if s.get("name") == "Run summary"]
        assert len(run_summary_steps) == 1, f"{label}: expected exactly 1 'Run summary' step"
        if_expr = str(run_summary_steps[0].get("if", ""))
        assert if_expr.startswith("always()"), f"{label}: run-summary if `{if_expr}` does not start with always()"
```

For `test_08_on_key_regression` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: on-key regression guard (catches PyYAML escape route)")
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- `new_string`:

```python
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    """Top-level `on:` key must parse as a string-keyed mapping, NOT the YAML-1.1
    boolean True (the PyYAML SafeLoader escape route). Regression guard.
    """
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        on_val = doc["on"]
        assert isinstance(on_val, dict), f"{label}: top-level `on:` is {type(on_val).__name__}, expected dict"
```

- [ ] **Step 4: Run the parity test — expect 4 newly PASSED + 4 still XFAILED**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: `test_04`, `test_05`, `test_07`, `test_08` PASSED; `test_01`, `test_02`, `test_03`, `test_06` still XFAILED.

- [ ] **Step 5: Run scaffold_workflow tests — inline xfail guards now lift**

After Task 5 the template contains `cron: "7 7 * * *"` + the new FN header. Both inline-xfail-guarded tests now run their full bodies:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py -v
```

Expected: 8 PASSED (6 from Task 2 + the 2 that were inline-xfail-guarded — `test_rewrite_cron_round_trip_on_real_template`, `test_cli_smoke`). 0 xfailed.

**On the lifting mechanism** (CI5 clarification): both tests use inline `if <condition>: pytest.xfail(...)` early-returns. When Task 5 lands the template, `<condition>` becomes false, the early-return doesn't fire, and the test body runs its assertions normally. **This is NOT a decorator-based xfail** — those would require code changes here.

- [ ] **Step 6: Run full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected shape: pass count up by ≥ 5 vs Task 4; xfail count drops from 10 to 4.

- [ ] **Step 7: Commit**

```bash
git add templates/workflow-run.yml tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-39 baseline + CCE-45/CCE-66 App-token (folded)

Lands BOTH the CCE-39 baseline (triggers, permissions, concurrency,
timeout, job-env, install steps, identity, run-summary) AND the
CCE-45/CCE-66 App-token step in a single commit.

POST-VALIDATION FOLD (CC2): actionlint 1.7.7 empirically rejects the
`steps.app-token.outputs.token` reference when the `app-token` step
doesn't yet exist (verified at plan-authoring: exit 1, two
property-not-defined errors). Splitting into two commits per spec §5.1.1
would push red CI between them. This commit lands both atomically —
documented planned deviation from the 5-commit sequence to a 4-commit
sequence (Tasks 5/6/7/8 of the post-validation plan).

App-token step uses `client-id` (not deprecated `app-id` — v3 rename).
CCE-54: action pinned to @v3 (Node-24 floor). DOCS_AGENT_APP_CLIENT_ID
opt-out gate: hosts that don't register the App fall through to
secrets.GITHUB_TOKEN via the || fallback wired at checkout-host and
docs-agent step-env. Their docs-agent PRs won't trigger downstream host
CI (deliberate GHA self-loop prevention).

CI2 extension: workflow_dispatch added to the job-level if: expression
so manual fires actually run when the self-loop guard is in effect.
CI3 alignment: Run-summary heading standardized to `## docs-agent-nightly`
to match dogfood and operator-facing filename.

Plugin checkout pinned to v0.5.0 — PR author cuts tag <5 min post-merge
per spec §5.4. Filename rename to docs-agent-nightly.yml in the header
comment closes FN locked-decision.

Lifts xfails on test_04 (literal-equals shape), test_05 (App-token
template-only properties), test_07 (run-summary if always()), test_08
(PyYAML on-key regression). scaffold_workflow inline-xfail-guarded tests
auto-pass now that the template has the `7 7` cron + FN header.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Template absorb — OAuth four-arm assert (CCE-49) (commit 2/4)

**Files:**

- Modify: `templates/workflow-run.yml` (insert OAuth-assert step after "Install claude CLI", before "Configure git identity")

**What this absorbs:** Step 13 of §5.1.0 (OAuth four-arm pre-flight) with the `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT` opt-out gate.

- [ ] **Step 1: Insert the OAuth-assert step into `templates/workflow-run.yml`** (use Edit tool)

Use Edit with:

- `old_string`:

```yaml
- name: Install claude CLI
  run: |
    npm install -g @anthropic-ai/claude-code
    which claude || (echo "claude CLI not installed" && exit 1)

- name: Configure git identity
```

- `new_string`:

```yaml
- name: Install claude CLI
  run: |
    npm install -g @anthropic-ai/claude-code
    which claude || (echo "claude CLI not installed" && exit 1)

- name: Assert OAuth token (sk-ant-oat*, len ≥ 32)
  id: assert-oauth
  if: vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true'
  # Enterprise / Bedrock / Vertex hosts use different auth — set
  # `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT` to `'true'` to skip this check.
  # CCE-49: three layered checks, cheapest first.
  shell: bash
  run: |
    if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
      echo "::error::CLAUDE_CODE_OAUTH_TOKEN is empty or unset. Set it in repo secrets."
      exit 1
    fi
    case "$CLAUDE_CODE_OAUTH_TOKEN" in
      sk-ant-oat*) ;;
      sk-ant-api*) echo "::error::CLAUDE_CODE_OAUTH_TOKEN looks like a console API key (sk-ant-api*). The Claude CLI reads the OAuth slot (sk-ant-oat*). Run 'claude setup-token' and paste that value."; exit 1 ;;
      *) echo "::error::CLAUDE_CODE_OAUTH_TOKEN has unexpected prefix. Expected sk-ant-oat*. Got prefix: ${CLAUDE_CODE_OAUTH_TOKEN:0:10}..."; exit 1 ;;
    esac
    if [ ${#CLAUDE_CODE_OAUTH_TOKEN} -lt 32 ]; then
      echo "::error::CLAUDE_CODE_OAUTH_TOKEN is suspiciously short (${#CLAUDE_CODE_OAUTH_TOKEN} chars). Likely truncated paste."
      exit 1
    fi

- name: Configure git identity
```

- [ ] **Step 2: Lint with actionlint and shellcheck**

Run actionlint:

```bash
actionlint templates/workflow-run.yml
```

Expected: clean.

Shellcheck the OAuth body — use Write to create the test script (CI8 fix: include `set -u` and dummy var binding so SC2154 doesn't false-positive):

Use Write to create `/tmp/oauth-assert.sh`:

```bash
#!/usr/bin/env bash
# shellcheck disable=SC2154  # CLAUDE_CODE_OAUTH_TOKEN supplied via env: at GHA runtime
set -eu
CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-}"

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  echo "::error::CLAUDE_CODE_OAUTH_TOKEN is empty or unset. Set it in repo secrets."
  exit 1
fi
case "$CLAUDE_CODE_OAUTH_TOKEN" in
  sk-ant-oat*) ;;
  sk-ant-api*) echo "::error::CLAUDE_CODE_OAUTH_TOKEN looks like a console API key (sk-ant-api*). The Claude CLI reads the OAuth slot (sk-ant-oat*). Run 'claude setup-token' and paste that value."; exit 1 ;;
  *) echo "::error::CLAUDE_CODE_OAUTH_TOKEN has unexpected prefix. Expected sk-ant-oat*. Got prefix: ${CLAUDE_CODE_OAUTH_TOKEN:0:10}..."; exit 1 ;;
esac
if [ ${#CLAUDE_CODE_OAUTH_TOKEN} -lt 32 ]; then
  echo "::error::CLAUDE_CODE_OAUTH_TOKEN is suspiciously short (${#CLAUDE_CODE_OAUTH_TOKEN} chars). Likely truncated paste."
  exit 1
fi
```

Then:

```bash
shellcheck /tmp/oauth-assert.sh
```

Expected: clean. If shellcheck not on PATH, skip with note.

- [ ] **Step 3: Run parity test — same 4 passed + 4 xfailed (no new lifts in this task)**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: unchanged `4 passed, 4 xfailed`.

- [ ] **Step 4: Run full suite — qualitative invariant**

Run:

```bash
python3 -m pytest --tb=no -q
```

Expected shape: pass count unchanged vs Task 5; xfail count unchanged (4).

- [ ] **Step 5: Commit**

```bash
git add templates/workflow-run.yml
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-49 OAuth four-arm pre-flight assert (step 13)

Three-layered substring check on CLAUDE_CODE_OAUTH_TOKEN: non-empty,
sk-ant-oat* prefix (with sk-ant-api* arm that points to claude setup-token),
length ≥ 32. ::error:: annotations surface in the GHA UI.

vars.DOCS_AGENT_SKIP_OAUTH_ASSERT='true' opt-out is TEMPLATE-ONLY —
dogfood doesn't carry the gate (we own this repo's auth). Documented in
_TEMPLATE_ONLY_DIVERGENCES in tests/templates/test_workflow_run_parity.py.
Shellcheck-clean (CI8 fix: extracted script template includes
SC2154-disable + dummy binding for the env-supplied var).

No xfails lift this task; substring assertions wait for the full set
including CCE-73 partial_reasons (Task 8).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Template absorb — CCE-41 subagent forensics (commit 3/4)

**Files:**

- Modify: `templates/workflow-run.yml` (add `DOCS_AGENT_DEBUG_DIR` to docs-agent step-env; insert upload-artifact forensics step after docs-agent)

**What this absorbs:** Steps 15 (DOCS_AGENT_DEBUG_DIR step-env) and 16 (Upload subagent forensics) of §5.1.0.

- [ ] **Step 1: Add `DOCS_AGENT_DEBUG_DIR` to docs-agent step-env** (use Edit tool)

Use Edit with:

- `old_string`:

```yaml
- name: Run docs-agent
  id: docs-agent
  env:
    # CCE-45: GH_TOKEN sourced from the GitHub App installation token
    # (or GITHUB_TOKEN fallback). Lives at step-env (not job-env) because
    # GitHub's runtime validator rejects `steps.*` references at job-env scope.
    GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}
```

- `new_string`:

```yaml
- name: Run docs-agent
  id: docs-agent
  env:
    # SP-1 / CCE-41: forensics capture mode. Per-dispatch
    # prompt/stdout/stderr/stream/meta land in this dir; the
    # upload-artifact step below persists them past the runner.
    # See scripts/orchestrator_runner.py:357.
    DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug
    # CCE-45: GH_TOKEN sourced from the GitHub App installation token
    # (or GITHUB_TOKEN fallback). Lives at step-env (not job-env) because
    # GitHub's runtime validator rejects `steps.*` references at job-env scope.
    GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Insert upload-artifact step after docs-agent** (use Edit tool)

Use Edit with:

- `old_string`:

```yaml
        run: |
          python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .

      - name: Run summary
```

- `new_string`:

```yaml
        run: |
          python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .

      - name: Upload subagent forensics
        # SP-1 / CCE-41: persist forensics on success AND failure (failure is
        # the primary use case). `if-no-files-found: warn` tolerates a runner
        # step that fails before any dispatch happens (config invalid, state
        # corrupted) without breaking the workflow. github.run_id is appended
        # because v4+ disallow duplicate artifact names within a run.
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: docs-agent-subagent-forensics-${{ github.run_id }}
          path: ${{ runner.temp }}/docs-agent-debug/
          retention-days: 14
          if-no-files-found: warn

      - name: Run summary
```

- [ ] **Step 3: Lint**

```bash
actionlint templates/workflow-run.yml
```

Expected: clean.

- [ ] **Step 4: Run parity test + full suite — no new lifts; qualitative invariant**

```bash
python3 -m pytest --tb=no -q
```

Expected: pass/xfail counts unchanged vs Task 6.

- [ ] **Step 5: Commit**

```bash
git add templates/workflow-run.yml
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-41 subagent forensics (steps 15–16)

Adds DOCS_AGENT_DEBUG_DIR=${{ runner.temp }}/docs-agent-debug to the
docs-agent step-env (read by scripts/orchestrator_runner.py:357), and an
actions/upload-artifact@v6 step with `if: always()` so failed runs persist
the forensics trail. retention-days: 14 + if-no-files-found: warn tolerate
the runner crashing before any dispatch runs.

No xfails lift this task; the forensics-substring assertion is part of the
test_01 step-signature parity check which lifts in Task 8 alongside the
CCE-73 bundle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Template absorb — CCE-73 stdout echo + dogfood co-edits (commit 4/4)

**Files:**

- Modify: `templates/workflow-run.yml` (add Print partial-run reasons step after Run summary)
- Modify: `.github/workflows/docs-agent-nightly.yml` — **TWO dogfood co-edits**:
  1. Add `id: checkout-host` to the existing checkout step (CC1 fix — required for test_01 step-signature parity)
  2. Append the SAME Print partial-run reasons step (CCE-73 bundle per locked decision CO-EDIT)
- Modify: `tests/templates/test_workflow_run_parity.py` (lift xfails on test_01, test_02, test_03, test_06; implement bodies)

**Why both files?** Locked decision CO-EDIT (spec §3): bundle CCE-73 into THIS PR so the parity test can fully lift at merge time. The dogfood `id: checkout-host` addition (CC1 fix from 3-validator panel) aligns dogfood's step signature with the template's, eliminating one of the two missing-in-template signatures `test_01` would otherwise flag.

- [ ] **Step 1: Add Print partial-run reasons step to TEMPLATE** (use Edit tool)

Use Edit with:

- `old_string`: the Run summary step's full closing — specifically the last few lines including the `} >> "$GITHUB_STEP_SUMMARY"` line:

````yaml
echo '  ```'
} >> "$GITHUB_STEP_SUMMARY"
````

- `new_string`:

````yaml
            echo '  ```'
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Print partial-run reasons
        # CCE-73: echo state.json.current_run.partial_reasons to stdout so
        # they show in `gh run view --log` even when the run-summary block
        # is collapsed. `// empty` null-safe + `|| true` so a malformed
        # state.json doesn't fail this step.
        if: always()
        shell: bash
        run: |
          state=".engineering-docs-agent/state.json"
          if [ -f "$state" ]; then
            jq -r '.current_run.partial_reasons[]? // empty' "$state" || true
          fi
````

- [ ] **Step 2: Add `id: checkout-host` to DOGFOOD checkout step** (use Edit tool)

The CC1 fix. The existing dogfood checkout step (`.github/workflows/docs-agent-nightly.yml` lines 65–71) currently reads:

```yaml
- uses: actions/checkout@v5
  with:
    fetch-depth: 0 # full history so state.json window math sees all merges
    # CCE-45: checkout configures git's credential helper from this
    # token, so the subsequent `git push` from the runner uses the
    # App token rather than the default GITHUB_TOKEN.
    token: ${{ steps.app-token.outputs.token }}
```

Use Edit with:

- `old_string`:

```yaml
- uses: actions/checkout@v5
  with:
    fetch-depth: 0 # full history so state.json window math sees all merges
    # CCE-45: checkout configures git's credential helper from this
    # token, so the subsequent `git push` from the runner uses the
    # App token rather than the default GITHUB_TOKEN.
    token: ${{ steps.app-token.outputs.token }}
```

- `new_string`:

```yaml
- name: Checkout host repo
  id: checkout-host
  uses: actions/checkout@v5
  with:
    fetch-depth: 0 # full history so state.json window math sees all merges
    # CCE-45: checkout configures git's credential helper from this
    # token, so the subsequent `git push` from the runner uses the
    # App token rather than the default GITHUB_TOKEN.
    token: ${{ steps.app-token.outputs.token }}
```

This addition does TWO things: adds `name:` for clarity in GHA logs, and adds `id: checkout-host` so the step's signature in test_01 becomes `uses:actions/checkout@v5#checkout-host`, matching the template.

- [ ] **Step 3: Append Print partial-run reasons step to DOGFOOD** (use Edit tool)

The dogfood file ends with the Run summary step. Use Edit to append after it. Use Edit with:

- `old_string`: the dogfood Run summary's last 3 lines verbatim — specifically:

````yaml
echo '  ```'
} >> "$GITHUB_STEP_SUMMARY"
````

- `new_string`:

````yaml
            echo '  ```'
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Print partial-run reasons
        # CCE-73 (bundled in CCE-80 PR per CO-EDIT locked decision): echo
        # state.json.current_run.partial_reasons to stdout so they show in
        # `gh run view --log` even when the run-summary block is collapsed.
        if: always()
        shell: bash
        run: |
          state=".engineering-docs-agent/state.json"
          if [ -f "$state" ]; then
            jq -r '.current_run.partial_reasons[]? // empty' "$state" || true
          fi
````

PRACTICAL NOTE: if Step 1 of this task already used this exact `old_string` pattern in the template Edit, the same pattern appears in two different files. Use the Edit tool with each file specified explicitly to avoid ambiguity. The Edit tool operates on a single file at a time, so this isn't a real ambiguity — just be explicit about the file path.

- [ ] **Step 4: Lint both files**

```bash
actionlint templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml
```

Expected: clean.

- [ ] **Step 5: Lift parity-test xfails on test_01, test_02, test_03, test_06** (use Edit tool, 4 edits)

For `test_01_step_signature_parity` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: full step-signature parity awaits CCE-73 stdout echo bundle + dogfood id co-edit")
def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")
```

- `new_string`:

```python
def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    """For each step in dogfood, the template has a step with the same uses:
    or run-first-line signature, modulo _ALLOWLIST. Match on signature + id."""
    template_steps = list(template_doc["jobs"].values())[0]["steps"]
    dogfood_steps = list(dogfood_doc["jobs"].values())[0]["steps"]

    def _signature(step: dict) -> str:
        uses = step.get("uses")
        sid = step.get("id")
        if uses:
            return f"uses:{uses}" + (f"#{sid}" if sid else "")
        run = step.get("run", "")
        first = (run.splitlines() or [""])[0].strip()
        return f"run:{first}"

    template_sigs = {_signature(s) for s in template_steps}
    dogfood_sigs = {_signature(s) for s in dogfood_steps}

    missing_in_template = dogfood_sigs - template_sigs - set(_ALLOWLIST)
    assert not missing_in_template, (
        "Dogfood steps with no template counterpart and no allowlist entry: "
        f"{sorted(missing_in_template)}.\n"
        "Action: absorb into templates/workflow-run.yml OR add an _ALLOWLIST "
        "entry in tests/templates/test_workflow_run_parity.py with rationale."
    )
```

For `test_02_with_key_contract` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: with-key contract on all absorbed actions")
def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")
```

- `new_string`:

```python
def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    """Each step using an action listed in _WITH_KEY_CONTRACT has the
    documented keys present. Extra keys are allowed."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        for step in steps:
            uses = step.get("uses")
            if uses in _WITH_KEY_CONTRACT:
                with_block = step.get("with") or {}
                expected = _WITH_KEY_CONTRACT[uses]
                # checkout-plugin step legitimately doesn't carry `token:`.
                if uses == "actions/checkout@v5" and step.get("id") == "checkout-plugin":
                    continue
                missing = expected - set(with_block.keys())
                assert not missing, (
                    f"{label}: step `{step.get('name')}` uses {uses} but "
                    f"missing required with: keys {sorted(missing)}"
                )
```

For `test_03_high_value_substring_asserts` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: substring asserts include partial_reasons (CCE-73 bundle)")
def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")
```

- `new_string`:

```python
def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    """Substring asserts on the parsed `run:` scalar (not raw bytes)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        run_blocks = [s.get("run", "") for s in steps]
        joined = "\n---\n".join(str(r) for r in run_blocks)

        assert "sk-ant-oat" in joined, f"{label}: missing sk-ant-oat assertion"
        assert "sk-ant-api" in joined, f"{label}: missing sk-ant-api arm"
        assert "which claude" in joined, f"{label}: missing which-claude verify"
        assert "engineering-docs-agent[bot]" in joined, f"{label}: missing bot identity"
        assert "partial_reasons" in joined, f"{label}: missing partial_reasons echo (CCE-73 bundle)"
```

For `test_06_stale_allowlist_entries` — Edit with:

- `old_string`:

```python
@pytest.mark.xfail(reason="CCE-80 plan task 8 lifts: allowlist orphan/redundant guards run when all steps present")
def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")
```

- `new_string`:

```python
def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    """Every _ALLOWLIST entry matches at least one step; no entry matches a step
    present in BOTH (redundant-allowlist guard)."""
    template_steps = list(template_doc["jobs"].values())[0]["steps"]
    dogfood_steps = list(dogfood_doc["jobs"].values())[0]["steps"]

    def _signature(step: dict) -> str:
        uses = step.get("uses")
        sid = step.get("id")
        if uses:
            return f"uses:{uses}" + (f"#{sid}" if sid else "")
        run = step.get("run", "")
        first = (run.splitlines() or [""])[0].strip()
        return f"run:{first}"

    template_sigs = {_signature(s) for s in template_steps}
    dogfood_sigs = {_signature(s) for s in dogfood_steps}

    for key in _ALLOWLIST:
        in_template = key in template_sigs
        in_dogfood = key in dogfood_sigs
        if not (in_template or in_dogfood):
            raise AssertionError(
                f"stale allowlist entry `{key}` — no matching step in dogfood "
                f"or template. Delete from _ALLOWLIST or update."
            )
        if in_template and in_dogfood:
            raise AssertionError(
                f"redundant allowlist entry `{key}` — present in both files. "
                "Remove from _ALLOWLIST."
            )
```

- [ ] **Step 6: Run parity test — expect all 8 PASSED**

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: 8 PASSED, 0 xfailed.

- [ ] **Step 7: Run full suite — qualitative invariant**

```bash
python3 -m pytest --tb=no -q
```

Expected shape: pass count up by 4 vs Task 7; xfail count drops from 4 to 0.

- [ ] **Step 8: Commit**

```bash
git add templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): bundle CCE-73 stdout echo + dogfood id co-edit (closes parity)

Print partial-run reasons step added to BOTH templates/workflow-run.yml
AND .github/workflows/docs-agent-nightly.yml per the CO-EDIT locked
decision (spec §3). `if: always()` ensures it runs on failed/partial runs;
`// empty` null-safe; `|| true` tolerates malformed state.json.

CC1 dogfood co-edit (post-validation): adds `name: Checkout host repo` +
`id: checkout-host` to the existing dogfood checkout step so its signature
becomes `uses:actions/checkout@v5#checkout-host`, matching the template's
checkout-host step. Without this, test_01 step-signature parity would
flag the dogfood step as missing-in-template.

Lifts ALL remaining xfails on the parity test:
- test_01 step-signature parity (full step list now compared)
- test_02 with-key contract (App-token + upload-artifact + checkout)
- test_03 substring asserts (now includes partial_reasons)
- test_06 stale + redundant allowlist guards (full set asserted)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Migration runbook `docs/runbooks/cce80-host-migration.md`

**Files:**

- Create: `docs/runbooks/cce80-host-migration.md`

**Why:** Spec §8 — the 3 known hosts (ADIS, CCSA, data-importer) need an explicit, verification-rich runbook. Including ADIS-69 mkdocs carve-out.

- [ ] **Step 1: Create the runbook** (use Write tool — CI7 fix: clean Write payload)

Run:

```bash
mkdir -p docs/runbooks
```

Then use the Write tool with file path `docs/runbooks/cce80-host-migration.md` and the following content. Write the content verbatim — do NOT add any outer fence or language hint; the content below is the literal file contents:

````markdown
# CCE-80 Host Migration Runbook

Run this for each host repo currently onboarded to engineering-docs-agent
(ADIS, CCSA, data-importer) after CCE-80 merges and the `v0.5.0` tag is cut.

## Pre-merge checklist

- [ ] CCE-80 PR is open, all checks green.
- [ ] Operator has the plugin tree checked out at the CCE-80 feature branch and has run:
  ```bash
  claude plugin add --local /Users/theo/Projects/engineering-docs-agent
  ```
  This makes the setup skill resolve to the feature branch's SKILL.md + scripts.
  After merge, run `claude plugin update engineering-docs-agent` to switch back
  to the main-tracking install.
- [ ] Operator has `gh auth status` confirming authentication to GitHub (V3-I4).

## Post-merge gate

The plugin checkout in `templates/workflow-run.yml` pins `ref: v0.5.0`.
Hosts re-scaffolded BEFORE the tag exists will fail at the plugin-vendoring
checkout step. PR author cuts the tag within 5 minutes of merge:

```bash
gh release create v0.5.0 \
    --target main \
    --title "v0.5.0 — CCE-80 template refresh" \
    --notes "Template absorbs 16 STALE divergences from dogfood nightly. See CCE-80 spec."
gh release view v0.5.0  # verify
```

Do not begin per-host migration until `gh release view v0.5.0` succeeds.

## Per-host: ADIS, CCSA, data-importer (in this order)

For each `<host>` in `{adis, ccsa, data-importer}`:

### 1. Provision new secrets/variables

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo theoju/<host> --body "$OAUTH_TOKEN"
```

Optional (recommended) — register a GitHub App `engineering-docs-agent`:

```bash
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/<host> --body "$CLIENT_ID"
gh secret set DOCS_AGENT_APP_PRIVATE_KEY --repo theoju/<host> --body-file path/to/private-key.pem
```

Optional (enterprise hosts):

```bash
gh variable set DOCS_AGENT_SKIP_OAUTH_ASSERT --repo theoju/<host> --body "true"
```

**Verify:**

```bash
gh secret list --repo theoju/<host>    # CLAUDE_CODE_OAUTH_TOKEN visible
gh variable list --repo theoju/<host>  # vars set
```

### 2. Re-run setup skill on the host

```bash
cd /path/to/host && claude
> /engineering-docs-agent-setup
```

**Verify:**

- `.github/workflows/docs-agent-nightly.yml` exists. If the pre-CCE-80
  `docs-agent-run.yml` is also present, delete it (`git rm` + commit). The
  legacy `docs-agent-verify.yml` is unrelated and stays.
- File contains `client-id:`, OAuth-assert step, forensics step, run-summary
  step, Print-partial-reasons step.
- Cron line: `grep -E '^\s+- cron: "[0-9]+ 7 \* \* \*"' .github/workflows/docs-agent-nightly.yml`
  returns a single line with a minute in `[5, 55]`.

### 3. (ADIS only) Re-apply mkdocs install carve-out

ADIS uses mkdocs (CCE-69 deferred). After re-scaffolding, insert this step
IMMEDIATELY AFTER the "Install runtime dependencies" step:

```yaml
- name: Install mkdocs (ADIS-specific; CCE-69 follow-up will absorb)
  run: python -m pip install mkdocs mkdocs-material
```

Commit on the ADIS repo:

```bash
git commit -m "chore(ADIS-DOCS): CCE-80 carve-out — restore mkdocs install pending CCE-69"
```

**Verify:** `actionlint .github/workflows/docs-agent-nightly.yml` clean.

### 4. Verify with manual dispatch

```bash
gh workflow run docs-agent-nightly.yml --repo theoju/<host> -f reason="post-CCE-80 migration verify"
gh run watch --repo theoju/<host>
```

**Verify:**

- OAuth pre-flight passes (no `sk-ant-api*` complaint).
- App-token step runs (or cleanly skips for hosts without the App).
- Forensics artifact uploads (visible in `gh run view --log`).
- Run-summary renders.
- Print-partial-reasons step runs (empty stdout is fine).

**Rollback on failure:**

1. Restore `ANTHROPIC_API_KEY` secret if it was already deleted.
2. Revert the workflow file:
   ```bash
   git revert <re-scaffold-commit-sha>
   git push
   ```
3. File a follow-up CCE ticket with the failure mode; halt remaining-host migrations.

### 5. Remove legacy secret (after verification)

```bash
gh secret delete ANTHROPIC_API_KEY --repo theoju/<host>
gh secret list --repo theoju/<host>   # verify removal
```

Wait 24 hours; confirm the next scheduled nightly succeeds. Document
completion in CCE-80 Jira comments.

## Post-runbook cleanup

After ALL hosts complete step 5 and confirm nightly success:

- [ ] Operator runs `claude plugin update engineering-docs-agent` to switch
      back to main-tracking install.
- [ ] CCE-80 Jira ticket transitioned to Done.
````

CI7 NOTE for the subagent: the markdown above contains code fences. The OUTER fence in this plan (` ````markdown `) is presentation only — do NOT write that outer fence into the runbook file. The file's actual first line is `# CCE-80 Host Migration Runbook`.

- [ ] **Step 2: Read-back verification**

Run:

```bash
head -3 docs/runbooks/cce80-host-migration.md
```

Expected: first line is `# CCE-80 Host Migration Runbook`. If you see ` ```markdown` or any leading backtick, the outer fence accidentally got written — delete and re-create.

- [ ] **Step 3: Run full suite — no regressions**

```bash
python3 -m pytest --tb=no -q
```

Expected: unchanged pass/xfail counts (the runbook is markdown only — no test impact).

- [ ] **Step 4: Commit**

```bash
git add docs/runbooks/cce80-host-migration.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): host-migration runbook — docs/runbooks/cce80-host-migration.md

Per-host migration steps for ADIS, CCSA, data-importer with explicit
verification commands at each step. Pre-merge plugin-tree clarification
(claude plugin add --local) so operators re-scaffolding before merge use
the feature branch's SKILL.md + scripts. gh auth status pre-flight (V3-I4).

Post-merge gate: PR author cuts v0.5.0 tag within 5 min, verifies via
gh release view; host migration does not proceed until the tag exists.

ADIS-only carve-out for mkdocs install captures the CCE-69 deferral.

Step 4 rollback documents the recovery path if a host's manual dispatch
fails post-re-scaffold.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `docs/site-src/setup-guide.md` — vars/secrets provisioning matrix (NEW — CI9 resolution)

**Files:**

- Modify: `docs/site-src/setup-guide.md` (append a "Provisioning matrix" subsection)

**Why:** Spec §5.3.4 mandates this and the v1 plan flagged it as a gap. The runbook (Task 9) references it implicitly — operators need a canonical reference during host provisioning.

- [ ] **Step 1: Verify the target file exists**

Run:

```bash
ls -la docs/site-src/setup-guide.md
```

Expected: file exists. If not (unlikely), surface to user — Task 10 is optional in that case.

- [ ] **Step 2: Append the provisioning-matrix section** (use Edit tool)

Read the file's end-of-file to find the last line, then use Edit with:

- `old_string`: the file's last 1-2 lines verbatim (capture via `tail -2 docs/site-src/setup-guide.md`)
- `new_string`: same content followed by:

```markdown
## Provisioning matrix (CCE-80)

Variables and secrets required at the host repo for the docs-agent nightly workflow:

| Name                           | Type        | Required                                 | Purpose                                                                                        |
| ------------------------------ | ----------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `CLAUDE_CODE_OAUTH_TOKEN`      | `secrets.*` | ✅                                       | Claude CLI auth in CI (sk-ant-oat\* token from `claude setup-token`)                           |
| `JIRA_API_TOKEN`               | `secrets.*` | If Jira enrichment                       | Atlassian API auth (basic-auth password half)                                                  |
| `JIRA_EMAIL`                   | `vars.*`    | If Jira enrichment                       | Atlassian basic-auth email half (public-coordinate metadata, not a credential)                 |
| `DOCS_AGENT_APP_CLIENT_ID`     | `vars.*`    | Opt-in (host CI on docs-agent PRs)       | GitHub App Client ID (format `Iv1.xxx` or `Iv23li...`, NOT the numeric App ID)                 |
| `DOCS_AGENT_APP_PRIVATE_KEY`   | `secrets.*` | Opt-in (paired with above)               | GitHub App private key, PEM form                                                               |
| `SLACK_WEBHOOK_URL`            | `secrets.*` | Opt-in (Slack notifications)             | Incoming-webhook URL consumed by `agents/notifier.md` when `notifications.slack.enabled: true` |
| `DOCS_AGENT_SKIP_OAUTH_ASSERT` | `vars.*`    | Opt-in (enterprise/Bedrock/Vertex hosts) | Set to `'true'` to skip the sk-ant-oat\* prefix check in the OAuth pre-flight step             |

### When does the App-token step matter?

If `vars.DOCS_AGENT_APP_CLIENT_ID` is unset, the workflow's `app-token` step is skipped via `if:`, and `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` resolves to the default `GITHUB_TOKEN`. GitHub deliberately suppresses `push` and `pull_request` workflow triggers on its own commits/PRs — so **docs-agent PRs will not fire your host's CI** without the App configured. Register the App and set both `DOCS_AGENT_APP_CLIENT_ID` (Variable) + `DOCS_AGENT_APP_PRIVATE_KEY` (Secret) to enable host CI.

### Migrating from earlier plugin versions

Pre-CCE-80 installations used `ANTHROPIC_API_KEY` (Secret) for the runner's CLI auth. CCE-80 migrates to `CLAUDE_CODE_OAUTH_TOKEN`. See `docs/runbooks/cce80-host-migration.md` for the per-host migration steps.
```

PRACTICAL NOTE: capture the exact end-of-file state with `tail -3 docs/site-src/setup-guide.md` before constructing the Edit so old_string is unique.

- [ ] **Step 3: Read-back verification**

Run:

```bash
grep -c "Provisioning matrix" docs/site-src/setup-guide.md
grep -c "CLAUDE_CODE_OAUTH_TOKEN" docs/site-src/setup-guide.md
```

Expected: both ≥ 1.

- [ ] **Step 4: Run full suite — no regressions**

```bash
python3 -m pytest --tb=no -q
```

Expected: unchanged.

- [ ] **Step 5: Commit**

```bash
git add docs/site-src/setup-guide.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): setup-guide.md — vars/secrets provisioning matrix (§5.3.4)

Closes the spec §5.3.4 gap flagged in the v1 plan self-review. Adds:
1. A canonical vars.*/secrets.* table for host onboarding.
2. The App-token-vs-host-CI consequence explained inline.
3. Migration-from-earlier-versions pointer to the new runbook.

The migration runbook (Task 9) references the matrix; this section gives
operators the canonical lookup they need during provisioning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: CONTRIBUTING.md — dogfood↔template parity gate

**Files:**

- Create: `CONTRIBUTING.md`

**Why:** Spec §7 acceptance criterion. The parity test catches drift, but a contributor-facing note prevents the friction of a confused contributor whose dogfood edit fails CI.

- [ ] **Step 1: Create CONTRIBUTING.md** (use Write tool — CI7 fix: clean payload, no outer fences)

Use the Write tool with file path `CONTRIBUTING.md` and the following content. The content starts at `# Contributing to engineering-docs-agent` (first line) — do not prepend any fence:

```markdown
# Contributing to engineering-docs-agent

## Dogfood ↔ Template Parity

This plugin ships `templates/workflow-run.yml` (the generic workflow
installed by the setup skill into arbitrary host repos) AND dogfoods itself
via `.github/workflows/docs-agent-nightly.yml`. Both files are tested for
parity by `tests/templates/test_workflow_run_parity.py`.

Edits to `.github/workflows/docs-agent-nightly.yml` require either:

1. A corresponding update to `templates/workflow-run.yml` (the preferred
   path for any change that should ship to host repos), or
2. An explicit entry added to `_ALLOWLIST` in
   `tests/templates/test_workflow_run_parity.py` with rationale (use this
   only when the divergence is intentionally host-specific or
   template-specific).

The parity test runs in CI. A failing test prints the divergence + the
allowlist key needed to suppress it. Suppressing without rationale is a
review-time block.

## Release tagging

Plugin releases are tagged so `templates/workflow-run.yml` can pin
`actions/checkout@v5 ref: vX.Y.Z` for the plugin-vendoring step. Cut a
release tag immediately after merging any PR that changes the plugin's
public surface (templates, setup skill, runner contracts):

    gh release create vX.Y.Z \
        --target main \
        --title "vX.Y.Z — short description" \
        --notes "Summary of changes."
    gh release view vX.Y.Z

Cut the tag within 5 minutes of merge — hosts re-scaffolding before the
tag exists will fail at the plugin-vendoring checkout step.
```

CI7 NOTE: the `gh release create` example uses 4-space indent (not a code fence) to sidestep nested-fence ambiguity in this plan document.

- [ ] **Step 2: Read-back verification**

Run:

```bash
head -3 CONTRIBUTING.md
```

Expected: first line is `# Contributing to engineering-docs-agent`. No backticks or `markdown` prefix.

- [ ] **Step 3: Run full suite — no regressions**

```bash
python3 -m pytest --tb=no -q
```

Expected: unchanged.

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): CONTRIBUTING.md — dogfood↔template parity gate + release tagging

Documents the rule contributors care about: edits to
.github/workflows/docs-agent-nightly.yml must either be mirrored into
templates/workflow-run.yml or explicitly allowlisted in the parity test.

Adds release-tagging instructions so future plugin PRs follow the
post-merge tag-cut cadence established by CCE-80.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Final verification (no commit)

**Files:** none modified.

**Why:** Spec §7 acceptance criteria checklist. This task is verification-only — its purpose is to confirm green CI before `/ship`.

- [ ] **Step 1: Run full pytest suite**

```bash
python3 -m pytest
```

Expected: `0 failed`, `0 errors`, ≥ 5 xfailed-then-lifted-to-pass tests added by CCE-80 work, summary line matches the qualitative invariant from §Test-total convention.

- [ ] **Step 2: Run actionlint on both edited workflow files**

```bash
actionlint templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml
```

Expected: clean (no output). If actionlint surfaces a finding, fix before `/ship`.

- [ ] **Step 3: Shellcheck the OAuth pre-flight step body** (CI8 fix included in extracted form)

Create `/tmp/oauth-assert.sh` via Write tool with content from Task 6 step 2. Then:

```bash
shellcheck /tmp/oauth-assert.sh
```

Expected: clean.

- [ ] **Step 4: Verify the live cron rewrite end-to-end**

```bash
python3 scripts/scaffold_workflow.py --owner theoju --repo dogfood | head -20
```

Expected: output starts with `# templates/workflow-run.yml — main authoring workflow` and includes the FN header (`# Drop into the host repo at .github/workflows/docs-agent-nightly.yml`); contains a cron line `- cron: "<minute> 7 * * *"` where `<minute>` is in `[5, 55]` AND the spacing is correct (single space between `<minute> 7` and `* * *`).

- [ ] **Step 5: Verify SKILL.md edits via grep**

```bash
grep -c "docs-agent-nightly.yml" skills/engineering-docs-agent-setup/SKILL.md
grep -c "docs-agent-run.yml" skills/engineering-docs-agent-setup/SKILL.md
grep -c "scaffold_workflow.py" skills/engineering-docs-agent-setup/SKILL.md
grep -c "DOCS_AGENT_APP_CLIENT_ID" skills/engineering-docs-agent-setup/SKILL.md
```

Expected: line 1 ≥ 1; line 2 == 0; line 3 ≥ 1; line 4 ≥ 1.

- [ ] **Step 6: Verify parity-test allowlist is non-stale and non-redundant**

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py::test_06_stale_allowlist_entries -v
```

Expected: PASSED.

- [ ] **Step 7: Verify final commit count via stable-ref anchor (CC5 resolution)**

```bash
git log --oneline c450653..HEAD | wc -l
```

Expected: 12 (1 plan v2 amendment + 11 implementation commits). If the count is 13–15, the subagent-driven flow added review-loop fixup commits — that's acceptable; just note the discrepancy.

If the count is < 12, something is missing — investigate before /ship.

- [ ] **Step 8: Surface ship-readiness**

Print to the user (do NOT invoke `/ship` — that's the next stage, driven by the controller):

> **CCE-80 implementation complete. 11 implementation commits on `chore/CCE-80-template-workflow-run-refresh` (`git log c450653..HEAD | wc -l == 12` including the plan v2 amendment).**
>
> - **All 8 parity tests pass.** Full suite: 0 failed, 0 errors.
> - **`actionlint` clean** on both `templates/workflow-run.yml` and `.github/workflows/docs-agent-nightly.yml`.
> - **`shellcheck` clean** on extracted OAuth-assert step.
> - **`scripts/scaffold_workflow.py` CLI verified** — deterministic cron + FN header rendering correctly with CI1 spacing fix.
> - **SKILL.md edits verified** via grep.
>
> Ready for `/ship`. The /ship pipeline will:
>
> 1. Re-run tests (green).
> 2. Code-review the cross-commit set.
> 3. Push + open PR.
> 4. Transition CCE-80 Jira to In Review on PR creation, Done after merge.
>
> **Post-merge action required:** PR author cuts `v0.5.0` tag within 5 minutes via:
>
> ```bash
> gh release create v0.5.0 --target main --title "v0.5.0 — CCE-80 template refresh" --notes "Template absorbs 16 STALE divergences from dogfood nightly. See CCE-80 spec."
> gh release view v0.5.0
> ```
>
> Begin host-migration runbook (`docs/runbooks/cce80-host-migration.md`) only after the tag verifies.

---

## Self-review

### Spec coverage

| Spec section                                          | Plan task                                                                                                                   |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------- |
| §3 D1 — all 16 STALE in one PR                        | Tasks 5–8                                                                                                                   |
| §3 D2 — OAuth-primary, drop ANTHROPIC_API_KEY         | Task 5 (job-env block); migration in Task 9                                                                                 |
| §3 D3 — App-token opt-in with `                       |                                                                                                                             | ` fallback | Task 5 (folded) |
| §3 D4 — keep `pull_request: closed` + self-loop guard | Task 5 (preserved + CI2 workflow_dispatch extension)                                                                        |
| §3 D5 — bundle CCE-73 stdout echo                     | Task 8                                                                                                                      |
| §3 MIG — hard cutover + runbook                       | Task 9                                                                                                                      |
| §3 PIN — v0.5.0 release tag                           | Task 5 (template `ref: v0.5.0`), Task 9 (runbook post-merge cut), Task 11 (CONTRIBUTING.md cadence)                         |
| §3 FN — docs-agent-nightly.yml                        | Tasks 4 (SKILL.md), 5 (template header)                                                                                     |
| §3 SLK — keep SLACK_WEBHOOK_URL                       | Task 5 (job-env block)                                                                                                      |
| §3 CO-EDIT — dogfood in same PR                       | Task 8 (Print partial-run reasons + `id: checkout-host`)                                                                    |
| §3 ADIS-69 — mkdocs carve-out in runbook              | Task 9 step 3                                                                                                               |
| §3 OAUTH-VAR — keep DOCS_AGENT_SKIP_OAUTH_ASSERT      | Task 6                                                                                                                      |
| §4.2 Generic-first                                    | Task 5 (vars/secrets split), Task 2 (deterministic cron), Task 3 (owner/repo discovery)                                     |
| §5.1.0 18-step final template                         | Tasks 5–8 (incrementally)                                                                                                   |
| §5.1.1 Absorption sequence                            | Tasks 5–8 (4-commit sequence after CC2 fold; documented deviation)                                                          |
| §5.1.2 Dogfood co-edit                                | Task 8 step 3 (Print partial-run reasons) + Task 8 step 2 (`id: checkout-host`)                                             |
| §5.1.3 All 16 STALE items                             | Distributed across Tasks 5–8                                                                                                |
| §5.2 TEMPLATE-ONLY items preserved                    | Task 5 (header, pull_request, self-loop, SLACK, App-token opt-out, OAuth opt-out); recorded in `_TEMPLATE_ONLY_DIVERGENCES` |
| §5.3.1 scripts/scaffold_workflow.py                   | Task 2                                                                                                                      |
| §5.3.2 SKILL.md step 6                                | Task 4                                                                                                                      |
| §5.3.3 SKILL.md step 8                                | Task 4                                                                                                                      |
| §5.3.4 setup-guide.md vars/secrets matrix             | **Task 10** (NEW in v2 — closes the v1 gap)                                                                                 |
| §5.3.5 discover_git_origin                            | Task 3                                                                                                                      |
| §5.3.6 pre-merge plugin-tree                          | Task 9 (runbook pre-merge checklist)                                                                                        |
| §5.4 v0.5.0 tag sequence                              | Task 9 post-merge gate                                                                                                      |
| §6.1 8 parity-test functions                          | Tasks 1, 5, 8 (skeleton + progressive lift)                                                                                 |
| §6.2 scaffold_workflow tests                          | Task 2                                                                                                                      |
| §6.3 SKILL.md grep test                               | Task 4                                                                                                                      |
| §7 Acceptance criteria                                | Task 12                                                                                                                     |
| §8 Migration runbook                                  | Task 9                                                                                                                      |
| §9 Risk surface                                       | Documented in spec; no plan action (advisory)                                                                               |

### Placeholder scan

Searched plan for `TBD`, `TODO`, `implement later`, `Add appropriate`, `Similar to Task N`, `add validation`, `handle edge cases`, `Write tests for`. **No violations.** Every step contains either exact code, exact commands, or exact substring/file targets.

### Type consistency

- `deterministic_cron_minute(owner, repo) -> int` — definition (Task 2) + use in tests (Task 2 step 1; reused in Task 5 step 5).
- `discover_git_origin(repo_root) -> dict | None` — definition (Task 3 step 4), used by SKILL.md (Task 4 step 5 via `discovery["git"]`), tested (Task 3 step 1).
- `_ALLOWLIST: dict[str, str]` and `_WITH_KEY_CONTRACT: dict[str, set[str]]` — defined (Task 1 step 4), bodies reference them unchanged in Tasks 5/6/8.
- `_TEMPLATE_ONLY_DIVERGENCES` — new documentation-only constant introduced in Task 1, not enforced by any test; consistency by inspection only.
- Step IDs (`app-token`, `checkout-host`, `checkout-plugin`, `docs-agent`, `assert-oauth`, `git-identity`) — used consistently across template absorption (Tasks 5–8) and parity test (Tasks 1, 5, 8).
- Workflow filename — `docs-agent-nightly.yml` everywhere; `docs-agent-run.yml` removed from SKILL.md (locked by Task 4's `test_skill_does_not_reference_legacy_filename`).

### Validation-finding traceability

| 3-validator finding                         | Resolved at                                                                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CC1 (`_ALLOWLIST` truncation + dogfood id)  | Task 1 step 4 (`_ALLOWLIST` rewritten); Task 8 step 2 (dogfood `id: checkout-host`)                                                                          |
| CC2 (actionlint blocks dangling step ref)   | Task 5 (folded — CCE-39 + App-token in one commit)                                                                                                           |
| CC3 (verbatim Edit blocks)                  | Tasks 3 step 3-5, 4 step 4-6, 6 step 1, 7 step 1-2, 8 step 1-3, 10 step 2 — all use verbatim `old_string`/`new_string`. Tasks 5 and 9 use Write (full-file). |
| CC4 (pytest totals)                         | §Test-total convention (qualitative invariant). Reference matrix at top.                                                                                     |
| CC5 (commit count)                          | Task 12 step 7 (anchored to `c450653..HEAD`); §0 reconciled.                                                                                                 |
| CI1 (cron regex spacing)                    | Task 2 step 3 (regex fix) + Task 2 step 1's `test_rewrite_cron_preserves_spacing_CI1_regression`.                                                            |
| CI2 (workflow_dispatch in if)               | Task 5 step 1 — included with `CI2 (post-validation extension)` comment in YAML.                                                                             |
| CI3 (Run-summary heading)                   | Task 5 step 1 (template uses `## docs-agent-nightly`).                                                                                                       |
| CI4 (non-step ALLOWLIST entries)            | Task 1 step 4 — `_TEMPLATE_ONLY_DIVERGENCES` constant.                                                                                                       |
| CI5 (xfail-lift mechanism explanation)      | Task 5 step 5 — "On the lifting mechanism (CI5 clarification)".                                                                                              |
| CI6 (dead-code assertion)                   | Task 4 step 2 — second clause is now `'host ci' in text.lower()`.                                                                                            |
| CI7 (CONTRIBUTING/runbook fences)           | Task 9/11 use clean Write payload; nested fences avoided; Task 11 uses 4-space indent for `gh release create` example.                                       |
| CI8 (shellcheck extracted body)             | Task 6 step 2 + Task 12 step 3 — extracted script includes `# shellcheck disable=SC2154` + dummy binding.                                                    |
| CI9 (setup-guide.md matrix)                 | Task 10 (new).                                                                                                                                               |
| CI10 (ruamel.yaml importorskip + HARD GATE) | Task 1 step 2 marked HARD GATE; Task 1 step 4 uses `pytest.importorskip("ruamel.yaml")`.                                                                     |
| CI11 (single SKILL.md edit for line 33)     | Task 4 step 4 (single Edit, full-line `old_string`).                                                                                                         |
| CI12 (6c/6b contradiction)                  | Task 4 step 5 — standardized on "6b immediately AFTER existing 6a".                                                                                          |

### Final note

The plan is comprehensive, executable, TDD-disciplined, and matches the spec's commit-sequence model (with the CC2 fold documented as a planned deviation). Execution path: `superpowers:subagent-driven-development` dispatches a fresh subagent per task with two-stage review (spec compliance, then code quality) between each. After Task 12, controller invokes `/ship`.
