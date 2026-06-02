# CCE-80 — Refresh `templates/workflow-run.yml` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb 16 STALE divergences from `.github/workflows/docs-agent-nightly.yml` into `templates/workflow-run.yml`, add deterministic per-host cron randomization at scaffold time, lock parity with a live test, and document the host-migration runbook.

**Architecture:** TDD-first parity test (`tests/templates/test_workflow_run_parity.py`, 8 functions, xfailed-skeleton-first) lifts xfails as each absorption phase lands. Two new stdlib-only helpers (`scripts/scaffold_workflow.py` for cron rewrite, `scripts/setup_discover.discover_git_origin()` for owner/repo) drive the setup-skill changes in `skills/engineering-docs-agent-setup/SKILL.md`. Bundled CCE-73 stdout-echo step is co-edited into the dogfood workflow in the same PR (locked decision CO-EDIT). Plugin pin is `v0.5.0`, cut by PR author within 5 min of merge per spec §5.4.

**Tech Stack:** Python 3.11 stdlib (helpers), ruamel.yaml 0.18+ (parity test parser — preserves YAML 1.2 semantics for the `on:` key, NOT PyYAML), pytest with `xfail` markers, GitHub Actions YAML, bash + jq + actionlint + shellcheck (CI lint).

**Spec:** `docs/superpowers/specs/2026-06-01-cce80-templates-workflow-run-refresh.md` (583 lines; revisions commit `c450653`)
**Branch:** `chore/CCE-80-template-workflow-run-refresh` (2 commits ahead of main: spec `b959da0` + revisions `c450653`)
**Commit trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
**Test runner:** `python3 -m pytest`

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

| Path                                           | Change                                                                      |
| ---------------------------------------------- | --------------------------------------------------------------------------- |
| `templates/workflow-run.yml`                   | Absorb 16 STALE divergences (~145 added lines, ~10 modified)                |
| `.github/workflows/docs-agent-nightly.yml`     | Co-edit: add Print partial-run reasons step (CCE-73 bundle)                 |
| `scripts/setup_discover.py`                    | Add `discover_git_origin()` + integrate into `discover()` under `"git"` key |
| `tests/setup/test_setup_discover.py`           | Add 3 test cases (SSH URL, HTTPS URL, missing-remote None)                  |
| `skills/engineering-docs-agent-setup/SKILL.md` | Step 6: invoke `scaffold_workflow.py`; Step 8: App-token CI warning         |
| `docs/site-src/setup-guide.md`                 | Add vars/secrets provisioning matrix                                        |

**Commit total within PR:** 12 commits (one per task; Task 12 is verification-only).

**Pre-merge dogfooding requirement:** Operators re-scaffolding any host before merge MUST first run `claude plugin add --local /Users/theo/Projects/engineering-docs-agent` so the setup skill resolves to the feature branch's SKILL.md + scripts (per spec §5.3.6). This plan does not implement that — it's an operator-runtime instruction captured in the migration runbook.

---

## Task 1: Bootstrap parity-test infrastructure (xfailed skeleton)

**Files:**

- Create: `requirements-dev.txt`
- Create: `tests/templates/__init__.py`
- Create: `tests/templates/test_workflow_run_parity.py`

**Why first?** The xfailed-skeleton pattern lets every subsequent template-absorption task lift its bucket of xfails. Suite stays green throughout the 5-commit absorption sequence.

- [ ] **Step 1: Create `requirements-dev.txt`**

```bash
cat > requirements-dev.txt <<'EOF'
# Dev-only dependencies — NOT shipped to host repos.
# templates/docs-requirements.txt is the host-facing list; keep this separate.

ruamel.yaml>=0.18  # YAML 1.2 parser for tests/templates/test_workflow_run_parity.py
                   # PyYAML SafeLoader collapses YAML-1.1 `on:` → True; ruamel preserves the key as a string.
EOF
```

- [ ] **Step 2: Install dev deps locally and verify ruamel imports**

Run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -c "import ruamel.yaml; print('ruamel.yaml', ruamel.yaml.__version__)"
```

Expected: prints `ruamel.yaml <version>` where version starts with `0.18.` or higher. No traceback.

- [ ] **Step 3: Create test package marker**

Create empty file:

```bash
mkdir -p tests/templates && : > tests/templates/__init__.py
```

- [ ] **Step 4: Write the skeleton parity test (all 8 functions xfailed)**

Create `tests/templates/test_workflow_run_parity.py`:

```python
"""Parity test for templates/workflow-run.yml ↔ .github/workflows/docs-agent-nightly.yml.

Key grammar (the strings used in _ALLOWLIST and matcher logic):
  uses:<action>@<ver>              — matches step by uses: signature only (no id required)
  uses:<action>@<ver>#<id>         — matches step by uses: AND id: (disambiguates duplicates)
  with.<key>==<value>              — matches a step whose with: key has the given literal value
  env.<NAME>                       — matches a job-env or step-env key
  pull_request.types==[<list>]     — matches an `on.pull_request.types` literal
  if:<expression>                  — matches a step- or job-level if: (substring match)
  run:<prefix>                     — matches a step whose run: scalar starts with the prefix (first line, normalized whitespace)

Tests are numbered (test_01_… through test_08_…) so failure output is predictable.

XFAIL DISCIPLINE: tests are xfailed until their template-absorption task lands. Each
task in the implementation plan lifts the xfail markers it satisfies, leaving the
suite green throughout the absorption sequence (CCE-80 plan tasks 5–9).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import ruamel.yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "workflow-run.yml"
DOGFOOD = ROOT / ".github" / "workflows" / "docs-agent-nightly.yml"


_ALLOWLIST: dict[str, str] = {
    # Template-only divergences (D4 — pull_request.closed self-loop affordance):
    "uses:actions/checkout@v5#checkout-plugin":
        "Template-only: plugin vendoring step (id: checkout-plugin discriminates from host checkout)",
    "pull_request.types==['closed']":
        "Template-only trigger: real-time docs update on merge for hosts (D4)",
    "if:github.event_name == 'schedule'":
        "Template-only job-level guard: paired with pull_request.closed trigger (D4 self-loop)",
    "with.path==.docs-agent-plugin":
        "Template-only: vendored-plugin checkout target (paired with checkout-plugin step)",
    "run:python .docs-agent-plugin/scripts/orchestrator_runner.py":
        "HOST-SPECIFIC: vendored entrypoint (divergence #20; template uses .docs-agent-plugin path)",
    "env.SLACK_WEBHOOK_URL":
        "Template-only opt-in: consumed by agents/notifier.md when notifications.slack.enabled: true",
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
# 8 numbered assertion functions
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="CCE-80 plan task 9 lifts: full step-signature parity awaits CCE-73 stdout echo bundle")
def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 9")


@pytest.mark.xfail(reason="CCE-80 plan task 9 lifts: with-key contract on all absorbed actions")
def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 9")


@pytest.mark.xfail(reason="CCE-80 plan task 9 lifts: substring asserts include partial_reasons (CCE-73 bundle)")
def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 9")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: literal-equals shape contract on CCE-39 baseline")
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(reason="CCE-80 plan task 6 lifts: App-token conditional shape (template-only properties)")
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 6")


@pytest.mark.xfail(reason="CCE-80 plan task 9 lifts: allowlist orphan/redundant guards run when all steps present")
def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 9")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: run-summary `if: always()` (CCE-39 baseline)")
def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(reason="CCE-80 plan task 5 lifts: on-key regression guard (catches PyYAML escape route)")
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
```

- [ ] **Step 5: Run the parity test — expect 8 xfailed, 0 failed**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected output ends with: `8 xfailed in <…>s`. No failures.

- [ ] **Step 6: Run the full suite — expect green (baseline + 8 xfail)**

Run:

```bash
python3 -m pytest
```

Expected: 0 failed. Baseline today is `726 passed + 3 skipped`; new total: `726 passed + 3 skipped + 8 xfailed`.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tests/templates/__init__.py tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
test(CCE-80): xfailed parity-test skeleton + ruamel.yaml dev dep

Sets up the live-dogfood parity test (templates/workflow-run.yml ↔
.github/workflows/docs-agent-nightly.yml) with all 8 numbered assertion
functions xfailed. Each subsequent CCE-80 task lifts its bucket of xfails
so the suite stays green through the 5-commit absorption sequence.

Uses ruamel.yaml (not PyYAML) to preserve YAML-1.2 semantics for the
top-level on: key. _ALLOWLIST + _WITH_KEY_CONTRACT named constants per
spec §6.1. requirements-dev.txt keeps dev deps out of the host-facing
templates/docs-requirements.txt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `scripts/scaffold_workflow.py` helper (TDD)

**Files:**

- Create: `scripts/scaffold_workflow.py`
- Create: `tests/setup/test_scaffold_workflow.py`

**Why next?** SKILL.md edits in Task 4 invoke this helper. The helper must exist + be tested first.

- [ ] **Step 1: Write failing test `test_deterministic_cron_minute_stable`**

Create `tests/setup/test_scaffold_workflow.py`:

```python
"""Tests for scripts/scaffold_workflow.py — cron-randomization helper.

