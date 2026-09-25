# tests/orchestrator/test_plugin_dir_write_denial.py
"""CCE-188: --plugin-dir must not shadow the worktree the agent has to write.

## What happened

Every dispatch passes ``--plugin-dir _PLUGIN_ROOT`` so agents resolve, and
Claude Code protects plugin-owned files from agent writes. That protection is
correct on its own — an agent should not be able to rewrite its own definition.

But **this repo IS the plugin**: ``.claude-plugin/plugin.json`` sits at the
repo root beside ``agents/`` and ``skills/``. So when the docs-agent documents
its OWN repo, ``_PLUGIN_ROOT == cwd`` and the entire worktree becomes
plugin-owned. Every page-author write is refused with::

    Claude requested permissions to edit <path> which is a sensitive file.

Measured on run 36007491599 (the last *successful* nightly, exit 0): 13
page-author dispatches, all ``returncode 0``, **17 Edit/Write attempts, 17
denials, 0 pages written**.

## Why it stayed invisible for weeks

The caller checked ``if out.get("ok"):`` with **no else**. A schema-valid
``ok: false`` fell straight through — no reason, no banner. That run's digest
reported only a window cap and a summary-cache line, exited 0, and read as a
healthy partial while the baseline froze and the CCE-175/178 stall escape
abandoned one PR's documentation every four days (``#221`` was lost this way).

So this module pins **both halves**: the permission fix, and the loudness.
Restoring writes without the reason would leave the same blind spot for
whatever breaks authoring next.

## Why `auto` and not `acceptEdits`

Measured against a scratch reproduction, all with ``--plugin-dir .``:

===================================  =======  =================
mode                                 wrote    sensitive denials
===================================  =======  =================
(none)                               0        4
``acceptEdits``                      0        4
``bypassPermissions``                1        0
``auto``                             1        0
===================================  =======  =================

``acceptEdits`` is in the CLI's bypass set yet the plugin-dir check still
fires, so it is **not** a fix. ``bypassPermissions`` works but disables every
check, which is not something to hand ``source-collector`` — it carries
``Bash``. ``auto`` is the narrowest mode that clears the gate, and
``--allowedTools`` still bounds each agent to its declared tools.

## Scope

The host shape is unaffected and must stay that way. On a host repo the plugin
installs to ``<host>/.docs-agent-plugin/`` — a SUBDIRECTORY — so docs are
siblings of the plugin dir and already writable with no permission mode at all
(verified). ``test_host_shape_gets_no_permission_mode`` is the regression guard
that keeps host runs on today's stricter default.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as runner  # noqa: E402


# --------------------------------------------------------------------------
# The predicate
# --------------------------------------------------------------------------


def test_self_documenting_repo_is_shadowed(tmp_path, monkeypatch):
    """cwd == _PLUGIN_ROOT: the engineering-docs-agent documenting itself."""
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", tmp_path.resolve())
    assert runner._plugin_dir_shadows_worktree(tmp_path) is True


def test_worktree_below_the_plugin_root_is_shadowed(tmp_path, monkeypatch):
    """_PLUGIN_ROOT as an ANCESTOR of cwd is shadowed too.

    Not hypothetical: a git worktree of the plugin checked out beneath the
    plugin root has this shape, and the files would be equally unwritable.
    """
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", tmp_path.resolve())
    nested = tmp_path / "worktrees" / "wt1"
    nested.mkdir(parents=True)
    assert runner._plugin_dir_shadows_worktree(nested) is True


def test_host_shape_is_not_shadowed(tmp_path, monkeypatch):
    """The plugin nested INSIDE the worktree — every real host repo.

    This is the case that must keep today's behaviour. Writes already succeed
    here with no permission mode, so relaxing it would be an unforced
    reduction in posture on every host.
    """
    plugin = tmp_path / ".docs-agent-plugin"
    plugin.mkdir()
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", plugin.resolve())
    assert runner._plugin_dir_shadows_worktree(tmp_path) is False


def test_unrelated_directories_are_not_shadowed(tmp_path, monkeypatch):
    plugin = tmp_path / "plugin"
    host = tmp_path / "host"
    plugin.mkdir()
    host.mkdir()
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", plugin.resolve())
    assert runner._plugin_dir_shadows_worktree(host) is False


def test_none_cwd_is_not_shadowed():
    """No cwd is not a reason to relax permissions."""
    assert runner._plugin_dir_shadows_worktree(None) is False


# --------------------------------------------------------------------------
# The argv
# --------------------------------------------------------------------------


def _capture(captured: dict, stdout: str = '{"ok": true}'):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return fake_run


def test_shadowed_dispatch_gets_permission_mode_auto(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", tmp_path.resolve())
    monkeypatch.setattr(subprocess, "run", _capture(captured))

    runner.dispatch_subagent(
        "page-author", {"x": 1}, dry_run_dir=None, cwd=tmp_path
    )

    cmd = captured["cmd"]
    assert "--permission-mode" in cmd, (
        "a shadowed worktree must relax the mode or every write is refused as "
        f"a sensitive file; argv={cmd}"
    )
    assert cmd[cmd.index("--permission-mode") + 1] == "auto", (
        "must be `auto`: `acceptEdits` was measured NOT to clear the "
        "plugin-dir gate, and `bypassPermissions` disables every check for "
        f"agents that carry Bash. argv={cmd}"
    )
    # The tool allow-list is the remaining bound and must survive.
    assert "--allowedTools" in cmd


def test_host_shape_gets_no_permission_mode(tmp_path, monkeypatch):
    """The blast-radius guard. Host runs keep the stricter default."""
    captured: dict = {}
    plugin = tmp_path / ".docs-agent-plugin"
    plugin.mkdir()
    monkeypatch.setattr(runner, "_PLUGIN_ROOT", plugin.resolve())
    monkeypatch.setattr(subprocess, "run", _capture(captured))

    runner.dispatch_subagent(
        "page-author", {"x": 1}, dry_run_dir=None, cwd=tmp_path
    )

    assert "--permission-mode" not in captured["cmd"], (
        "writes already succeed on the host shape with no permission mode; "
        "adding one here lowers posture on every host for no benefit. "
        f"argv={captured['cmd']}"
    )


# --------------------------------------------------------------------------
# The loudness
# --------------------------------------------------------------------------


def test_page_author_refusal_is_reported_not_swallowed(
    tmp_path, init_host, read_current_run
):
    """A schema-valid `ok: false` must produce a partial reason.

    Before CCE-188 this fell through an `if out.get("ok"):` with no else, which
    is how 17 denied writes produced a digest that named none of them.
    """
    import shutil

    fakes = tmp_path / "fakes_refused"
    shutil.copytree(Path(__file__).parent / "fakes_degraded_advance", fakes)
    (fakes / "fake_page_author.json").write_text(
        json.dumps(
            {
                "path": "docs/site-src/core/whats-new.md",
                "action": "edit",
                "ok": False,
                "error": (
                    "edit_permission_denied: the harness blocked write access"
                ),
            }
        )
    )

    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "orchestrator_runner.py"),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(fakes),
        ],
        capture_output=True,
        text=True,
    )
    cr = read_current_run(state_path)
    reasons = cr["partial_reasons"]

    assert any(r.startswith("page_author_error:") for r in reasons), (
        "a page-author refusal must be named in partial_reasons; swallowing it "
        f"is the CCE-188 blind spot. reasons={reasons}"
    )
    assert any("edit_permission_denied" in r for r in reasons), (
        "the agent's own error text must survive into the reason — it is the "
        f"only clue an operator gets. reasons={reasons}"
    )
    assert cr["partial"] is True
    assert not cr.get("blind"), (
        "an unlanded page holds work back rather than consuming it, so this is "
        f"degraded, not blind (CCE-144). current_run={cr}"
    )
    assert result.returncode == 0
    assert (
        json.loads(state_path.read_text())["last_successful_run"]["head_sha"]
        == "old_sha_000"
    ), "nothing was documented, so the baseline must not move"
