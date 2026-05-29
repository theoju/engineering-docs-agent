"""CCE-48: surface partial_reasons in $GITHUB_STEP_SUMMARY.

The runner's _write_step_summary helper:
- no-ops when $GITHUB_STEP_SUMMARY is unset (local runs, unit tests)
- appends a bulleted digest when env var is set + partial_reasons non-empty
- swallows OSError when the env-var-pointed path is unwritable
- runs from a try/finally in run() so hard-fail paths still flush
"""

from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_helper_noop_when_env_var_unset(tmp_path: Path, monkeypatch):
    """When GITHUB_STEP_SUMMARY is unset, the helper returns silently
    with no side effects — local runs and unit tests behave as today."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": ["source_collector_invalid: returned None"],
        },
    }
    # Should not raise; should not touch any file.
    orun._write_step_summary(state, tmp_path)
    # Nothing on disk (assertion implicit — helper has no path to write to).
    assert list(tmp_path.iterdir()) == []


def test_helper_writes_digest_when_env_var_set_and_reasons_present(
    tmp_path: Path, monkeypatch
):
    """With GITHUB_STEP_SUMMARY pointing to a file and partial_reasons
    non-empty, the helper appends a bulleted digest section."""
    summary = tmp_path / "summary.md"
    summary.write_text("## existing content\n")  # helper must APPEND, not overwrite
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": [
                "source_collector_invalid: returned None",
                "page_author_invalid: docs/site-src/core/index.md",
            ],
        },
    }
    orun._write_step_summary(state, tmp_path)
    contents = summary.read_text()
    # Existing content preserved (append, not overwrite).
    assert "## existing content" in contents
    # New heading present.
    assert "## docs-agent partial_reasons" in contents
    # Each reason rendered as a bullet.
    assert "- source_collector_invalid: returned None" in contents
    assert "- page_author_invalid: docs/site-src/core/index.md" in contents
    # The bulleted list lives inside a "WARNING — Partial run" block.
    assert "WARNING — Partial run" in contents


def test_helper_noop_when_partial_reasons_empty(tmp_path: Path, monkeypatch):
    """Clean runs (partial_reasons == []) leave the summary file
    untouched — the workflow's existing `state.json` cat step is
    sufficient signal for green runs."""
    summary = tmp_path / "summary.md"
    summary.write_text("baseline\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {"partial": False, "partial_reasons": []},
    }
    orun._write_step_summary(state, tmp_path)
    assert summary.read_text() == "baseline\n"


def test_helper_noop_when_current_run_missing(tmp_path: Path, monkeypatch):
    """If state has no current_run (defensive — shouldn't happen at the
    flush point), the helper returns silently rather than KeyError."""
    summary = tmp_path / "summary.md"
    summary.write_text("baseline\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {"version": "1"}
    orun._write_step_summary(state, tmp_path)
    assert summary.read_text() == "baseline\n"


def test_helper_swallows_oserror_when_path_unwritable(tmp_path: Path, monkeypatch):
    """If the env-var-pointed path is unwritable (missing parent dir,
    read-only fs), the helper swallows OSError so the runner's primary
    output isn't held hostage by a diagnostics sink."""
    bad_path = tmp_path / "does" / "not" / "exist" / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(bad_path))
    state = {
        "version": "1",
        "current_run": {"partial": True, "partial_reasons": ["x"]},
    }
    # Must not raise.
    orun._write_step_summary(state, tmp_path)


def test_run_invokes_write_step_summary_in_finally_on_hard_fail(
    tmp_path: Path, monkeypatch
):
    """Stronger contract: the finally block calls _write_step_summary
    even when run() propagates an exception from downstream."""
    import shutil
    import subprocess as sp

    HOST = Path(__file__).parent.parent / "fixtures" / "e2e_host"
    FAKES = Path(__file__).parent / "fakes"
    host = tmp_path / "host"
    shutil.copytree(HOST, host)
    sp.run(["git", "-C", str(host), "init", "-q"], check=True)
    sp.run(["git", "-C", str(host), "config", "user.email", "t@t"], check=True)
    sp.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    sp.run(["git", "-C", str(host), "add", "."], check=True)
    sp.run(["git", "-C", str(host), "commit", "-q", "-m", "init"], check=True)

    calls = []

    def fake_write(state, repo_root):
        calls.append(
            {
                "partial_reasons": list(
                    (state.get("current_run") or {}).get("partial_reasons", [])
                )
            }
        )

    monkeypatch.setattr(orun, "_write_step_summary", fake_write)

    def fake_open(*args, **kwargs):
        raise RuntimeError("simulated hard-fail mid-PR-open")

    monkeypatch.setattr(orun, "open_or_append_pr", fake_open)

    raised = None
    try:
        orun.run(host, dry_run_dir=FAKES, no_pr=False)
    except RuntimeError as e:
        raised = e

    assert raised is not None, (
        "expected the patched open_or_append_pr to propagate its RuntimeError"
    )
    assert len(calls) >= 1, (
        "expected _write_step_summary to be called from run()'s finally; "
        f"got {len(calls)} calls"
    )


def test_run_invokes_write_step_summary_on_clean_success(tmp_path: Path, monkeypatch):
    """On a clean success path, the finally block still fires —
    _write_step_summary itself is the gate on writing nothing for
    empty partial_reasons."""
    import shutil
    import subprocess as sp

    HOST = Path(__file__).parent.parent / "fixtures" / "e2e_host"
    FAKES = Path(__file__).parent / "fakes"
    host = tmp_path / "host"
    shutil.copytree(HOST, host)
    sp.run(["git", "-C", str(host), "init", "-q"], check=True)
    sp.run(["git", "-C", str(host), "config", "user.email", "t@t"], check=True)
    sp.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    sp.run(["git", "-C", str(host), "add", "."], check=True)
    sp.run(["git", "-C", str(host), "commit", "-q", "-m", "init"], check=True)

    calls = []

    def fake_write(state, repo_root):
        calls.append(True)

    monkeypatch.setattr(orun, "_write_step_summary", fake_write)

    rc = orun.run(host, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0, f"expected clean run to exit 0; got {rc}"
    assert len(calls) >= 1, (
        f"expected _write_step_summary to fire on clean-success path; "
        f"got {len(calls)} calls"
    )
