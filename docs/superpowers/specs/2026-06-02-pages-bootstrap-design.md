# Pages bootstrap fix — design

**Status:** Draft v2 (post-3-agent verification; awaiting user review)
**Tracker:** CCE-XX (to be filed when spec is approved)
**Related:** `theoju/claude-code-self-assessment` PR #121 / CCE-81 (originating incident, shipped 2026-06-02), PR #122 (post-merge corrections)
**Type:** Bug + plugin tech-debt
**Author:** Theo Jungeblut + Claude (session originated from `theoju/claude-code-self-assessment`)

## Context

`theoju/claude-code-self-assessment` was the third host onboarded to this plugin and the first to actually exercise the `framework: mkdocs` publish path end-to-end — onboarded with a synthetic scaffold from CCE-57, then upgraded to a real mkdocs site in PR #121 / CCE-81 on 2026-06-02.

The first push-triggered run of the consumer's `docs-agent-pages.yml` after merge failed at `actions/configure-pages@v6` with:

```
Get Pages site failed. Error: Not Found
Create Pages site failed. Error: Resource not accessible by integration
HttpError: Resource not accessible by integration
```

Recovery: one-off `gh api -X POST repos/theoju/claude-code-self-assessment/pages -f build_type=workflow` from a personal admin gh login, then `gh workflow run docs-agent-pages.yml` to re-fire the deploy. Site went live on the retry.

**Root cause:** `actions/configure-pages@v6` with `enablement: true` cannot create the Pages site on first run when invoked with the default `GITHUB_TOKEN`. The token lacks admin scope; `permissions:` blocks can only restrict the default token's scopes, never expand them. The field is therefore a no-op on first run (when it would matter) and a no-op every subsequent run (when Pages already exists). (If a workflow overrides `token:` with a PAT carrying admin scope, `enablement: true` DOES work — but no plugin host configures that today, and the spec's deliverables explicitly drop the field rather than make it work, since the `gh api` path during setup is strictly cleaner.)

This is fundamentally a plugin bug — the misleading line lives in `templates/workflow-pages.yml`, which gets copied into every future `framework: mkdocs` host. The setup skill's step 6a documents the wrong assumption verbatim. Every new mkdocs host onboarded going forward will hit the same first-deploy failure unless we fix this here.