Determinism + bounds + anchor sanity + real-template round-trip + CLI smoke.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import ruamel.yaml

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "scaffold_workflow.py"
TEMPLATE = ROOT / "templates" / "workflow-run.yml"

sys.path.insert(0, str(ROOT / "scripts"))


def test_deterministic_cron_minute_stable() -> None:
    """Same input → same output. No drift across calls."""
    from scaffold_workflow import deterministic_cron_minute

    assert deterministic_cron_minute("theoju", "adis") == deterministic_cron_minute("theoju", "adis")
    assert deterministic_cron_minute("theoju", "ccsa") == deterministic_cron_minute("theoju", "ccsa")
```

- [ ] **Step 2: Run test — expect FAIL (ModuleNotFoundError)**

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py::test_deterministic_cron_minute_stable -v
```

Expected: FAILED with `ModuleNotFoundError: No module named 'scaffold_workflow'`.

- [ ] **Step 3: Implement minimal scaffold_workflow.py**

Create `scripts/scaffold_workflow.py`:

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

# Loosened anchor (per spec §5.3.1 / C5): tolerates trailing whitespace or
# inline comment on the cron line. The rewrite preserves whatever tail was
# present.
_CRON_PATTERN = re.compile(r'^(\s+- cron: ")7 7 (\* \* \*")(.*)$', re.MULTILINE)


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

- [ ] **Step 4: Run test — expect PASS**

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py::test_deterministic_cron_minute_stable -v
```

Expected: PASSED.

- [ ] **Step 5: Add tests 2–6 (distribution, bounds, anchor, round-trip, CLI smoke)**

Append to `tests/setup/test_scaffold_workflow.py`:

```python
def test_known_fixture_minutes() -> None:
    """Lock specific (owner, repo) → minute mappings so a drift in the algorithm
    surfaces immediately. Pre-computed via:
        python3 -c "import hashlib; print(int(hashlib.sha256(b'theoju/adis').hexdigest(), 16) % 51 + 5)"
    """
    from scaffold_workflow import deterministic_cron_minute

    # PLAN-NOTE: regenerate these integers via the snippet above if the
    # algorithm ever changes intentionally. A spurious diff here means
    # someone modified the hashing without updating fixtures.
    assert deterministic_cron_minute("theoju", "adis") == _expected_minute("theoju", "adis")
    assert deterministic_cron_minute("theoju", "ccsa") == _expected_minute("theoju", "ccsa")
    assert deterministic_cron_minute("theoju", "data-importer") == _expected_minute("theoju", "data-importer")
    assert deterministic_cron_minute("theoju", "dogfood") == _expected_minute("theoju", "dogfood")


def _expected_minute(owner: str, repo: str) -> int:
    # Mirrors the production algorithm so the fixture isn't tautological.
    # If both this and the production helper drift in lock-step, the
    # bounds + distribution + round-trip tests still catch it.
    import hashlib
    return int(hashlib.sha256(f"{owner}/{repo}".encode()).hexdigest(), 16) % 51 + 5


def test_cron_minute_bounds() -> None:
    """Sweep a handful of plausible host names; every minute must land in [5, 55]."""
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


def test_rewrite_cron_round_trip_on_real_template() -> None:
    """Real template — output differs from input by exactly the cron line,
    parses cleanly under ruamel.yaml, and round-trip is loss-free elsewhere.

    Skipped only if templates/workflow-run.yml has not been refreshed yet
    (cron is still '0 7 * * *' from the pre-CCE-80 template). Lifts at task 5.
    """
    from scaffold_workflow import rewrite_cron

    raw = TEMPLATE.read_text()
    if '- cron: "7 7 * * *"' not in raw:
        pytest.xfail("CCE-80 plan task 5 sets cron to '7 7 * * *' in the template")

    rendered = rewrite_cron(raw, "theoju", "dogfood")
    # Bytewise-different only on the cron line.
    raw_lines = raw.splitlines()
    rendered_lines = rendered.splitlines()
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(raw_lines, rendered_lines)) if a != b]
    assert len(diffs) == 1, f"expected exactly 1 differing line; got {diffs}"
    idx, before, after = diffs[0]
    assert 'cron: "7 7 * * *"' in before
    assert 'cron: "' in after and '* * *"' in after

    # Output parses cleanly under ruamel.yaml.
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.load(rendered)

    # actionlint clean (skip if binary not on PATH).
    if shutil.which("actionlint") is None:
        pytest.skip("actionlint not on PATH")
    proc = subprocess.run(
        ["actionlint", "-"],
        input=rendered,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"actionlint failed:\n{proc.stdout}{proc.stderr}"


def test_cli_smoke() -> None:
    """Invoke the helper as a script. Output is rendered to stdout and contains
    the expected header (FN — docs-agent-nightly.yml) plus the per-host cron line.
    """
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

- [ ] **Step 6: Run all 6 tests**

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py -v
```

Expected: 4 passed (`test_deterministic_cron_minute_stable`, `test_known_fixture_minutes`, `test_cron_minute_bounds`, `test_rewrite_cron_anchor_zero_matches_raises`, `test_rewrite_cron_anchor_two_matches_raises`); 2 xfailed (`test_rewrite_cron_round_trip_on_real_template`, `test_cli_smoke`) — those await Task 5's template refresh.

- [ ] **Step 7: Run full suite — no regressions**

Run:

```bash
python3 -m pytest
```

Expected: `726 passed + 3 skipped + 10 xfailed` (8 from Task 1 + 2 from Task 2).

- [ ] **Step 8: Commit**

```bash
git add scripts/scaffold_workflow.py tests/setup/test_scaffold_workflow.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): scripts/scaffold_workflow.py — deterministic per-host cron rewrite

Stdlib-only helper invoked by the setup skill at SKILL.md step 6. SHA-256
of `<owner>/<repo>` mod 51 + 5 yields a stable minute in [5, 55] — same
input always produces the same output (no diff churn on re-scaffold), and
100 hosts won't pile up at :07 UTC.

Anchored regex on `^\s+- cron: "7 7 \* \* \*"$` raises RuntimeError on
0-or-many matches (structural-drift guard). Tolerates trailing comment per
spec §5.3.1 C5.

Tests cover: determinism, fixture lock-in, bounds [5, 55], anchor sanity
(zero/two-match raise), real-template round-trip (xfail until task 5 lands
the refresh), CLI smoke (xfail likewise).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `scripts/setup_discover.discover_git_origin()` (TDD)

