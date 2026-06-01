---
status: draft
ticket: CCE-70
related: CCE-57, CCE-58, CCE-67
created: 2026-05-31
---

# CCE-70 — Prevent gitlink contamination of host repos by `.docs-agent-plugin/`

## Goal

Stop the orchestrator from committing the vendored plugin checkout (`.docs-agent-plugin/`) as a gitlink (submodule entry, mode 160000) into the host's docs-agent PR. The plugin checkout is workflow-only infrastructure and must never appear in the host's git history.

## Background

`scripts/orchestrator_runner.py:1767` runs `git -C repo_root add .` after the orchestrator pipeline writes authored docs + state.json + whats-new entries. The host's nightly workflow (`templates/workflow-run.yml:40` and host-side `.github/workflows/docs-agent-nightly.yml`) checks out the engineering-docs-agent plugin into a separate path: `actions/checkout@v5 with path: .docs-agent-plugin`. That creates a nested git checkout at the runner workspace root.

Because no `.gitignore` entry excludes `.docs-agent-plugin/`, git treats the nested checkout as a submodule and `git add .` stages it as a gitlink pointing at the plugin's HEAD SHA from the runner. Every nightly run contaminates the host's docs-agent PR with this drifting gitlink — SHA changes nightly to whatever the plugin's main is at the time of the run.

**Evidence:** ADIS PR #394 (merged 2026-06-01 at `8c00014`) added `.docs-agent-plugin` with mode 160000 pointing at `6e812a5e58d17760fd2a0b8ac751021fb3bf3080` (engineering-docs-agent's HEAD at that moment). Not a deliberate SHA-pin marker — incidental contamination from `git add .`.

The dogfood repo isn't affected because the orchestrator runs from within the plugin itself (no nested checkout). The bug surfaces only on host repos that use the vendored-checkout pattern — i.e. every CCE-57/58-onboarded host.

## Approach

Two-layer fix:

**Layer 1 (defensive, plugin-side):** harden `git add` at the orchestrator site so it never sweeps the `.docs-agent-plugin/` path. Use git's exclude pathspec to drop the nested checkout from staging. This is the primary fix — works on every host immediately after the plugin updates, without any host-side change.

**Layer 2 (preventative, setup-side):** update the setup skill (`skills/engineering-docs-agent-setup/SKILL.md`) to write `.docs-agent-plugin/` into the host's `.gitignore` during onboarding. This belt-and-suspenders coverage protects against any future code path that might `git add` from the host root outside the orchestrator's staging helper.

**Layer 3 (host-side, out of scope):** ADIS main currently carries the gitlink from `8c00014`. A follow-up host PR (`git rm --cached .docs-agent-plugin` + commit) is tracked separately; not part of this plugin change.

Rejected alternatives:

- **Refactor `open_or_append_pr` to take an explicit list of paths to stage.** Cleaner but invasive — requires plumbing `authored_paths + state_path + whats_new_path` through several call sites. Pathspec exclusion gets the same staging guarantee with no signature change.
- **Add `.gitignore` only, leave `git add .` alone.** Insufficient — relies on every host being re-set-up. The pathspec exclusion is what protects already-onboarded hosts on the next nightly.
- **Stop using `path: .docs-agent-plugin` in the workflow.** Would require restructuring the launcher pattern. The vendored-checkout pattern is well-established and per CCE-57 design intentional. Adapt the staging logic to it.

## What changes

### 1. Extract a staging helper — `scripts/orchestrator_runner.py`

Today (lines 1767-1773):

```python
add = subprocess.run(
    ["git", "-C", str(repo_root), "add", "."], capture_output=True, text=True
)
if add.returncode != 0:
    reasons.append(
        (f"git_add_failed: {add.stderr.strip()[:_STDERR_TRUNCATE]}", False)
    )
    return None, reasons
```

Replace with a call to a new helper `_stage_docs_run_changes(repo_root)`:

```python
add_rc, add_stderr = _stage_docs_run_changes(repo_root)
if add_rc != 0:
    reasons.append(
        (f"git_add_failed: {add_stderr[:_STDERR_TRUNCATE]}", False)
    )
    return None, reasons
```

Helper (module-level, near the other private helpers):

