# tests/orchestrator/test_window_cap.py
"""CCE-169: the pre-admission PR-count window cap.

The review window had no upper bound, so a stalled baseline widened by a day
every night and each run finished a smaller fraction of it. These tests pin the
cap itself (this file's first half) and the third-category routing that keeps a
capped PR out of the deferral machinery while still stopping the cursor at the
cap boundary (second half, added in Task 2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


# ---------------------------------------------------------------------------
# resolve_window_cap
# ---------------------------------------------------------------------------


def test_window_cap_defaults_to_ten():
    """The default is the whole point of CCE-169 and NOTHING else can catch it.

    Every `fake_source_collector.json` in the tree tops out at 3 PRs, and each
    helper that rewrites them keeps 3 — so `len(prs) > cap` is False for any
    default >= 3 and no end-to-end test can observe the value. An implementer
    who writes `int(run_cfg.get("window_pr_cap") or 0)` ships the rejected
    off-by-default alternative with every other test green.
    """
    assert orun.DEFAULT_WINDOW_PR_CAP == 10
    assert orun.resolve_window_cap({}) == 10
    assert orun.resolve_window_cap({"run": {}}) == 10


def test_window_cap_reads_the_config_key():
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 25}}) == 25


def test_window_cap_zero_is_unlimited():
    """`0` is the advertised opt-out, so it must survive as 0.

    This is why the resolver tests `val is None` and not truthiness: `or
    DEFAULT` would silently rewrite an explicit 0 back to 10.
    """
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 0}}) == 0


def test_window_cap_tolerates_a_malformed_run_block():
    """`_run_cfg` exists because `config.get("run") or {}` raises
    AttributeError on `run: "nonsense"`. Mirror its siblings, do not reinvent.
    """
    assert orun.resolve_window_cap({"run": "nonsense"}) == 10
    assert orun.resolve_window_cap({"run": None}) == 10