**Files:**

- Modify: `scripts/setup_discover.py` (add `discover_git_origin()` + integrate into `discover()` under `"git"` key)
- Modify: `tests/setup/test_setup_discover.py` (add 3 cases)

**Why:** SKILL.md step 6 needs `discovery["git"]["owner"]` and `discovery["git"]["repo"]` to invoke `scaffold_workflow.py`. The current `setup_discover.py` does not emit these.

- [ ] **Step 1: Write 3 failing tests**

Append to `tests/setup/test_setup_discover.py`:

```python
def test_discover_git_origin_https_url(tmp_path, monkeypatch) -> None:
    """HTTPS clone URL → {owner, repo} extracted."""
    from setup_discover import discover_git_origin

    # Fake `git remote get-url origin` by intercepting subprocess.run.
    import subprocess
    calls: list[list[str]] = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0,
            stdout="https://github.com/theoju/engineering-docs-agent.git\n",
            stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = discover_git_origin(tmp_path)
    assert result == {"owner": "theoju", "repo": "engineering-docs-agent"}


def test_discover_git_origin_ssh_url(tmp_path, monkeypatch) -> None:
    """SSH clone URL → {owner, repo} extracted."""
    from setup_discover import discover_git_origin

    import subprocess
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0,
            stdout="git@github.com:theoju/adis.git\n",
            stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = discover_git_origin(tmp_path)
    assert result == {"owner": "theoju", "repo": "adis"}


def test_discover_git_origin_no_remote(tmp_path, monkeypatch) -> None:
    """No `origin` remote → None (caller falls back to AskUserQuestion)."""
    from setup_discover import discover_git_origin

    import subprocess
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=128,
            stdout="",
            stderr="error: No such remote 'origin'\n",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert discover_git_origin(tmp_path) is None
```

- [ ] **Step 2: Run tests — expect 3 FAILED (no function)**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py::test_discover_git_origin_https_url tests/setup/test_setup_discover.py::test_discover_git_origin_ssh_url tests/setup/test_setup_discover.py::test_discover_git_origin_no_remote -v
```

Expected: 3 FAILED with `ImportError: cannot import name 'discover_git_origin'`.

- [ ] **Step 3: Implement `discover_git_origin`**

Edit `scripts/setup_discover.py`. At the top, the existing imports are:

```python
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
```

Add `import re, subprocess` to that import line (or as separate imports — match existing style).

Then insert this function **before** `def discover(cwd: Path) -> dict:` (around line 203):

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
```

- [ ] **Step 4: Wire `discover_git_origin` into `discover()`**

Inside `def discover(cwd: Path) -> dict:`, add `"git": discover_git_origin(cwd)` to the `out` dict literal. The current `out:` block (around line 221) becomes:

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

- [ ] **Step 5: Run the 3 new tests — expect PASS**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py::test_discover_git_origin_https_url tests/setup/test_setup_discover.py::test_discover_git_origin_ssh_url tests/setup/test_setup_discover.py::test_discover_git_origin_no_remote -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Run full setup_discover suite — no regressions**

Run:

```bash
python3 -m pytest tests/setup/test_setup_discover.py -v
```

Expected: all existing setup_discover tests pass + the 3 new tests pass. If any existing test that touches `discover()['git']` was previously missing — it should pass now (the new key is additive).

- [ ] **Step 7: Run full suite — no regressions**

Run:

```bash
python3 -m pytest
```

Expected: `729 passed + 3 skipped + 10 xfailed` (3 new tests pass; previous totals unchanged otherwise).

- [ ] **Step 8: Commit**

```bash
git add scripts/setup_discover.py tests/setup/test_setup_discover.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): setup_discover.discover_git_origin() — emit {owner, repo}

Parses `git remote get-url origin` to feed SKILL.md step 6's invocation of
scripts/scaffold_workflow.py. Handles SSH and HTTPS URLs; returns None when
no origin remote exists so the caller can fall back to AskUserQuestion.

Integrated into discover() under the new "git" key — additive to existing
discovery shape. Three new tests cover SSH, HTTPS, and missing-remote paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SKILL.md edits + `tests/skills/test_setup_skill_md.py` (TDD grep)

**Files:**

- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_setup_skill_md.py`
- Modify: `skills/engineering-docs-agent-setup/SKILL.md` (step 6 sub-bullet rewrite, step 8 conditional warning)

**Why:** Spec §5.3.2 / §5.3.3. The grep test locks the FN rename + the helper invocation + the App-token warning.

- [ ] **Step 1: Create test package marker**

```bash
mkdir -p tests/skills && : > tests/skills/__init__.py
```

- [ ] **Step 2: Write 4 failing grep tests**

Create `tests/skills/test_setup_skill_md.py`:

```python
"""Grep-style integration test for SKILL.md edits (CCE-80 spec §6.3).

Locks the FN rename, the scaffold_workflow.py invocation, and the App-token
warning. Each assertion is a substring check on the SKILL.md file content.
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
    """Step 8 must surface the App-token-for-host-CI consequence."""
    text = _content()
    assert "DOCS_AGENT_APP_CLIENT_ID" in text
    assert "host CI" in text or "host CI" in text.lower() or "host_ci" in text  # tolerant
```

- [ ] **Step 3: Run the 4 tests — expect at least 2 FAILED**

Run:

```bash
python3 -m pytest tests/skills/test_setup_skill_md.py -v
```

Expected: `test_skill_does_not_reference_legacy_filename` FAILS (current SKILL.md line 33 contains `docs-agent-run.yml`); `test_skill_references_docs_agent_nightly_filename` FAILS; `test_skill_invokes_scaffold_workflow_helper` FAILS; `test_skill_step8_warns_about_app_token_for_ci` FAILS.

- [ ] **Step 4: Edit SKILL.md step 6 (rewrite the workflow-write sub-bullet)**

In `skills/engineering-docs-agent-setup/SKILL.md`, line 33 currently reads:

> 6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-run.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`. (CCE-57) The shipped workflow checks out ...

Replace the substring `.github/workflows/docs-agent-run.yml` with `.github/workflows/docs-agent-nightly.yml`, AND replace the `(CCE-57)` reference with `(CCE-57, CCE-80)`, AND append a new sub-bullet (6c) BEFORE the existing 6a sub-bullet (which currently follows on line 34).

Use Edit tool with old_string targeting the exact sub-bullet and new_string with the rewrite. The final SKILL.md step 6 should read:

````
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-nightly.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`. (CCE-57, CCE-80) The shipped workflow checks out `theoju/engineering-docs-agent` into `.docs-agent-plugin/` and runs the orchestrator from that path — do not delete the checkout step. After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.
   6a. (existing pages-publishable sub-bullet unchanged)
   6b. **Render the workflow file with a deterministic per-host cron minute** (CCE-80) — instead of writing the raw template, run:
       ```bash
       python <plugin_root>/scripts/scaffold_workflow.py \
           --owner "$OWNER" --repo "$REPO" \
           --out .github/workflows/docs-agent-nightly.yml
       ```
       where `OWNER`/`REPO` come from `discovery["git"]["owner"]` and `discovery["git"]["repo"]` (from `setup_discover.discover_git_origin()`). If `discovery["git"]` is `None`, fall back to `AskUserQuestion("What is the GitHub owner/repo for this host?", header="Repo", ...)`. The helper is deterministic — re-scaffolding the same host always produces the same cron minute, so no operator-visible diff churn.
````

Apply this as a single `Edit` operation matching the original line 33 verbatim and replacing with the expanded text. Preserve the existing 6a sub-bullet exactly (the pages-publishable section).

- [ ] **Step 5: Edit SKILL.md step 8 (append App-token warning)**

After the existing step 8 line (`8. Print a final "next steps" summary.`), append:

```
   Conditional warning (CCE-80): if `vars.DOCS_AGENT_APP_CLIENT_ID` is unset on the host, append this to the "next steps" output:
   > **Host CI will not run on docs-agent PRs** unless you register a GitHub App. Without `vars.DOCS_AGENT_APP_CLIENT_ID`, the workflow falls back to `secrets.GITHUB_TOKEN`, which GitHub deliberately prevents from triggering `push`/`pull_request` workflows on its own commits. To enable host CI on docs-agent PRs:
   >
   > 1. Register a GitHub App named `engineering-docs-agent` with `Contents: write`, `Pull requests: write`, `Issues: read` permissions.
   > 2. Install it on this repository.
   > 3. Set `vars.DOCS_AGENT_APP_CLIENT_ID` (the App's Client ID) and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` (PEM-form private key).
   > 4. Re-scaffold via this skill (no-op for cron; activates the App-token step).
```

- [ ] **Step 6: Run the 4 grep tests — expect PASS**

Run:

```bash
python3 -m pytest tests/skills/test_setup_skill_md.py -v
```

Expected: 4 PASSED.

- [ ] **Step 7: Run full suite — no regressions**

Run:

```bash
python3 -m pytest
```

Expected: `733 passed + 3 skipped + 10 xfailed` (4 new grep tests pass; previous totals unchanged otherwise).

- [ ] **Step 8: Commit**

```bash
git add tests/skills/__init__.py tests/skills/test_setup_skill_md.py skills/engineering-docs-agent-setup/SKILL.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): SKILL.md — invoke scaffold_workflow.py + App-token CI warning

Step 6 rewrites the workflow-write sub-bullet to invoke
scripts/scaffold_workflow.py with --owner/--repo from
discovery["git"], producing a deterministic per-host cron minute.
Filename updates from docs-agent-run.yml to docs-agent-nightly.yml
(matches dogfood + all 3 known hosts).

Step 8 appends a conditional warning surfaced when vars.DOCS_AGENT_APP_CLIENT_ID
is unset, explaining the host-CI suppression consequence and the App
registration flow.

tests/skills/test_setup_skill_md.py grep-locks all 4 substrings so future
edits can't silently regress.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Template absorb — CCE-39 baseline (commit 1/5)

**Files:**

- Modify: `templates/workflow-run.yml` (absorb steps 1–7, 11–12, 14, 17 per spec §5.1.0)
- Modify: `tests/templates/test_workflow_run_parity.py` (lift xfails on test_04, test_07, test_08; implement bodies)
- Modify: `tests/setup/test_scaffold_workflow.py` (lift xfails on round-trip + CLI smoke — template now has the `7 7` cron + FN header)

**What this absorbs:** triggers (`schedule` off-minute, `workflow_dispatch.inputs.reason`), permissions block (`issues: read`), concurrency rename + `cancel-in-progress: false`, `timeout-minutes: 60`, job-env scaffolding (CLAUDE*CODE_OAUTH_TOKEN, JIRA*\*), install steps (pip upgrade form, `which claude` verify), git identity step, run-summary step skeleton (without CCE-73 stdout echo).

This task does NOT absorb: App-token step (Task 6), OAuth four-arm assert (Task 7), forensics (Task 8), CCE-73 stdout echo (Task 9).

- [ ] **Step 1: Edit `templates/workflow-run.yml` — header + triggers + permissions + concurrency**

Replace the current header (`templates/workflow-run.yml:1-19`) with:

```yaml
# templates/workflow-run.yml — main authoring workflow
# Drop into the host repo at .github/workflows/docs-agent-nightly.yml (CCE-80 FN).
# This file is rendered through scripts/scaffold_workflow.py at scaffold time,
# which rewrites the cron minute to a deterministic per-host value in [5, 55]
# so 100 onboarded hosts don't all fire at :07 UTC. See SKILL.md step 6.
name: docs-agent run

on:
  schedule:
    # 07:07 UTC off-minute default; setup-skill rewrites per-host so 100 hosts don't pileup at :07
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
```

- [ ] **Step 2: Edit `templates/workflow-run.yml` — job header + job-env block**

Replace the existing `jobs:` block opener (current `templates/workflow-run.yml:20-23`) with:

```yaml
jobs:
  run:
    # TEMPLATE-ONLY (D4 self-loop guard): paired with `pull_request.closed`.
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
```

- [ ] **Step 3: Replace the step list — checkout-host + checkout-plugin + Python + install + identity + run-summary**

Replace `templates/workflow-run.yml:24-52` (the entire current steps block) with the CCE-39 baseline step list (Task 6 will insert the App-token step at the top; Task 7 the OAuth assert; Task 8 the forensics step; Task 9 the stdout-echo step):

````yaml
- name: Checkout host repo
  id: checkout-host
  uses: actions/checkout@v5
  with:
    fetch-depth: 0 # full history so state.json window math sees all merges
    # CCE-45: checkout configures git's credential helper from this
    # token, so the subsequent `git push` from the runner uses the
    # App token rather than the default GITHUB_TOKEN. The `||` resolves
    # to GITHUB_TOKEN when the App-token step (CCE-80 task 6) is skipped.
    # NOTE: as of CCE-80 plan task 5 the App-token step doesn't exist yet;
    # `steps.app-token.outputs.token` is empty → `||` resolves to the
    # fallback. Task 6 lands the step + actually-meaningful token.
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
    # (task 6 lands the App-token step). The `||` fallback to
    # GITHUB_TOKEN handles the opt-out case. Lives at step-env (not
    # job-env) because GitHub's runtime validator rejects `steps.*`
    # references at job-env scope.
    GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}
  run: |
    python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .

- name: Run summary
  if: always()
  # workflow_dispatch.inputs.reason is user-controlled; pass it via env: and
  # dereference as a shell var rather than interpolating into the script body.
  env:
    TRIGGER: ${{ github.event_name }}
    REASON: ${{ inputs.reason }}
  run: |
    {
      echo "## docs-agent"
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

- [ ] **Step 4: Lint the new template with actionlint**

Run:

```bash
actionlint templates/workflow-run.yml
```

Expected: clean (no output). If actionlint flags missing `app-token` step output reference — that's expected at this stage; task 6 lands the step. Note any errors and verify they all relate to the future App-token wiring (which is intentional placeholder state).

If actionlint is not on PATH, skip this step with a note; CI will catch it.

- [ ] **Step 5: Lift parity-test xfails on test_04, test_07, test_08**

Edit `tests/templates/test_workflow_run_parity.py`:

Replace the body of `test_04_literal_equals_shape_contract` (remove the `@pytest.mark.xfail` decorator):

```python
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    """Locked literal values shared by both files (CCE-39 baseline)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        # Concurrency
        conc = doc["concurrency"]
        assert conc["group"] == "docs-agent-nightly", f"{label}: concurrency.group != docs-agent-nightly"
        assert conc["cancel-in-progress"] is False, f"{label}: cancel-in-progress != false"
        # Timeout (lives under jobs.<job-id>.timeout-minutes; job-id differs)
        jobs = list(doc["jobs"].values())
        assert len(jobs) == 1, f"{label}: expected exactly 1 job"
        assert jobs[0]["timeout-minutes"] == 60, f"{label}: timeout-minutes != 60"
        # Permissions
        perms = doc["permissions"]
        for k in ("contents", "pull-requests", "issues"):
            assert k in perms, f"{label}: missing permissions.{k}"
        # Job-env keys
        env = jobs[0]["env"]
        for k in ("CLAUDE_CODE_OAUTH_TOKEN", "JIRA_API_TOKEN", "JIRA_EMAIL"):
            assert k in env, f"{label}: missing job-env {k}"
        # Triggers
        triggers = doc["on"]
        assert "schedule" in triggers, f"{label}: missing schedule trigger"
        assert "workflow_dispatch" in triggers, f"{label}: missing workflow_dispatch trigger"
```

Replace the body of `test_07_run_summary_if_always` (remove `@pytest.mark.xfail`):

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

Replace the body of `test_08_on_key_regression` (remove `@pytest.mark.xfail`):

```python
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    """Top-level `on:` key must parse as a string-keyed mapping, NOT the YAML-1.1
    boolean True (the PyYAML SafeLoader escape route). Regression guard.
    """
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        on_val = doc["on"]
        assert isinstance(on_val, dict), f"{label}: top-level `on:` is {type(on_val).__name__}, expected dict"
        # If we accidentally use PyYAML, this becomes `True` and the dict access above fails.
```

- [ ] **Step 6: Run the parity test — expect 3 newly PASSED + 5 still XFAILED**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: `test_04`, `test_07`, `test_08` PASSED; `test_01`, `test_02`, `test_03`, `test_05`, `test_06` still XFAILED. Total: `3 passed, 5 xfailed`.

- [ ] **Step 7: Run scaffold_workflow round-trip + CLI smoke — should lift xfails now**

The template now contains `cron: "7 7 * * *"` + the new FN header. `test_rewrite_cron_round_trip_on_real_template` and `test_cli_smoke` should pass.

Run:

```bash
python3 -m pytest tests/setup/test_scaffold_workflow.py -v
```

Expected: 6 PASSED, 0 xfailed.

Note: this works because both xfail-guards in those tests use plain `pytest.xfail(...)` calls inside the function body — they short-circuit when the precondition is unmet but otherwise run the assertions normally. No code edit needed in `test_scaffold_workflow.py`.

- [ ] **Step 8: Run full suite — green**

Run:

```bash
python3 -m pytest
```

Expected: `738 passed + 3 skipped + 5 xfailed`. Net: 3 xfails lifted on parity test, 2 xfails lifted on scaffold_workflow test.

- [ ] **Step 9: Commit**

```bash
git add templates/workflow-run.yml tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-39 baseline (steps 1–7, 11–12, 14, 17)

Triggers (schedule off-minute + workflow_dispatch.reason +
pull_request.closed TEMPLATE-ONLY), permissions (issues: read added),
concurrency rename (docs-agent-nightly + cancel-in-progress: false),
timeout-minutes: 60, job-env block (CLAUDE_CODE_OAUTH_TOKEN replaces
ANTHROPIC_API_KEY; JIRA_API_TOKEN + JIRA_EMAIL added; SLACK_WEBHOOK_URL
TEMPLATE-ONLY preserved), install steps (pip upgrade form + which claude
verify), git identity step, run-summary step skeleton.

Plugin checkout pinned to v0.5.0 — PR author cuts tag <5 min post-merge
per spec §5.4. Filename rename to docs-agent-nightly.yml in the header
comment closes FN locked-decision.

Lifts xfails on test_04 (literal-equals shape), test_07 (run-summary
if always()), test_08 (PyYAML on-key regression guard). scaffold_workflow
round-trip + CLI smoke also auto-pass now that the template has the
`7 7` cron + FN header.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Template absorb — App-token plumbing (CCE-45 + CCE-66) (commit 2/5)

**Files:**

- Modify: `templates/workflow-run.yml` (insert App-token step as first step under `steps:`)
- Modify: `tests/templates/test_workflow_run_parity.py` (lift xfail on test_05, implement body)

**What this absorbs:** Step 8 of §5.1.0 (App-token step with `if:` gate + `client-id` per CCE-66 v3 deprecation). Checkout-host step's `with.token` is already wired to the `||` fallback in Task 5; this task makes that wiring meaningful.

- [ ] **Step 1: Insert the App-token step**

In `templates/workflow-run.yml`, insert this block as the FIRST step under `steps:` (immediately after the `steps:` line, before the existing "Checkout host repo" step):

```yaml
# Without DOCS_AGENT_APP_CLIENT_ID set, this step is skipped and the workflow
# falls back to secrets.GITHUB_TOKEN. CONSEQUENCE: docs-agent PRs will NOT
# trigger your host CI (push/pull_request workflows). To enable host CI on
# docs-agent PRs, register a GitHub App named engineering-docs-agent and set
# vars.DOCS_AGENT_APP_CLIENT_ID + secrets.DOCS_AGENT_APP_PRIVATE_KEY.
- name: Generate GitHub App installation token
  id: app-token
  if: vars.DOCS_AGENT_APP_CLIENT_ID != ''
  # CCE-54: v3 is the first major on Node 24.
  # CCE-66: v3 deprecates `app-id` in favor of `client-id` (a different
  # App field — the OAuth Client ID, format Iv1.xxx or Iv23li…, NOT the
  # numeric App ID). Stored as a repo Variable because Client IDs are
  # not credentials.
  uses: actions/create-github-app-token@v3
  with:
    client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
    private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

- [ ] **Step 2: Lint with actionlint**

Run:

```bash
actionlint templates/workflow-run.yml
```

Expected: clean. Any remaining errors should ONLY relate to the not-yet-added OAuth assert step (Task 7), forensics step (Task 8), or CCE-73 stdout echo step (Task 9). If actionlint flags the App-token block itself, fix before continuing.

- [ ] **Step 3: Lift parity-test xfail on test_05**

In `tests/templates/test_workflow_run_parity.py`, replace `test_05_app_token_conditional_shape` (remove `@pytest.mark.xfail`):

```python
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    """Template-only property tests on the App-token wiring.

    The TEMPLATE has the `if:` opt-out gate (hosts may skip the App-token step);
    the DOGFOOD does not (we own this repo's auth). The dogfood divergence is
    intentional — the parity test allowlist permits it.
    """
    template_jobs = list(template_doc["jobs"].values())
    template_steps = template_jobs[0]["steps"]

    app_token = next(
        (s for s in template_steps if s.get("id") == "app-token"), None
    )
    assert app_token is not None, "template missing app-token step"
    assert "vars.DOCS_AGENT_APP_CLIENT_ID != ''" in str(app_token.get("if", "")), \
        "template app-token step missing opt-out `if:`"
    assert app_token.get("uses") == "actions/create-github-app-token@v3"
    assert "client-id" in app_token["with"], "app-token must use `client-id` (not deprecated `app-id`)"

    # Checkout-host token wiring — AST-normalized form (strip whitespace).
    checkout = next(
        (s for s in template_steps if s.get("id") == "checkout-host"), None
    )
    assert checkout is not None, "template missing checkout-host step"
    token_expr = "".join(str(checkout["with"]["token"]).split())  # normalize whitespace
    expected = "${{steps.app-token.outputs.token||secrets.GITHUB_TOKEN}}"
    assert token_expr == expected, \
        f"checkout-host token wiring mismatch: got {token_expr}, expected {expected}"

    # Authoring step step-env GH_TOKEN — same expression.
    authoring = next(
        (s for s in template_steps if s.get("id") == "docs-agent"), None
    )
    assert authoring is not None, "template missing docs-agent authoring step"
    gh_token_expr = "".join(str(authoring["env"]["GH_TOKEN"]).split())
    assert gh_token_expr == expected, \
        f"authoring step GH_TOKEN mismatch: got {gh_token_expr}, expected {expected}"
```

- [ ] **Step 4: Run parity test — expect 4 PASSED + 4 still XFAILED**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: `test_04`, `test_05`, `test_07`, `test_08` PASSED; `test_01`, `test_02`, `test_03`, `test_06` still XFAILED. Total: `4 passed, 4 xfailed`.

- [ ] **Step 5: Run full suite — green**

Run:

```bash
python3 -m pytest
```

Expected: `739 passed + 3 skipped + 4 xfailed`.

- [ ] **Step 6: Commit**

```bash
git add templates/workflow-run.yml tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-45 + CCE-66 App-token plumbing (steps 8–9)

Template now has the GitHub App installation-token step with the
DOCS_AGENT_APP_CLIENT_ID opt-out gate. Hosts that don't register the App
fall through to secrets.GITHUB_TOKEN via the || fallback already wired in
Task 5's checkout-host/docs-agent steps — but their docs-agent PRs won't
trigger downstream host CI (deliberate GHA self-loop prevention).

CCE-66: uses `client-id` (not `app-id` — v3 rename).
CCE-54: action pinned to @v3 (Node-24 floor).

Lifts test_05 (App-token template-only shape: if-gate, client-id key,
||-fallback token expression, step-env GH_TOKEN).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Template absorb — OAuth four-arm assert (CCE-49) (commit 3/5)

**Files:**

- Modify: `templates/workflow-run.yml` (insert OAuth-assert step after "Install claude CLI", before "Configure git identity")

**What this absorbs:** Step 13 of §5.1.0 (OAuth four-arm pre-flight) with the `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT` opt-out gate (template-only divergence — dogfood doesn't need the gate; we own the auth).

- [ ] **Step 1: Insert the OAuth-assert step**

In `templates/workflow-run.yml`, between the "Install claude CLI" step and the "Configure git identity" step, insert:

```yaml
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
```

- [ ] **Step 2: Lint with actionlint AND shellcheck**

Run:

```bash
actionlint templates/workflow-run.yml
```

Expected: clean (remaining issues should only relate to Task 8 forensics + Task 9 stdout echo).

Extract the OAuth step body and run shellcheck:

```bash
# Extract just the OAuth assert run block to a temp file
cat > /tmp/oauth-assert.sh <<'EOF'
#!/usr/bin/env bash
set -u
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
EOF
shellcheck /tmp/oauth-assert.sh
```

Expected: clean (no output). If shellcheck is not on PATH, skip with a note; CI catches it.

- [ ] **Step 3: Run parity test — same 4 passed + 4 xfailed (no new lifts in this task)**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: unchanged — `4 passed, 4 xfailed`. The `sk-ant-oat` substring assert lives inside `test_03_high_value_substring_asserts`, which waits to lift until Task 9 (it also needs `partial_reasons` from the CCE-73 bundle).

- [ ] **Step 4: Run full suite — green**

Run:

```bash
python3 -m pytest
```

Expected: `739 passed + 3 skipped + 4 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add templates/workflow-run.yml
git commit -m "$(cat <<'EOF'
feat(CCE-80): absorb CCE-49 OAuth four-arm pre-flight assert (step 13)

Three-layered substring check on CLAUDE_CODE_OAUTH_TOKEN: non-empty,
sk-ant-oat* prefix (with sk-ant-api* arm that points to claude setup-token),
length ≥ 32. ::error:: annotations surface in the GHA UI.

vars.DOCS_AGENT_SKIP_OAUTH_ASSERT='true' opt-out is TEMPLATE-ONLY —
dogfood doesn't carry the gate (we own this repo's auth). Shellcheck-clean.

