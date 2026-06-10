"""CCE-101: auto-merge gate tests.

`resolve_merge_settings` + `_maybe_auto_merge` — the runner-side
poll-and-merge that lands fully-green non-partial docs-agent PRs
without an operator. All auto-merge reasons are info_only=True;
every failure degrades to leaving the PR open (pre-CCE-101 behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402
from gh_client import FakeGhClient, GhResult  # noqa: E402


def test_resolve_merge_settings_absent_block_defaults_to_auto():
    """CCE-101 contract: absent key = auto-merge ON."""
    s = orun.resolve_merge_settings({})
    assert s == {
        "policy": "auto",
        "checks_grace_seconds": 120,
        "checks_timeout_seconds": 900,
    }


def test_resolve_merge_settings_absent_policy_defaults_to_auto():
    s = orun.resolve_merge_settings({"merge": {"checks_grace_seconds": 5}})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 5
    assert s["checks_timeout_seconds"] == 900


def test_resolve_merge_settings_manual_respected():
    s = orun.resolve_merge_settings({"merge": {"policy": "manual"}})
    assert s["policy"] == "manual"


def test_resolve_merge_settings_non_dict_block_falls_back():
    s = orun.resolve_merge_settings({"merge": "auto"})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 120