```python
def _stage_docs_run_changes(repo_root: Path) -> tuple[int, str]:
    """Stage all run-emitted changes in `repo_root`, excluding the vendored
    plugin checkout at `.docs-agent-plugin/`.

    The host's workflow checks out the plugin into `.docs-agent-plugin/`
    via actions/checkout (see templates/workflow-run.yml). Without an
    explicit exclusion, `git add .` would register the nested checkout as
    a submodule gitlink (mode 160000) in the host's docs-agent PR — CCE-70.
    """
    result = subprocess.run(
        [
            "git", "-C", str(repo_root), "add", ".", "--",
            ":!.docs-agent-plugin",
            ":!.docs-agent-plugin/**",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr.strip()
```

`':!path'` is git's exclude pathspec magic — it removes any matching path from the set even though `.` matches it. Two patterns cover both the directory itself (the gitlink entry) and any contents underneath.

### 2. Setup skill update — `skills/engineering-docs-agent-setup/SKILL.md`

The existing step 6 (line 33) writes config + workflow files but does not touch `.gitignore`. Add a new sub-step:

> After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.

### 3. Regression test — `tests/orchestrator/`

New file `tests/orchestrator/test_gitlink_exclusion.py`:

```python
"""CCE-70: orchestrator must not stage .docs-agent-plugin as a gitlink.

The host's docs-agent-nightly workflow checks out the plugin into
.docs-agent-plugin/. Without an explicit exclude pathspec, `git add .`
would register that nested checkout as a submodule entry (mode 160000)
in the host's docs-agent PR.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _init_git_repo(path: Path) -> None:
    """Initialize a real git repo at `path` with author config."""
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "test"],
        check=True,
    )


def _create_nested_plugin_checkout(host_root: Path) -> None:
    """Create a fake `.docs-agent-plugin/` checkout that looks like a
    submodule to git (presence of a `.git` entry inside it). Mirrors how
    actions/checkout@v5 leaves the path in CI."""
    plugin = host_root / ".docs-agent-plugin"
    plugin.mkdir()
    # actions/checkout creates a real .git directory; for the gitlink
    # detection to fire we only need git to see *something* it treats as a
    # repo boundary. A `.git` file (gitdir reference) is sufficient.
    (plugin / ".git").write_text("gitdir: /tmp/fake-plugin-git\n")
    (plugin / "README.md").write_text("# plugin sentinel\n")


def test_stage_docs_run_changes_excludes_plugin_checkout(tmp_path: Path) -> None:
    """The staging helper must NOT register .docs-agent-plugin as a gitlink."""
    _init_git_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new-page.md").write_text("# new docs page\n")
    _create_nested_plugin_checkout(tmp_path)

    rc, stderr = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0, f"staging failed: rc={rc}, stderr={stderr!r}"

    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()

    assert "docs/new-page.md" in staged, (
        f"authored docs page must be staged; got {staged}"
    )
    assert ".docs-agent-plugin" not in staged, (
        f".docs-agent-plugin must NOT be staged as a gitlink; got {staged}"
    )
    # Defense in depth: also verify no path beginning with the plugin prefix
    # leaked into the index via the `**` glob.
    plugin_entries = [p for p in staged if p.startswith(".docs-agent-plugin")]
    assert not plugin_entries, (
        f"no .docs-agent-plugin/* entries should be staged; got {plugin_entries}"
    )


def test_stage_docs_run_changes_stages_state_and_whats_new(tmp_path: Path) -> None:
    """The staging helper must still stage all the run's intended outputs:
    state.json bump, whats-new entry, and the docs pages."""
    _init_git_repo(tmp_path)
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "state.json").write_text("{}\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "whats-new.md").write_text("# What's new\n")
    (tmp_path / "docs" / "page.md").write_text("# new page\n")

    rc, _ = orun._stage_docs_run_changes(tmp_path)
    assert rc == 0

    staged = set(subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines())

    assert ".engineering-docs-agent/state.json" in staged
    assert "docs/whats-new.md" in staged
    assert "docs/page.md" in staged
```

Two tests: one pins the exclusion behavior; the other guards against an over-eager pathspec that accidentally excludes legitimate paths.

## What does NOT change

- `open_or_append_pr` signature — same arguments, same return shape.
- Push, commit, checkout, or fetch logic.
- The vendored-checkout pattern in `templates/workflow-run.yml` — that is the correct host-side launcher pattern.
- Existing tests in `tests/orchestrator/test_open_or_append_pr.py` — they stub subprocess entirely, so the helper extraction is invisible to them.
- ADIS main's existing contaminated gitlink — addressed via a separate host-side PR after this lands.

## Data flow