No xfails lift this task; substring assertions wait for the full set
including CCE-73 partial_reasons (Task 9).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Template absorb — CCE-41 subagent forensics (commit 4/5)

**Files:**

- Modify: `templates/workflow-run.yml` (add DOCS_AGENT_DEBUG_DIR to docs-agent step-env; insert upload-artifact forensics step after docs-agent)

**What this absorbs:** Steps 15 (DOCS_AGENT_DEBUG_DIR step-env) and 16 (Upload subagent forensics) of §5.1.0.

- [ ] **Step 1: Add DOCS_AGENT_DEBUG_DIR to docs-agent step-env**

In `templates/workflow-run.yml`, find the `docs-agent` step's `env:` block (currently has only `GH_TOKEN`). Add `DOCS_AGENT_DEBUG_DIR` above it:

```yaml
- name: Run docs-agent
  id: docs-agent
  env:
    # SP-1 / CCE-41: forensics capture mode. Per-dispatch
    # prompt/stdout/stderr/stream/meta land in this dir; the
    # upload-artifact step below persists them past the runner.
    # See scripts/orchestrator_runner.py:357.
    DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug
    GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}
  run: |
    python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

- [ ] **Step 2: Insert upload-artifact step after docs-agent**

Between "Run docs-agent" and "Run summary", insert:

```yaml
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
```

- [ ] **Step 3: Lint**

Run:

```bash
actionlint templates/workflow-run.yml
```

Expected: clean (remaining issues only relate to Task 9's CCE-73 stdout echo).

- [ ] **Step 4: Run parity test — same 4 passed + 4 xfailed**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: unchanged `4 passed, 4 xfailed`.

- [ ] **Step 5: Run full suite — green**

Run:

```bash
python3 -m pytest
```

Expected: `739 passed + 3 skipped + 4 xfailed`.

- [ ] **Step 6: Commit**

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
test_01 step-signature parity check which lifts in Task 9 alongside the
CCE-73 bundle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Template absorb — CCE-73 stdout echo + dogfood co-edit (commit 5/5)

**Files:**

- Modify: `templates/workflow-run.yml` (add Print partial-run reasons step after Run summary)
- Modify: `.github/workflows/docs-agent-nightly.yml` (add the SAME step — co-edit per locked decision CO-EDIT)
- Modify: `tests/templates/test_workflow_run_parity.py` (lift xfails on test_01, test_02, test_03, test_06; implement bodies)

**Why both files?** Locked decision CO-EDIT (spec §3): bundle CCE-73 into THIS PR so the parity test can fully lift at merge time. No xfail follow-up.

- [ ] **Step 1: Add Print partial-run reasons step to TEMPLATE**

In `templates/workflow-run.yml`, append AFTER the "Run summary" step (at the end of the steps block):

```yaml
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
```

- [ ] **Step 2: Add the SAME step to DOGFOOD**

In `.github/workflows/docs-agent-nightly.yml`, after the "Run summary" step (currently the last step, ending around line 198), append:

```yaml
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
```

- [ ] **Step 3: Lint both files**

Run:

```bash
actionlint templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml
```

Expected: clean.

- [ ] **Step 4: Lift parity-test xfails on test_01, test_02, test_03, test_06**

Edit `tests/templates/test_workflow_run_parity.py`. Replace each function:

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

    # Every dogfood signature is either in the template or explicitly
    # allowlisted.
    missing_in_template = dogfood_sigs - template_sigs - set(_ALLOWLIST)
    assert not missing_in_template, (
        "Dogfood steps with no template counterpart and no allowlist entry: "
        f"{sorted(missing_in_template)}.\n"
        "Action: absorb into templates/workflow-run.yml OR add an _ALLOWLIST "
        "entry in tests/templates/test_workflow_run_parity.py with rationale."
    )


def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    """Each step using an action listed in _WITH_KEY_CONTRACT has the
    documented keys present. Extra keys are allowed if present in BOTH files.
    """
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        for step in steps:
            uses = step.get("uses")
            if uses in _WITH_KEY_CONTRACT:
                with_block = step.get("with") or {}
                expected = _WITH_KEY_CONTRACT[uses]
                missing = expected - set(with_block.keys())
                # For actions/checkout@v5 the `token:` key is only required
                # when the App-token wiring is meaningful. Template requires
                # it on checkout-host (id check); dogfood requires it on its
                # single checkout step.
                if uses == "actions/checkout@v5":
                    if step.get("id") not in ("checkout-host",) and label == "template":
                        # checkout-plugin step legitimately doesn't carry `token:`.
                        continue
                assert not missing, (
                    f"{label}: step `{step.get('name')}` uses {uses} but "
                    f"missing required with: keys {sorted(missing)}"
                )


def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    """Substring asserts on the parsed `run:` scalar (not raw bytes)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        run_blocks = [s.get("run", "") for s in steps]
        joined = "\n---\n".join(str(r) for r in run_blocks)

        # OAuth pre-flight (template only — dogfood has it too, but template
        # has the four-arm shape per spec §6.1.3; dogfood matches).
        assert "sk-ant-oat" in joined, f"{label}: missing sk-ant-oat assertion"
        assert "sk-ant-api" in joined, f"{label}: missing sk-ant-api arm"
        # CLI install verification
        assert "which claude" in joined, f"{label}: missing which-claude verify"
        # Git identity step
        assert "engineering-docs-agent[bot]" in joined, f"{label}: missing bot identity"
        # CCE-73 stdout echo
        assert "partial_reasons" in joined, f"{label}: missing partial_reasons echo (CCE-73 bundle)"


def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    """Every _ALLOWLIST entry matches at least one step in dogfood OR template;
    no entry matches a step present in BOTH (redundant-allowlist guard)."""
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

    # Some allowlist entries are non-step (env.SLACK_WEBHOOK_URL,
    # with.path==..., pull_request.types==[...], if:...) — those are matched
    # via custom code rather than step-signature comparison. For this test we
    # only validate the step-signature-style entries.
    step_style_entries = {k for k in _ALLOWLIST if k.startswith("uses:") or k.startswith("run:")}

    for key in step_style_entries:
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

- [ ] **Step 5: Run parity test — expect all 8 PASSED**

Run:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py -v
```