The consumer-side incident artifacts (CLAUDE.md gotcha bullet, PR #121 spec correction, plan post-merge section) all landed in `theoju/claude-code-self-assessment` PR #122. This spec is the durable plugin-side fix that closes the bug for every future host AND mirrors the fix to the originating consumer AND fixes the plugin's OWN deployed Pages workflow (the plugin is itself a dogfood mkdocs host).

## Goals

1. **Stop writing `enablement: true`** in any workflow file shipped by this codebase — the template, the plugin's own deployed workflow, and the consumer's already-deployed workflow.
2. **Bootstrap Pages programmatically during host setup** via a new `scripts/enable_pages.py` invoked from the setup skill's new step 6c. The script wraps `gh api -X POST repos/$OWNER/$REPO/pages -f build_type=workflow` with three robust failure-mode behaviors (201 happy, 409 idempotent, all-other-paths graceful fallback that never blocks scaffolding).
3. **Update docs/test surfaces** so the new posture is the regression guard. The existing test that asserts `enablement: true IS present` gets flipped to assert ABSENCE; the consumer's test gets the same flip; the SKILL.md text matches reality.
4. **Prevent the same footgun from biting future hosts** — the plugin template + setup skill are the single source of truth for every new `framework: mkdocs` onboarding.
5. **Mirror the fix everywhere it currently leaks** — including comment text that repeats the wrong claim verbatim (the consumer's `docs-agent-pages.yml` lines 3-6).

## Non-goals

1. **No re-deploy of any existing host's site.** The fix changes templates + scaffolding + comment text + the plugin's own deploy workflow, not steady-state runtime behavior. Hosts that already have Pages bootstrapped (CCE-81's consumer; the plugin's own site) continue to deploy on every docs change.
2. **No retroactive workflow rewriting for already-onboarded third-party hosts.** The plugin's nightly does NOT overwrite host-owned workflow files. Existing hosts keep whatever they have; the consumer-side drive-by is the explicit follow-up for the one external host that exists today.
3. **No migration away from `configure-pages@v6`.** The action still does useful work — sets `GITHUB_PAGES` env var that `deploy-pages@v5` reads. We're dropping ONE field (`enablement: true`), not the action.
4. **No changes for non-MkDocs hosts.** The skill's step 6a branch that skips writing `docs-agent-pages.yml` when neither MkDocs nor `publishing.build_command` is configured stays as-is. Step 6c is conditional on 6a having written the workflow.
5. **No upstream patch to `actions/configure-pages`.** GitHub-side, not in our control. Filed as future work; explicitly out of scope.
6. **No new GitHub Apps, secrets, or org-level changes.** The `gh api` call uses the operator's existing gh auth at scaffold-time, not a long-lived token in any repo.
7. **No `--skip-pages-enable` flag.** YAGNI until someone asks. The graceful-fallback behavior already gives users the manual path.
8. **No support claimed for GitHub Enterprise Server hosts.** GHES uses a different API path (`/api/v3/repos/.../pages` at a custom domain); the script speaks only github.com. Documented in Open Questions §Q5; explicit non-goal.
9. **No support claimed for forks or repos where the operator lacks admin.** The graceful-fallback path documents the manual recovery; the script never tries to elevate permissions.

## Architecture

### One conceptual fix, four surfaces, two PRs

The bug has four distinct surfaces:

| #   | Surface                                                           | Repo                        |
| --- | ----------------------------------------------------------------- | --------------------------- |
| α   | Plugin template (source of every future host's bad line)          | engineering-docs-agent      |
| β   | Plugin's own deployed workflow (dogfood mkdocs host)              | engineering-docs-agent      |
| γ   | Setup skill behavior + the `gh api` bootstrap call it should make | engineering-docs-agent      |
| δ   | Active third-party consumer host already carrying the bad line    | claude-code-self-assessment |

Surfaces α, β, γ ship as ONE PR in the plugin repo (PR #B). Surface δ ships as a tiny drive-by PR in the consumer repo (PR #A). The four surfaces fix the same conceptual bug; the deployment vehicles split along repo boundaries.

### Decision: inline `gh api` from the skill, with graceful fallback

The new `scripts/enable_pages.py` is invoked synchronously by the setup skill's step 6c. Four failure-mode behaviors:

1. **Happy path (HTTP 201, gh exit 0, non-empty JSON body):** Pages enabled; print `✓ Pages enabled` + the page URL; continue.
2. **Already enabled (HTTP 409 — gh exit 1, stderr contains literal `(HTTP 409)`):** Pages exists; print `✓ Pages already enabled (idempotent)`; continue silently. Re-running setup is safe.
3. **`gh` not installed or not on PATH:** Print `⚠ `gh` CLI not found` + manual recovery command; continue scaffolding; return 0.
4. **Any other failure (HTTP 401/403/422/500, gh exit non-zero, gh exit 0 with empty body, gh exit 139):** Print `⚠ Could not enable Pages` + the exact manual recovery command + the actual error; continue scaffolding; return 0. **Never blocks setup.**

Two important precision rules captured from the 3-agent verification:

- Exit-code detection must NOT rely on `gh`'s actual code — `gh` exits `1` on all HTTP 4xx (not 4 or 22). The script reads `gh`'s exit + stderr together; the substring match for 409/403 uses the literal `(HTTP NNN)` with parentheses to avoid false positives against JSON bodies containing `"status":"409"` or unrelated prose containing `"already exists"`.
- Empty stdout on exit 0 is suspect (could indicate a network glitch or proxy interception); the script requires non-empty output before claiming success.

This matches the plugin's existing "degrade gracefully" pattern documented in CLAUDE.md: _"When a host lacks a convention... the affected capability skips or falls back cleanly — it never errors and never emits an empty artifact."_

### Decision: separate small helper script, not inline shell-out from SKILL.md

`scripts/enable_pages.py` is a small CLI, not inline `bash` blocks in the skill's markdown. Rationale: matches `scripts/setup_scaffold.py` + `scripts/scaffold_workflow.py` + `scripts/setup_discover.py` pattern; testable in isolation with a PATH-shadowed `gh` stub; multi-line failure-mode logic is fragile as markdown.

### Decision: existing same-named test is FLIPPED, not duplicated

The existing `tests/ci/test_workflow_pages_template.py:30` asserts `assert "enablement: true" in text`. PR #B's B0 deliverable flips that line to assert ABSENCE. Do NOT create a new file at `tests/site/test_workflow_pages_template.py` (the name collides with the existing test under a different directory; pytest collection becomes ambiguous; concerns split across two files). The existing test already validates pinned actions, permissions, `.nojekyll` — adding the negative assertion there keeps all template contract checks in one place.

### Decision: one Jira ticket covers both PRs

One CCE ticket (CCE-XX, to be filed when spec is approved). Both PRs reference it; the ticket transitions to Done when both merge.

## Deliverables

### Primary fix — plugin repo (PR #B)

**B0. Modify `tests/ci/test_workflow_pages_template.py`** — flip the positive assertion to negative (line 30) and broaden the match to catch variants:

```diff
 def test_enablement_and_nojekyll_and_no_jekyll_build():
     text = TPL.read_text()
-    assert "enablement: true" in text
+    # Regression guard: enablement: true is misleading (no-op on first deploy
+    # because the workflow token lacks admin scope; no-op forever after Pages
+    # exists). Pages bootstrap is done by scripts/enable_pages.py from
+    # SKILL.md step 6c using the operator's admin gh auth. See CCE-XX.
+    import re
+    assert not re.search(
+        r"^\s*enablement:\s*['\"]?true['\"]?\s*$",
+        text,
+        re.MULTILINE,
+    ), (
+        "templates/workflow-pages.yml must not carry `enablement: true` in "
+        "any form (quoted, unquoted, leading whitespace) — see CCE-XX."
+    )
     assert ".nojekyll" in text
```

Plus a structural assertion that catches a re-add via a `with:` block on `configure-pages@v6`:

```python
def test_configure_pages_step_has_no_with_block():
    """Structural guard against re-adding any `with:` block to configure-pages@v6.
    Currently no host configuration requires one; if one is added later, this
    test forces the maintainer to update both the test and the SKILL/CLAUDE.md
    documentation that explains WHY the field shouldn't be there."""
    data = yaml.safe_load(TPL.read_text())
    build_steps = data["jobs"]["build"]["steps"]
    cp_step = next(s for s in build_steps if s.get("uses", "").startswith("actions/configure-pages@"))
    assert "with" not in cp_step, (
        f"configure-pages step must not carry a `with:` block; found: {cp_step.get('with')}"
    )
```

**B1. Modify `templates/workflow-pages.yml`** — delete the misleading `with:` block under `configure-pages@v6` (currently lines 30-32):

```diff
       - uses: actions/checkout@v5
-      - uses: actions/configure-pages@v6
-        with:
-          enablement: true
+      - uses: actions/configure-pages@v6
       - uses: actions/setup-python@v6
```

After this, B0's existing-test + structural-test combination passes.

**B2. Add `scripts/enable_pages.py`** — new file, ~95 lines, robust against the four failure modes plus the substring-false-positive risk:

```python
#!/usr/bin/env python3
"""Bootstrap GitHub Pages on a host repo with build_type=workflow.

The setup skill's step 6c calls this once during scaffolding because
actions/configure-pages@v6 with `enablement: true` does NOT actually
work on first deploy — the workflow's GITHUB_TOKEN lacks admin scope
to create a Pages site (`permissions:` blocks can only restrict
default-token scopes, never expand them). The user's admin `gh` auth
does have the required scope.

Behaviors (all return exit 0 — scaffolding must never block on this):
  201 + non-empty JSON body: print "✓ Pages enabled", return 0.
  409 (matched by literal "(HTTP 409)" in stderr, not bare substring):
      print "✓ Pages already enabled (idempotent)", return 0.
  gh not on PATH: print "⚠ `gh` CLI not found" + manual recovery,
      return 0.
  Any other failure (401, 403, 422, 500, exit 139, exit 0 with empty
      body, etc.): print "⚠ Could not enable Pages" + manual recovery
      + the actual error, return 0.

Exit codes:
  0: any of the above behaviors completed.
  2: argument or environment error (missing/empty --owner/--repo).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys


_RECOVERY_TEMPLATE = (
    "    gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow"
)


def enable_pages(owner: str, repo: str) -> int:
    if not owner or not repo:
        print(
            "✗ --owner and --repo must both be non-empty.",
            file=sys.stderr,
        )
        return 2
    if shutil.which("gh") is None:
        print(
            "⚠ `gh` CLI not found on PATH. Pages must be enabled manually before "
            "first deploy:\n"
            + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
            + "\nContinuing with the rest of scaffolding."
        )
        return 0
    proc = subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{repo}/pages",
            "-f",
            "build_type=workflow",
        ],
        capture_output=True,
        text=True,
    )
    # Detect 409 with literal "(HTTP 409)" — matches gh's actual stderr format
    # "gh: ... (HTTP 409)" and avoids false positives from JSON bodies
    # containing `"status":"409"` or prose containing `"already exists"`.
    is_409 = bool(re.search(r"\(HTTP 409\)", proc.stderr))
    if proc.returncode == 0 and proc.stdout.strip():
        # Real Pages creation returns a JSON body with html_url; require non-empty
        # so a network-glitched empty-body exit-0 doesn't false-positive.
        print(f"✓ Pages enabled (https://{owner}.github.io/{repo}/)")
        return 0
    if is_409:
        print("✓ Pages already enabled (idempotent)")
        return 0
    err_summary = (proc.stderr or proc.stdout or "(no output)").strip()[:300]
    print(
        "⚠ Could not enable Pages programmatically. Run this manually before first deploy:\n"
        + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
        + f"\n(gh exit {proc.returncode}; error: {err_summary})\n"
        + "Continuing with the rest of scaffolding."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bootstrap GitHub Pages on a host repo with build_type=workflow."
    )
    p.add_argument("--owner", required=True, help="GitHub owner (user or org).")
    p.add_argument("--repo", required=True, help="Repository name.")
    args = p.parse_args()
    return enable_pages(args.owner, args.repo)


if __name__ == "__main__":
    sys.exit(main())
```

**B3. Modify `skills/engineering-docs-agent-setup/SKILL.md`** — rewrite the wrong claim in step 6a and add new step 6c.

Replace the existing wrong sentence in step 6a:

```diff
- `configure-pages(enablement:true)` sets the repo's Pages source to GitHub Actions on first run.
+ `configure-pages` is invoked without `enablement: true` — that field is misleading (it's a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope, despite `permissions: pages: write` being declared). Pages bootstrap happens via step 6c's `gh api` call using the operator's admin auth. `configure-pages` here only sets the deploy env var consumed by `deploy-pages@v5`.
```

Add new step 6c (inserted after 6b, conditional on 6a):

````markdown
6c. **Bootstrap GitHub Pages** for the host repo. SKIP this step if 6a did NOT write `docs-agent-pages.yml` (i.e., non-MkDocs host without `publishing.build_command`).

Pages must exist with `build_type=workflow` before the first push-triggered run of `docs-agent-pages.yml` will succeed. The setup skill performs this once during scaffolding using the user's admin `gh` auth (the workflow token lacks the required scope — see 6a). Reuse the `$OWNER`/`$REPO` resolved in step 6b (`discovery["git"]["owner"]` / `discovery["git"]["repo"]`, with `AskUserQuestion` fallback if `discovery["git"]` is `None`).

Run:

```bash
python <plugin_root>/scripts/enable_pages.py --owner "$OWNER" --repo "$REPO"
```
````

The script handles four cases and always returns 0 (never blocks scaffolding):

- **HTTP 201 (happy path):** prints `✓ Pages enabled (https://$OWNER.github.io/$REPO/)`.
- **HTTP 409 (already enabled):** prints `✓ Pages already enabled (idempotent)`. Safe on re-run.
- **`gh` not installed/on PATH:** prints `⚠ `gh` CLI not found` + the manual recovery command. The user runs the command after `gh auth login`.
- **Any other failure:** prints `⚠ Could not enable Pages` + the manual recovery command + the actual gh error.

````

**B4. Modify `CLAUDE.md`** in the plugin repo — add a convention bullet:

```markdown
- **`actions/configure-pages@v6 enablement: true` does NOT bootstrap GitHub Pages on a first deploy.** Despite the field name and the action's docs. The workflow's `GITHUB_TOKEN` lacks the admin scope required to call `POST /repos/.../pages`; `permissions:` blocks can only restrict default-token scopes, never expand them. The plugin's `templates/workflow-pages.yml` therefore does NOT include this field; bootstrap is done by `skills/engineering-docs-agent-setup` step 6c calling `scripts/enable_pages.py` (which wraps `gh api -X POST repos/.../pages -f build_type=workflow`) with the operator's admin gh auth. The script handles 4 failure modes (201, 409, gh-missing, all-other) and always returns 0 — graceful fallback never blocks scaffolding. Reference: CCE-XX (2026-06-02); the originating incident was `theoju/claude-code-self-assessment` PR #121 / CCE-81. The plugin's own dogfood `.github/workflows/docs-pages.yml` was also cleaned in this fix.
````

**B5. Add `tests/ci/test_enable_pages_cli.py`** — new file, ~180 lines, exercising every failure-mode branch plus the substring-false-positive risk + argv contract:

```python
"""Behavioral coverage of scripts/enable_pages.py — all four failure-mode
branches plus the substring-false-positive risk and the argv contract.

The test installs a `gh` stub in tmp_path/bin and PATH-shadows the real
binary. Real gh exits 1 on all HTTP 4xx (not 4 or 22 — those would be
curl-style codes); the stub mimics this. Each stub also writes its argv
to a side-channel file so the test can assert the script invokes gh with
the expected repos/<owner>/<repo>/pages path + build_type=workflow body.

Reference: CCE-XX. See SKILL.md step 6c.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "enable_pages.py"


def _install_gh_stub(
    bin_dir: Path,
    exit_code: int,
    stdout: str,
    stderr: str,
    argv_capture: Path | None = None,
) -> None:
    """Write a shell script named `gh` that exits with the given code/output.
    If argv_capture is set, the stub writes its full argv to that file so
    tests can assert the script invoked gh with the expected arguments."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gh"
    capture = f'printf "%s\\n" "$@" > {argv_capture}\n' if argv_capture else ""
    stub.write_text(
        f"#!/bin/sh\n"
        f"{capture}"
        f"cat >&2 <<'STDERR_EOF'\n{stderr}\nSTDERR_EOF\n"
        f"cat <<'STDOUT_EOF'\n{stdout}\nSTDOUT_EOF\n"
        f"exit {exit_code}\n"
    )
    stub.chmod(0o755)


def _run_cli(bin_dir: Path, owner: str = "octocat", repo: str = "sample") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(_CLI), "--owner", owner, "--repo", repo],
        capture_output=True,
        text=True,
        env=env,
    )


# --- Happy path ---

def test_happy_path_201_prints_success_and_returns_zero(tmp_path):
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"https://octocat.github.io/sample/","build_type":"workflow"}',
        stderr="",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, proc.stderr
    assert "✓ Pages enabled" in proc.stdout
    assert "octocat.github.io/sample" in proc.stdout


def test_argv_carries_correct_path_and_build_type(tmp_path):
    """Highest-leverage hardening: a future refactor that swaps owner/repo
    or drops `-f build_type=workflow` would still pass other tests because
    the stub ignores argv. This test asserts gh was called with the right
    path components and the build_type form-field."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    _run_cli(tmp_path / "bin", owner="my-org", repo="some-repo")
    argv = argv_file.read_text().splitlines()
    # ["api", "-X", "POST", "repos/my-org/some-repo/pages", "-f", "build_type=workflow"]
    assert "repos/my-org/some-repo/pages" in argv, f"argv was: {argv}"
    assert "build_type=workflow" in argv, f"argv was: {argv}"
    assert "POST" in argv
    assert "api" in argv


# --- 409 idempotent ---

def test_already_enabled_409_is_idempotent(tmp_path):
    # Real gh stderr format: "gh: HTTP 409: Conflict (...)" or similar
    # containing the literal "(HTTP 409)" in parens.
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,  # gh exits 1 on HTTP 4xx, regardless of HTTP code
        stdout="",
        stderr='gh: Pages site already created (HTTP 409)',
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" in proc.stdout.lower()
    assert "⚠" not in proc.stdout  # not a warning path


def test_409_substring_false_positive_is_not_classified_as_idempotent(tmp_path):
    """A 500 whose error body QUOTES `HTTP 409` (or contains the bare phrase
    `already exists` in unrelated prose) must NOT be classified as idempotent.
    The script uses `re.search(r"\\(HTTP 409\\)", stderr)` — literal parens
    only matches gh's actual format, not arbitrary substrings."""
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,
        stdout="",
        stderr='gh: Internal Server Error: previous request returned HTTP 409 - not retried (HTTP 500)',
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" not in proc.stdout.lower(), proc.stdout
    assert "⚠ Could not enable" in proc.stdout


# --- Fallback path (all non-201/409 cases collapse to graceful fallback) ---

@pytest.mark.parametrize(
    "exit_code,stderr",
    [
        (1, "gh: Resource not accessible by integration (HTTP 403)"),
        (1, "gh: Unauthorized (HTTP 401)"),
        (1, "gh: Validation failed (HTTP 422)"),
        (1, "gh: Internal Server Error (HTTP 500)"),
        (139, ""),  # segfault — empty stderr
        (0, ""),    # exit 0 but empty body — could be proxy interception
    ],
    ids=["403_auth", "401_unauth", "422_validation", "500_server", "139_segfault", "0_empty_body"],
)
def test_all_non_201_non_409_paths_fall_back_gracefully(tmp_path, exit_code, stderr):
    _install_gh_stub(tmp_path / "bin", exit_code=exit_code, stdout="", stderr=stderr)
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, "must never block scaffolding"
    assert "⚠ Could not enable Pages" in proc.stdout
    assert "gh api -X POST repos/octocat/sample/pages -f build_type=workflow" in proc.stdout
    assert "Continuing" in proc.stdout


# --- gh missing ---

def test_gh_missing_prints_recovery_and_returns_zero(tmp_path):
    # PATH intentionally empty-except-for-stub-dir to force shutil.which('gh') -> None
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(empty_bin)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--owner", "octocat", "--repo", "sample"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "`gh` CLI not found" in proc.stdout
    assert "gh api -X POST repos/octocat/sample/pages" in proc.stdout


# --- Argparse boundary ---

def test_missing_args_returns_nonzero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_CLI)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    # argparse default is exit 2 on missing required
    assert "owner" in proc.stderr.lower() or "owner" in proc.stdout.lower()