```
nightly run on host
  └─→ orchestrator pipeline writes:
      - docs/<authored>.md            (legitimate)
      - docs/whats-new.md             (legitimate)
      - .engineering-docs-agent/state.json (legitimate)
      .docs-agent-plugin/             (workflow's actions/checkout side-effect — NOT legitimate)
  └─→ open_or_append_pr
      └─→ _stage_docs_run_changes(repo_root)
          └─→ git add . -- ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'
              └─→ stages all legitimate paths
              └─→ EXCLUDES the nested plugin checkout
      └─→ git commit
      └─→ git push
      └─→ gh pr create
```

## Error handling

- **`.docs-agent-plugin/` is also a host-tracked path** (unlikely but theoretically possible if a host already had files at that path before onboarding): the exclude pathspec drops it from staging during docs-agent runs. The host can still commit changes to it manually. Acceptable; setup skill should detect this collision during onboarding (out of scope here).
- **Git version too old to support `':!path'` pathspec magic**: the syntax is supported in git ≥ 1.9 (released 2014). Every modern runner image (ubuntu-latest, macos-latest) ships git ≥ 2.x. No version check needed.
- **Pathspec exclusion does not affect already-committed gitlinks**: if a previous run committed `.docs-agent-plugin` as a gitlink (as ADIS did), the new staging step will NOT un-stage it. Host-side cleanup PR handles that case.

## Testing

1. **`tests/orchestrator/test_gitlink_exclusion.py`** (new, two tests):
   - `test_stage_docs_run_changes_excludes_plugin_checkout` — fails without the fix; passes with the exclude pathspec.
   - `test_stage_docs_run_changes_stages_state_and_whats_new` — guards against over-eager exclusion.
2. **Existing tests in `tests/orchestrator/test_open_or_append_pr.py`** stub subprocess and remain green — the helper extraction is invisible to them.
3. **Full suite (`python3 -m pytest`)** — must stay green.
4. **Post-merge verification**: re-trigger docs-agent-nightly on CCSA. Confirm the resulting docs-agent PR's `git show <merge-commit> --stat` does NOT include `.docs-agent-plugin`. Same on ADIS.

## Migration

- **Plugin and dogfood**: no migration. The dogfood repo never had the contamination (it doesn't use the vendored-checkout pattern).
- **CCSA**: no host-side action needed. The contamination on CCSA's closed partial PRs (#103, #105) never reached host main. Next nightly will be clean.
- **ADIS**: one-commit follow-up PR `chore(CCE-70): git rm --cached .docs-agent-plugin` on theoju/advanced-data-import-system. Out of scope for this plugin PR; tracked separately.

## Out of scope

- Refactoring `open_or_append_pr` to accept an explicit staging list — rejected alternative above.
- The setup skill running a `.gitignore` migration on already-onboarded hosts — those hosts get the protection automatically via the orchestrator-side exclusion. The setup skill update applies to NEW onboardings only.
- ADIS host cleanup — own follow-up PR.

## Risks

- **Exclude pathspec syntax requires the `--` separator** to be unambiguous. Forgetting it makes git interpret `':!path'` as a literal pathname and fails to stage anything. The helper uses `--` explicitly; the regression test catches the mistake.
- **A future maintainer adds another `git add .` call elsewhere in the orchestrator without using the helper**: defense via the `.gitignore` setup-skill update plus a code review reminder. Worth a follow-up audit pass that grep-fails CI on bare `git add` in the orchestrator (out of scope here).

## Success criteria

1. Tomorrow's nightly on CCSA and ADIS opens a docs-agent PR whose diff contains NO `.docs-agent-plugin` entry.
2. The two regression tests fail without the staging helper and pass with it.
3. `python3 -m pytest` stays green.
4. ADIS host main has the existing contamination reverted in a separate PR after the plugin fix merges.

## References

- `scripts/orchestrator_runner.py:1767` — the `git add .` site to replace
- `scripts/orchestrator_runner.py:1713-1730` — surrounding fetch + checkout logic (unchanged)
- `templates/workflow-run.yml:40` — `actions/checkout@v5 with path: .docs-agent-plugin`
- `skills/engineering-docs-agent-setup/SKILL.md:33` — setup step to extend with `.gitignore` write
- ADIS#394 (merged at `8c000145ebe1d05aa6922234554ec3c8541bbdf6`) — first observed contamination
- git pathspec exclusion docs: https://git-scm.com/docs/gitglossary#Documentation/gitglossary.txt-aiddefpathspecapathspec