Expected: `8 passed`. No xfails remain.

- [ ] **Step 6: Run full suite — green**

Run:

```bash
python3 -m pytest
```

Expected: `743 passed + 3 skipped + 0 xfailed`.

- [ ] **Step 7: Commit**

```bash
git add templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml tests/templates/test_workflow_run_parity.py
git commit -m "$(cat <<'EOF'
feat(CCE-80): bundle CCE-73 stdout echo (step 18) + dogfood co-edit

Print partial-run reasons step added to BOTH templates/workflow-run.yml
AND .github/workflows/docs-agent-nightly.yml per the CO-EDIT locked
decision (spec §3). `if: always()` ensures it runs on failed/partial runs;
`// empty` null-safe; `|| true` tolerates malformed state.json.

Lifts ALL remaining xfails on the parity test:
- test_01 step-signature parity (full step list now compared)
- test_02 with-key contract (App-token + upload-artifact + checkout)
- test_03 substring asserts (now includes partial_reasons)
- test_06 stale + redundant allowlist guards (full set asserted)

Suite: 743 passed + 3 skipped + 0 xfailed (was 739 + 4 xfailed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Migration runbook `docs/runbooks/cce80-host-migration.md`

**Files:**

- Create: `docs/runbooks/cce80-host-migration.md`

**Why:** Spec §8 — the 3 known hosts (ADIS, CCSA, data-importer) need an explicit, verification-rich runbook. Including ADIS-69 mkdocs carve-out.

- [ ] **Step 1: Create the runbook**

```bash
mkdir -p docs/runbooks
```

Create `docs/runbooks/cce80-host-migration.md` with the following content (verbatim from spec §8 with `<host>` placeholders and `gh` commands embedded):

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
````

This makes the setup skill resolve to the feature branch's SKILL.md + scripts.
After merge, run `claude plugin update engineering-docs-agent` to switch back
to the main-tracking install.

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

- `.github/workflows/docs-agent-nightly.yml` exists (delete the pre-CCE-80 `docs-agent-run.yml` if present).
- File contains `client-id:`, OAuth-assert step, forensics step, run-summary step, Print-partial-reasons step.
- Cron line: `grep -E '^\s+- cron: "[0-9]+ 7 \* \* \*"' .github/workflows/docs-agent-nightly.yml` returns a single line with a minute in `[5, 55]`.

### 3. (ADIS only) Re-apply mkdocs install carve-out

ADIS uses mkdocs (CCE-69 deferred). After re-scaffolding, insert this step
IMMEDIATELY AFTER the "Install runtime dependencies" step (step 11 → step 12
in the §5.1.0 ordering):

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

- [ ] **Step 2: Run full suite — no regressions**

Run:
```bash
python3 -m pytest
````

Expected: `743 passed + 3 skipped + 0 xfailed` (unchanged from Task 9).

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/cce80-host-migration.md
git commit -m "$(cat <<'EOF'
docs(CCE-80): host-migration runbook — docs/runbooks/cce80-host-migration.md

Per-host migration steps for ADIS, CCSA, data-importer with explicit
verification commands at each step (gh secret list, grep on cron line,
gh run watch, etc.). Pre-merge plugin-tree clarification (claude plugin
add --local) so operators re-scaffolding before merge use the feature
branch's SKILL.md + scripts.

Post-merge gate: PR author cuts v0.5.0 tag within 5 min, verifies via
gh release view; host migration does not proceed until the tag exists
(prevents the plugin-vendoring checkout from failing on a missing ref).

ADIS-only carve-out for mkdocs install captures the CCE-69 deferral
without baking it into the generic template.

Step 4 rollback documents the recovery path if a host's manual dispatch
fails post-re-scaffold.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: CONTRIBUTING.md — dogfood↔template parity gate

**Files:**

- Create: `CONTRIBUTING.md`

**Why:** Spec §7 acceptance criterion. The parity test catches drift, but a contributor-facing note prevents the friction of a confused contributor whose dogfood edit fails CI.

- [ ] **Step 1: Create CONTRIBUTING.md**

Create `CONTRIBUTING.md`:

````markdown
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

```bash
gh release create vX.Y.Z \
    --target main \
    --title "vX.Y.Z — short description" \
    --notes "Summary of changes."
gh release view vX.Y.Z
```
````

Cut the tag within 5 minutes of merge — hosts re-scaffolding before the
tag exists will fail at the plugin-vendoring checkout step.

````

- [ ] **Step 2: Run full suite — no regressions**

Run:
```bash
python3 -m pytest
````

Expected: `743 passed + 3 skipped + 0 xfailed`.

- [ ] **Step 3: Commit**

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

**Why:** Spec §7 acceptance criteria checklist. This task is verification-only — its purpose is to confirm green CI before /ship.

- [ ] **Step 1: Run full pytest suite**

Run:

```bash
python3 -m pytest
```

Expected: `743 passed + 3 skipped + 0 xfailed`. No failures.

- [ ] **Step 2: Run actionlint on both edited workflow files**

Run:

```bash
actionlint templates/workflow-run.yml .github/workflows/docs-agent-nightly.yml
```

Expected: clean (no output). If actionlint surfaces a finding, fix it before /ship.

- [ ] **Step 3: Shellcheck the OAuth pre-flight step body**

Extract to /tmp/oauth-assert.sh as in Task 7 step 2; run:

```bash
shellcheck /tmp/oauth-assert.sh
```

Expected: clean.

- [ ] **Step 4: Verify the live cron rewrite end-to-end**

Run:

```bash
python3 scripts/scaffold_workflow.py --owner theoju --repo dogfood | head -20
```

Expected: output starts with the FN header (`# Drop into the host repo at .github/workflows/docs-agent-nightly.yml`) and contains a cron line `- cron: "<minute> 7 * * *"` where `<minute>` is between 5 and 55.

- [ ] **Step 5: Verify SKILL.md edits via grep**

Run:

```bash
grep -c "docs-agent-nightly.yml" skills/engineering-docs-agent-setup/SKILL.md
grep -c "docs-agent-run.yml" skills/engineering-docs-agent-setup/SKILL.md
grep -c "scaffold_workflow.py" skills/engineering-docs-agent-setup/SKILL.md
grep -c "DOCS_AGENT_APP_CLIENT_ID" skills/engineering-docs-agent-setup/SKILL.md
```

Expected: line 1 ≥ 1; line 2 == 0; line 3 ≥ 1; line 4 ≥ 1.

- [ ] **Step 6: Verify parity-test allowlist is non-stale**

The `test_06_stale_allowlist_entries` test already enforces this. As a manual sanity check:

```bash
python3 -m pytest tests/templates/test_workflow_run_parity.py::test_06_stale_allowlist_entries -v
```

Expected: PASSED.

- [ ] **Step 7: Verify final commit count and branch state**

Run:

```bash
git log --oneline main..HEAD
```

Expected output: 13 lines (2 spec commits from before + 11 implementation commits from this plan). Approximately:

```
<sha> docs(CCE-80): CONTRIBUTING.md — dogfood↔template parity gate
<sha> docs(CCE-80): host-migration runbook
<sha> feat(CCE-80): bundle CCE-73 stdout echo + dogfood co-edit
<sha> feat(CCE-80): absorb CCE-41 subagent forensics
<sha> feat(CCE-80): absorb CCE-49 OAuth four-arm pre-flight assert
<sha> feat(CCE-80): absorb CCE-45 + CCE-66 App-token plumbing
<sha> feat(CCE-80): absorb CCE-39 baseline
<sha> docs(CCE-80): SKILL.md — invoke scaffold_workflow.py + App-token CI warning
<sha> feat(CCE-80): setup_discover.discover_git_origin() — emit {owner, repo}
<sha> feat(CCE-80): scripts/scaffold_workflow.py — deterministic per-host cron rewrite
<sha> test(CCE-80): xfailed parity-test skeleton + ruamel.yaml dev dep
c450653 docs(CCE-80): spec revisions — apply 6 criticals + 25 importants from validation panel
b959da0 docs(CCE-80): spec — refresh templates/workflow-run.yml to match dogfood's nightly
```

- [ ] **Step 8: Surface ship-readiness**

Print to the user (do NOT invoke /ship — that's the next stage, driven by the controller):

> **CCE-80 implementation complete. 11 commits on `chore/CCE-80-template-workflow-run-refresh`.**
>
> - **All 8 parity tests pass.** Full suite: 743 passed + 3 skipped + 0 xfailed.
> - **`actionlint` clean** on both `templates/workflow-run.yml` and `.github/workflows/docs-agent-nightly.yml`.
> - **`shellcheck` clean** on OAuth-assert step.
> - **`scripts/scaffold_workflow.py` CLI verified** — deterministic cron + FN header rendering correctly.
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

| Spec section                                          | Plan task                                                                                            |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------- | ------ |
| §3 D1 — all 16 STALE in one PR                        | Tasks 5–9                                                                                            |
| §3 D2 — OAuth-primary, drop ANTHROPIC_API_KEY         | Task 5 (job-env block)                                                                               |
| §3 D3 — App-token opt-in with `                       |                                                                                                      | ` fallback | Task 6 |
| §3 D4 — keep `pull_request: closed` + self-loop guard | Task 5 (preserved as TEMPLATE-ONLY)                                                                  |
| §3 D5 — bundle CCE-73 stdout echo                     | Task 9                                                                                               |
| §3 MIG — hard cutover + runbook                       | Task 10                                                                                              |
| §3 PIN — v0.5.0 release tag                           | Task 5 (template `ref: v0.5.0`), Task 10 (runbook post-merge cut), Task 11 (CONTRIBUTING.md cadence) |
| §3 FN — docs-agent-nightly.yml                        | Tasks 4 (SKILL.md), 5 (template header)                                                              |
| §3 SLK — keep SLACK_WEBHOOK_URL                       | Task 5 (job-env block)                                                                               |
| §3 CO-EDIT — dogfood in same PR                       | Task 9                                                                                               |
| §3 ADIS-69 — mkdocs carve-out in runbook              | Task 10 step 3                                                                                       |
| §3 OAUTH-VAR — keep DOCS_AGENT_SKIP_OAUTH_ASSERT      | Task 7                                                                                               |
| §4.2 Generic-first                                    | Task 5 (vars/secrets split), Task 2 (deterministic cron), Task 3 (owner/repo discovery)              |
| §5.1.0 18-step final template                         | Tasks 5–9 (incrementally)                                                                            |
| §5.1.1 5-commit absorption sequence                   | Tasks 5–9 (one task per commit)                                                                      |
| §5.1.2 Dogfood co-edit                                | Task 9 step 2                                                                                        |
| §5.1.3 All 16 STALE items                             | Distributed across Tasks 5–9 per §5.1.0 mapping                                                      |
| §5.2 TEMPLATE-ONLY items preserved                    | Task 5 (header, pull_request, self-loop, SLACK), Task 6 (App-token), Task 9 (preserved in test_05)   |
| §5.3.1 scripts/scaffold_workflow.py                   | Task 2                                                                                               |
| §5.3.2 SKILL.md step 6                                | Task 4                                                                                               |
| §5.3.3 SKILL.md step 8                                | Task 4                                                                                               |
| §5.3.4 setup-guide.md vars/secrets matrix             | **Gap — adding** (see below)                                                                         |
| §5.3.5 discover_git_origin                            | Task 3                                                                                               |
| §5.3.6 pre-merge plugin-tree                          | Task 10 (runbook pre-merge checklist)                                                                |
| §5.4 v0.5.0 tag sequence                              | Task 10 post-merge gate                                                                              |
| §6.1 8 parity-test functions                          | Tasks 1, 5, 6, 9 (skeleton + progressive lift)                                                       |
| §6.2 scaffold_workflow tests                          | Task 2                                                                                               |
| §6.3 SKILL.md grep test                               | Task 4                                                                                               |
| §7 Acceptance criteria                                | Task 12                                                                                              |
| §8 Migration runbook                                  | Task 10                                                                                              |
| §9 Risk surface                                       | Documented in spec; no plan action (advisory)                                                        |

**Gap:** §5.3.4 — setup-guide.md vars/secrets matrix is documented in the spec but not yet allocated to a plan task. Folding into Task 11 as a second commit would inflate the task; better to add a dedicated Task 11b. **However**, on review: the matrix is operator-facing documentation that lives in the doc-site, not in repo root. Verify the file exists first — if it does, add a step to Task 11. If it doesn't, defer to a setup-skill follow-up (CCE-69 territory). Folding the verification into Task 12 step 8's user-facing summary so the user can decide.

### Placeholder scan

Searched plan for `TBD`, `TODO`, `implement later`, `Add appropriate`, `Similar to Task N`, `add validation`, `handle edge cases`, `Write tests for`. **No matches.** Every step contains either exact code, exact commands, or exact substring/file targets.

### Type consistency

- `deterministic_cron_minute(owner, repo) -> int` — used identically in Task 2 (definition), Task 2 step 5 (fixture test), and Task 5 step 7 (round-trip).
- `discover_git_origin(repo_root) -> dict | None` — defined Task 3 step 3, used identically in test (Task 3 step 1), and referenced by SKILL.md (Task 4 step 4, via `discovery["git"]`).
- `_ALLOWLIST: dict[str, str]` and `_WITH_KEY_CONTRACT: dict[str, set[str]]` — defined Task 1 step 4, referenced unchanged in Tasks 5/6/9 test body implementations.
- Step IDs (`app-token`, `checkout-host`, `checkout-plugin`, `docs-agent`, `assert-oauth`, `git-identity`) — used consistently across template absorption tasks (5–9) and parity test (1, 5, 6, 9).
- Workflow filename — `docs-agent-nightly.yml` everywhere (no `docs-agent-run.yml` leakage in any new code/text).

No type-consistency violations found.

### Final note

The plan is comprehensive, executable, TDD-disciplined, and matches the spec's commit-sequence model. Execution path: `superpowers:subagent-driven-development` dispatches a fresh subagent per task with two-stage review (spec compliance, then code quality) between each. After Task 12, controller invokes `/ship`.