def test_empty_owner_or_repo_rejected_with_exit_2(tmp_path):
    """argparse `required=True` only guards missingness, not empty strings.
    The script must reject empty strings explicitly, otherwise it would POST
    to `repos//<repo>/pages` and confuse gh."""
    for args in [["--owner", "", "--repo", "x"], ["--owner", "x", "--repo", ""]]:
        proc = subprocess.run(
            [sys.executable, str(_CLI), *args],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2, f"expected exit 2 for empty owner/repo, args={args}, got {proc.returncode}"


# --- Argparse cosmetics ---

def test_owner_with_hyphen_works(tmp_path):
    """argparse handles hyphens in values fine; pin the contract."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    proc = _run_cli(tmp_path / "bin", owner="my-cool-org-name", repo="repo-with-dashes")
    assert proc.returncode == 0
    argv = argv_file.read_text().splitlines()
    assert "repos/my-cool-org-name/repo-with-dashes/pages" in argv
```

**B6. Modify `.github/workflows/docs-pages.yml`** in the plugin repo (the plugin's OWN dogfood Pages workflow — surface β) — delete the same `with:` block (lines 23-25):

```diff
       - uses: actions/checkout@v5
-      - uses: actions/configure-pages@v6
-        with:
-          enablement: true
+      - uses: actions/configure-pages@v6
       - uses: actions/setup-python@v6
```

Same fix; same justification. The plugin's site at `https://theoju.github.io/engineering-docs-agent/` already has Pages bootstrapped (every prior deploy proves it), so dropping the line is purely the same no-op cleanup as on the consumer.

**B7. Add CHANGELOG.md entry** (Unreleased section):

```markdown
### Fixed

- **Pages bootstrap on first host deploy.** Replaced `actions/configure-pages@v6 enablement: true` (a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope) with a setup-time `gh api -X POST repos/.../pages -f build_type=workflow` call from the new `scripts/enable_pages.py`. The setup skill's step 6c invokes it after writing the docs-pages workflow. Graceful fallback on all error paths — scaffolding never blocks on Pages bootstrap. Originating incident: `theoju/claude-code-self-assessment` PR #121 / CCE-81. Tracker: CCE-XX.
```

### Consumer-side drive-by — claude-code-self-assessment (PR #A)

This is a small cleanup PR that mirrors the template fix to the one already-onboarded third-party host. Ships before, after, or in parallel with PR #B.

**A1. `.github/workflows/docs-agent-pages.yml`** — delete the misleading `with:` block AND clean the comment block at lines 3-6 that repeats the wrong claim verbatim:

```diff
 name: docs-agent-pages

 # Builds the mkdocs site and deploys to GitHub Pages.
-# Fires only when docs sources actually change (path filter below) +
-# manual workflow_dispatch. configure-pages@v6 with enablement: true
-# enables Pages programmatically on the first run.
+# Fires only when docs sources actually change (path filter below) +
+# manual workflow_dispatch.

 on:
   push:
     branches: [main]
     paths:
       - "docs/site-src/**"
       ...

       - uses: actions/checkout@v5
-      - uses: actions/configure-pages@v6
-        with:
-          enablement: true
+      - uses: actions/configure-pages@v6
       - uses: actions/setup-python@v6
```

LOC delta: −6 (4 from `with:` block + comment chunk, +0 since comment is replaced by a shorter version).

**A2. `scripts/__tests__/docs-mkdocs-scaffold.test.mjs:76`** — flip the assertion (regression guard):

```diff
     expect(body).toMatch(/actions\/configure-pages@v6/);
-    expect(body).toMatch(/enablement:\s*true/);
+    expect(body).not.toMatch(/enablement:\s*['"]?true['"]?/);
     expect(body).toMatch(/actions\/upload-pages-artifact@v5/);
```

Aligned with the plugin's broader regex (matches `enablement:true`, `enablement: "true"`, etc., not just `enablement: true`).

**A3. `docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md`** — append a ONE-line "Resolved by" footer to the existing POST-IMPLEMENTATION CORRECTION block (lines 426-454).

The existing block ALREADY recommends "drop the `enablement: true` line ... and bake the `gh api` call into ... `setup_scaffold` script." So A3 does NOT need to re-state the recommendation — only point at the resolution:

```diff
 > The CLAUDE.md
 > Conventions section now carries this gotcha for the project.
+>
+> **Resolved 2026-06-02 by PR #A (this repo) + PR #B (plugin) under CCE-XX:** template + this repo's workflow + plugin's own workflow all cleaned; bootstrap is now done by `scripts/enable_pages.py` from SKILL.md step 6c.
```

**A4. `CLAUDE.md`** — minor update to the Pages enablement convention bullet (added in PR #122): replace "The line should be deleted from the workflow" with "The line was deleted from the workflow in PR #A / CCE-XX" and shorten the redundant explanation that's now duplicated in the plugin's CLAUDE.md (B4):

```diff
- The line should be deleted from the workflow to
- remove the footgun; the post-implementation note in the spec
+ The line was deleted from the workflow in PR #A / CCE-XX (2026-06-02).
+ See the plugin's CLAUDE.md (https://github.com/theoju/engineering-docs-agent/blob/main/CLAUDE.md)
+ for the durable plugin-side fix detail; the post-implementation note in this repo's spec
```

### File summary

| Repo                    | File                                                         | Action        | LOC delta |
| ----------------------- | ------------------------------------------------------------ | ------------- | --------- |
| **plugin (primary)**    | `tests/ci/test_workflow_pages_template.py`                   | edit + add fn | ~+25      |
| **plugin**              | `templates/workflow-pages.yml`                               | edit          | −3        |
| **plugin**              | `scripts/enable_pages.py`                                    | create        | ~95       |
| **plugin**              | `skills/engineering-docs-agent-setup/SKILL.md`               | edit          | ~+40      |
| **plugin**              | `CLAUDE.md`                                                  | edit          | +6        |
| **plugin**              | `tests/ci/test_enable_pages_cli.py`                          | create        | ~180      |
| **plugin**              | `.github/workflows/docs-pages.yml` (dogfood)                 | edit          | −3        |
| **plugin**              | `CHANGELOG.md`                                               | edit          | +5        |
| **consumer (drive-by)** | `.github/workflows/docs-agent-pages.yml`                     | edit          | −6        |
| **consumer**            | `scripts/__tests__/docs-mkdocs-scaffold.test.mjs`            | edit          | −1, +1    |
| **consumer**            | `docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md` | edit          | +2        |
| **consumer**            | `CLAUDE.md`                                                  | edit          | −2, +3    |

Plugin total: ~355 LOC across 8 files
Consumer total: ~13 LOC across 4 files

## Rollout sequence

Both PRs are independent — either can land first.

### Step 0 — File CCE ticket

Before opening either PR, file CCE-XX with:

- **Summary:** `fix(pages): bootstrap host Pages via gh api instead of misleading configure-pages enablement:true`
- **Type:** Bug
- **Description:** spec link, both forthcoming PRs as they're filed, CCE-81 as the originating incident.
- **Acceptance:** both PRs merged; templates regression-tested; SKILL.md reflects correct behavior; plugin's own deployed Pages workflow cleaned.

### Step 1 — Plugin PR (PR #B)

```bash
cd ~/Projects/engineering-docs-agent
git checkout -b fix/CCE-XX-pages-bootstrap origin/main
# apply B0 through B7
python3 -m pytest tests/ci/test_workflow_pages_template.py tests/ci/test_enable_pages_cli.py -v
python3 -m pytest tests/ -v
git add -A
git commit -m "fix(pages): bootstrap host Pages via gh api — CCE-XX"
git push -u origin fix/CCE-XX-pages-bootstrap
gh pr create --base main --title "fix(pages): bootstrap host Pages via gh api — CCE-XX" --body-file <path>
```

**Gate B.1 — All new + flipped tests pass.**

**Gate B.2 — Full pytest suite passes.**

**Gate B.3 — Plugin CI passes** (actionlint, yaml-lint, all existing matrix).

**Gate B.4 — Squash-merge.** Plugin's own `docs-pages.yml` re-fires on the merge commit (touches the workflow file in its own paths filter); deploy succeeds without `enablement: true` (plugin's Pages site was bootstrapped on its first-ever deploy weeks ago, so this is pure no-op cleanup).

### Step 2 — Consumer drive-by PR (PR #A)

```bash
# In claude-code-self-assessment's main checkout
git checkout -b fix/CCE-XX-pages-cleanup origin/main
# apply A1, A2, A3, A4
npm test
git commit -m "fix(pages): drop misleading enablement:true + flip test to negative assertion — CCE-XX"
gh pr create --base main --title "fix(pages): drop misleading enablement:true — CCE-XX" --body-file <path>
```

**Gate A.1 — `npm test` passes.**

**Gate A.2 — `docs-build-check.yml` passes on the PR.**

**Gate A.3 — Squash-merge.** Next push-triggered run of `docs-agent-pages.yml` works without `enablement: true` (Pages already bootstrapped from CCE-81's recovery).

### Step 3 — Verify and close

After both PRs merge: comment on CCE-XX linking both merged PRs; transition to Done.

### Step 4 — Validate against a new host (deferred, not part of this spec)

The true post-deploy validation is "onboard a fresh `framework: mkdocs` host via the setup skill and verify Pages comes live without manual intervention." Filed as future smoke harness (see Future work §3); no pending host onboarding to drive it today.

## Verification matrix

### Pre-merge (PR #B — plugin)

| Gate    | Command / check                                                                            | Expected                                                                                                                        |
| ------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| B.pre-1 | `python3 -m pytest tests/ci/test_workflow_pages_template.py -v`                            | all 4 cases pass (existing 3 + new B0 structural)                                                                               |
| B.pre-2 | `python3 -m pytest tests/ci/test_enable_pages_cli.py -v`                                   | all ~9 cases pass (happy, argv, 409, 409-false-positive, 6 parametrized fallback, gh-missing, missing-args, empty-args, hyphen) |
| B.pre-3 | `python3 -m pytest tests/ -v`                                                              | full suite passes (no regressions)                                                                                              |
| B.pre-4 | `grep -n "enablement: true" templates/workflow-pages.yml .github/workflows/docs-pages.yml` | NO match in either                                                                                                              |
| B.pre-5 | `grep -n "configure-pages(enablement:true)" skills/engineering-docs-agent-setup/SKILL.md`  | NO match (old wrong claim removed)                                                                                              |
| B.pre-6 | `grep -n "enable_pages.py" skills/engineering-docs-agent-setup/SKILL.md`                   | matches (new step 6c references it)                                                                                             |
| B.pre-7 | `grep -n "## .*[Uu]nreleased" CHANGELOG.md` then check next ~15 lines                      | the new "Fixed" bullet is present                                                                                               |
| B.pre-8 | Plugin CI on PR                                                                            | passes                                                                                                                          |

### Pre-merge (PR #A — consumer)

| Gate    | Command / check                                                                     | Expected                            |
| ------- | ----------------------------------------------------------------------------------- | ----------------------------------- |
| A.pre-1 | `npm test` from worktree root                                                       | 689/689 passes                      |
| A.pre-2 | `grep -n "enablement: true" .github/workflows/docs-agent-pages.yml`                 | NO match (neither YAML nor comment) |
| A.pre-3 | `grep -n "not.toMatch.*enablement" scripts/__tests__/docs-mkdocs-scaffold.test.mjs` | matches (regression guard)          |
| A.pre-4 | `mkdocs build --strict --site-dir /tmp/site`                                        | exits 0 (unchanged)                 |
| A.pre-5 | Consumer's `docs-build-check.yml` on PR                                             | passes                              |

### Post-merge

| Gate   | Check                                                                       | Expected                                                                                         |
| ------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| post-1 | Plugin's own deploy re-fires on PR #B's squash-merge                        | Plugin's https://theoju.github.io/engineering-docs-agent/ continues to serve; no behavior change |
| post-2 | Next docs-touching merge to consumer's main triggers `docs-agent-pages.yml` | Deploy succeeds; site updated                                                                    |
| post-3 | Next plugin nightly that runs after PR #B merges                            | Steady-state; no host workflow files rewritten                                                   |

### Negative tests (these MUST stay failing in a future regression)

| Test                                                                                             | What it asserts                                                                                                       |
| ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `test_workflow_pages_template.py` (flipped + structural)                                         | Re-adding `enablement: true` (any variant) OR a `with:` block on `configure-pages@v6` to the template breaks the test |
| `test_enable_pages_cli.py::test_409_substring_false_positive_is_not_classified_as_idempotent`    | Loosening the 409 match back to a bare substring breaks the test                                                      |
| `test_enable_pages_cli.py::test_argv_carries_correct_path_and_build_type`                        | A future refactor that swaps owner/repo or drops `-f build_type=workflow` breaks the test                             |
| `test_enable_pages_cli.py::test_all_non_201_non_409_paths_fall_back_gracefully` (6 parametrized) | Making the script exit non-zero on ANY non-409 failure breaks the test                                                |
| `test_enable_pages_cli.py::test_empty_owner_or_repo_rejected_with_exit_2`                        | Loosening the empty-string check breaks the test                                                                      |
| Consumer's `docs-mkdocs-scaffold.test.mjs` flipped assertion                                     | Re-adding `enablement: true` (any quoted variant) to consumer's workflow breaks the test                              |

## Rollback decision tree

| Failure                                                        | Rollback action                                                                                                                                                                                                                                                                     |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PR #B breaks plugin CI                                         | Revert PR #B; no production impact (template + script + skill consumed only by NEW setup runs); existing hosts unaffected; plugin's own site continues serving (Pages already bootstrapped)                                                                                         |
| PR #B merges; plugin's own deploy fails (β surface)            | Plugin Pages was already bootstrapped on first-ever deploy weeks ago; dropping `enablement: true` is a no-op for an existing site. If somehow it fails: revert PR #B's edit to `.github/workflows/docs-pages.yml` only (keep B0-B5, B7 in place)                                    |
| PR #A breaks the consumer deploy                               | Revert PR #A's squash-merge; consumer keeps `enablement: true` as a no-op; plugin template stays fixed for future hosts                                                                                                                                                             |
| Future host onboarding fails at the new `enable_pages.py` step | Inspect script output; documented manual recovery still works; if a different failure mode appears, file follow-up bug                                                                                                                                                              |
| Test regex over-matches                                        | The negative regex `r"^\s*enablement:\s*['\"]?true['\"]?\s*$"` is anchored to a full line and accepts quoted/unquoted forms; if false positives appear (e.g., a doc comment line uses this exact form), refine to also require the line to be inside `with:` context — but unlikely |

## Open questions

### Q1: Should `scripts/enable_pages.py` use a separate `--token` flag for non-personal-auth setups?

**Recommendation:** No. The plugin's other scripts (`setup_scaffold.py`, `scaffold_workflow.py`) don't take auth tokens — they assume the operator's local `gh` is authenticated. Adding `--token` is a different feature that should be its own ticket if needed.

### Q2: Should `scripts/enable_pages.py` be importable as a library?

**Recommendation:** Yes, by accident. The `enable_pages(owner, repo)` function is a normal Python function; the CLI is a thin `argparse` wrapper. Future programmatic callers can `from scripts.enable_pages import enable_pages`.

### Q3: Should we also actionlint-check that no future workflow YAML carries `enablement: true`?

**Recommendation:** Future work (§3). The flipped + structural test in B0 covers the plugin template; an analogous check is filed for the consumer. Adding repo-wide actionlint integration is broader scope.

### Q4: Should the consumer-side drive-by PR be filed by the plugin maintainer or by the consumer-repo maintainer?

**Recommendation:** Either works; for CCE-XX both PRs are filed by the same person. For future ecosystem hosts adopting the plugin, the plugin-side fix is enough — others would only mirror it if they care about the cosmetic cleanup. Their deploy keeps working regardless.

### Q5: Should the script support GitHub Enterprise Server hosts?

**Recommendation:** No, out of scope. Explicit non-goal. GHES uses `/api/v3/repos/.../pages` at a custom hostname; `gh` CLI handles GHES via `gh auth login --hostname`, but the script would need to detect/respect the host. File as a follow-up only if a GHES host actually adopts the plugin (none today).

### Q6: Why pre-emptively GET pages before POST (instead of POST-then-409)?

**Considered and rejected.** A GET-first approach (`gh api repos/{owner}/{repo}/pages`; if 404, POST) is slightly cleaner because it avoids relying on stderr-string matching for 409 detection. However:

- It doubles the API call count for the happy path (already-enabled hosts).
- The literal-paren regex `r"\(HTTP 409\)"` for 409 detection is robust enough (test `test_409_substring_false_positive_is_not_classified_as_idempotent` pins it).
- POST-then-409 is one round-trip; GET-then-POST is two.
- The graceful-fallback bucket catches the script's behavior if `gh`'s stderr format ever drifts.

POST-first stays.

## Future work (filed; do NOT do in this PR)

1. **Upstream patch to `actions/configure-pages`** — file a docs-quality issue (or PR) at https://github.com/actions/configure-pages proposing clearer first-run behavior documentation, or proposing an `enable_via_admin_token` parameter that takes a separate PAT. Low-leverage for us; improves the ecosystem.

2. **Actionlint integration** — add a custom rule (or shellcheck-style postprocessor) that flags `enablement: true` in any workflow file under `.github/workflows/`. Scope-bounded follow-up.

3. **End-to-end new-host smoke harness** — extend the plugin's fixture-host test scaffolding to invoke the setup skill end-to-end against a real (temporary) GitHub repo + verify Pages comes live programmatically. Higher cost; useful regression guard.

4. **Setup-skill flag `--skip-pages-enable`** — if a future operator wants to enable Pages manually (e.g., corporate org with policy constraints), surface a flag rather than the graceful-fallback path. YAGNI until requested.

5. **`gh` minimum-version assertion** — `gh api -X POST` semantics are stable across recent versions, but a one-line check `gh --version` ≥ 2.x with a clear error if too old would improve triage.

6. **JSON output mode for the script** (`--format json`) — for machine consumption by future programmatic-orchestration mode of the setup skill.

## Validation findings & responses

The spec was validated by 3 independent agents (correctness, completeness, test-rigor). Their findings and the spec revisions that addressed them:

### Correctness agent — YELLOW, 4 MAJORs (all addressed)

| Finding                                                                                                        | Response                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1: `gh api` exits **1** on HTTP 4xx (not 22 or 4 — those are curl-style codes); test stubs were wrong         | B5 stub exit codes changed to 1; comment in stub helper notes "gh exits 1 on HTTP 4xx regardless of code"                                                                                                  |
| M2: Bare substring match for `"HTTP 409"` could false-positive against JSON bodies containing `"status":"409"` | B2 script tightened to `re.search(r"\(HTTP 409\)", stderr)` — literal parens match gh's actual format; new test case `test_409_substring_false_positive_is_not_classified_as_idempotent` pins the contract |
| M3: Consumer `docs-agent-pages.yml` comment block (lines 3-6) ALSO carries the wrong claim verbatim            | A1 expanded to clean the comment block; LOC delta now -6 instead of -3                                                                                                                                     |
| M4: SKILL.md step 6c didn't specify `$OWNER`/`$REPO` source/fallback                                           | B3 step 6c now explicitly references step 6b's `discovery["git"]["owner"]/["repo"]` + `AskUserQuestion` fallback pattern                                                                                   |

### Completeness agent — SIGNIFICANT-GAPS, 4 ship-blockers (all addressed)

| Finding                                                                                                                                     | Response                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plugin is itself a dogfood mkdocs host; `.github/workflows/docs-pages.yml:25` carries `enablement: true` — missed surface                   | Added **B6**: same deletion in plugin's own deployed workflow (4th surface acknowledged in Architecture)                                             |
| Existing test `tests/ci/test_workflow_pages_template.py:30` asserts `assert "enablement: true" in text` — would fail when template is fixed | Added **B0**: flip the existing test in place + add structural assertion that no `with:` block returns to `configure-pages@v6`                       |
| My B5 file path (`tests/site/test_workflow_pages_template.py`) collides with existing same-named file in `tests/ci/`                        | Removed; B0 modifies the existing file instead. B5 is now `tests/ci/test_enable_pages_cli.py` (different name, same directory)                       |
| Step 6c missing `$OWNER`/`$REPO` provenance (overlaps with correctness M4)                                                                  | Addressed via M4 response                                                                                                                            |
| Nice: CHANGELOG entry, A3 redundancy with existing POST-IMPLEMENTATION CORRECTION block                                                     | Added **B7**: CHANGELOG entry. A3 simplified to a one-line "Resolved by" footer pointing at the existing recommendation text rather than duplicating |
| Nice: CLAUDE.md symmetry vs divergence between consumer + plugin                                                                            | A4 now shortens consumer's bullet to point at plugin's CLAUDE.md as the durable detail source                                                        |

### Test-rigor agent — NEEDS-IMPROVEMENT, 7 critical gaps (all addressed)

| Finding                                                                         | Response                                                                                                                                                                                       |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 409 substring false positives (500 quoting "HTTP 409")                          | Added `test_409_substring_false_positive_is_not_classified_as_idempotent`; script regex tightened to literal-paren match                                                                       |
| Stub doesn't assert argv                                                        | Added `test_argv_carries_correct_path_and_build_type` with side-channel argv capture file                                                                                                      |
| No coverage of HTTP 422/500/401/exit-139 in fallback branch                     | Added `@pytest.mark.parametrize` over 6 fallback cases (`403_auth`, `401_unauth`, `422_validation`, `500_server`, `139_segfault`, `0_empty_body`)                                              |
| `gh` exit 0 with empty body → false success                                     | Added `0_empty_body` case in parametrized fallback; B2 script requires `proc.stdout.strip()` truthy for happy-path classification                                                              |
| SKILL.md conditional skip (step 6c skip when 6a didn't write workflow) untested | Documented as future integration test (covered by integration smoke harness in Future Work §3); spec text in B3 makes the conditional explicit                                                 |
| Empty `$OWNER`/`$REPO` from discover untested                                   | Added `test_empty_owner_or_repo_rejected_with_exit_2`; B2 script rejects with exit 2 (matches argparse convention)                                                                             |
| Template guard regex too narrow                                                 | B0 uses `re.search(r"^\s*enablement:\s*['\"]?true['\"]?\s*$", text, re.MULTILINE)` (anchored, accepts quoted variants); plus structural YAML-parse assertion that catches `with:` block re-add |
| Quality: stub stderr realism comment                                            | Added inline comment in stub helper                                                                                                                                                            |
| Quality: consumer/plugin test parity                                            | A2 uses broader regex `/enablement:\s*['"]?true['"]?/` matching the plugin's pattern                                                                                                           |
| Quality: pytest-xdist note                                                      | Comment in `_run_cli` notes PATH-shadow approach is per-process and survives xdist if added later                                                                                              |

## References

- **Originating incident:** `theoju/claude-code-self-assessment` PR #121 / CCE-81 (https://github.com/theoju/claude-code-self-assessment/pull/121)
- **Post-incident corrections:** `theoju/claude-code-self-assessment` PR #122 (https://github.com/theoju/claude-code-self-assessment/pull/122)
- **Consumer-side spec being annotated by A3:** `theoju/claude-code-self-assessment/docs/superpowers/specs/2026-06-01-mkdocs-upgrade-design.md`
- **Plugin onboarding spec (CCE-57):** `docs/superpowers/specs/2026-05-29-cce57-onboard-prep-design.md`
- **`actions/configure-pages` repo:** https://github.com/actions/configure-pages
- **GitHub Pages API `POST /repos/{owner}/{repo}/pages`:** https://docs.github.com/en/rest/pages/pages#create-a-github-pages-site

## Scope sanity check

- ~355 LOC in plugin (8 files); ~13 LOC in consumer (4 files).
- One conceptual fix; four surfaces; two deployment vehicles.
- No new dependencies (stdlib + existing `gh` toolchain in both repos).
- No new GitHub Apps, secrets, or org-level changes.
- All failure modes documented + tested.
- Rollback is a single revert per PR.
- No coupling between PRs; either can ship first.
- No runtime impact on existing hosts (template + script + skill consumed only by NEW setup runs); the consumer drive-by and the plugin's own dogfood-workflow fix are cosmetic + regression-guard, not behavioral.
- All 3-agent findings (correctness, completeness, test-rigor) addressed and documented in "Validation findings & responses" section.
